"""
Image Converter — FastAPI Backend
Expone la lógica de conversión existente como API REST + SSE.

Uso:
    pip install fastapi uvicorn
    python main.py

Luego abre el frontend en el navegador (index.html).
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import tkinter as tk
from tkinter import filedialog
import queue
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

CONFIG_FILENAME = "image_converter_config.json"
DEFAULT_MAGICK_PATH = "magick"

DEFAULT_IMAGE_EXTENSIONS = [
    ".avif", ".png", ".gif", ".jpg", ".jpeg", ".heic",
    ".webp", ".dng", ".arw", ".svg",
]

FORMAT_PRESETS = {
    "JPG":  {"extension": "jpg",  "quality": 85,  "description": "Equilibrio ideal para fotos. Recomendado entre 70-95."},
    "WEBP": {"extension": "webp", "quality": 85,  "description": "Alta compresión con excelente calidad visual."},
    "AVIF": {"extension": "avif", "quality": 65,  "description": "Mejor compresión disponible. Calidad 60-70 óptima."},
    "PNG":  {"extension": "png",  "quality": 100, "description": "Sin pérdida. Archivos más pesados."},
}

if sys.platform == "win32":
    SUBPROCESS_FLAGS = 0x08000000
else:
    SUBPROCESS_FLAGS = 0


# ─────────────────────────────────────────────────────────────────────────────
# DATACLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ImageConverterConfig:
    input_dir: str = ""
    output_dir: str = ""
    magick_path: str = DEFAULT_MAGICK_PATH
    output_format: str = "WEBP"
    output_extension: str = "webp"
    quality: int = 85
    resize_enabled: bool = False
    resize_width: int = 2000
    force_resize_all: bool = False
    append_resize_tag: bool = False
    recursive: bool = True
    overwrite_existing: bool = True
    open_output_when_done: bool = False
    strip_metadata: bool = True
    auto_sharpening: bool = False
    image_extensions: List[str] = field(default_factory=lambda: list(DEFAULT_IMAGE_EXTENSIONS))

    def normalize(self) -> None:
        self.output_format = self.output_format.upper().strip()
        if self.output_format not in FORMAT_PRESETS:
            self.output_format = "WEBP"
        self.output_extension = FORMAT_PRESETS[self.output_format]["extension"]
        self.quality = max(1, min(100, int(self.quality)))
        self.resize_width = max(1, int(self.resize_width))
        clean_exts = []
        for ext in self.image_extensions:
            ext = ext.strip().lower()
            if not ext:
                continue
            if not ext.startswith("."):
                ext = "." + ext
            if ext not in clean_exts:
                clean_exts.append(ext)
        self.image_extensions = clean_exts or list(DEFAULT_IMAGE_EXTENSIONS)


# ─────────────────────────────────────────────────────────────────────────────
# PYDANTIC MODELS (para los endpoints)
# ─────────────────────────────────────────────────────────────────────────────

class ConversionRequest(BaseModel):
    input_dir: str
    output_dir: str
    magick_path: str = DEFAULT_MAGICK_PATH
    output_format: str = "WEBP"
    quality: int = 85
    resize_enabled: bool = False
    resize_width: int = 2000
    force_resize_all: bool = False
    append_resize_tag: bool = False
    recursive: bool = True
    overwrite_existing: bool = True
    strip_metadata: bool = True
    auto_sharpening: bool = False
    image_extensions: List[str] = field(default_factory=lambda: list(DEFAULT_IMAGE_EXTENSIONS))


class ConfigSaveRequest(BaseModel):
    config: dict


# ─────────────────────────────────────────────────────────────────────────────
# WORKER BRIDGE (thread-safe)
# ─────────────────────────────────────────────────────────────────────────────

class OperationCancelled(Exception):
    pass


class CancellationToken:
    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self.active_process: Optional[subprocess.Popen] = None

    def cancel(self) -> None:
        self._cancelled.set()
        proc = self.active_process
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                for _ in range(10):
                    if proc.poll() is not None:
                        break
                    time.sleep(0.1)
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def check(self) -> None:
        if self._cancelled.is_set():
            raise OperationCancelled()


class WorkerBridge:
    def __init__(self) -> None:
        self.q: queue.Queue[Tuple[str, Any]] = queue.Queue()
        self.cancel_token = CancellationToken()

    def log(self, message: str, level: str = "INFO") -> None:
        self.q.put(("log", {"message": message, "level": level, "ts": datetime.now().strftime("%H:%M:%S")}))

    def progress(self, current: int, total: int, label: str = "") -> None:
        self.q.put(("progress", {"current": current, "total": total, "label": label}))

    def status(self, text: str) -> None:
        self.q.put(("status", {"text": text}))

    def stats(self, data: dict) -> None:
        self.q.put(("stats", data))

    def done(self, success: bool, summary: str = "") -> None:
        self.q.put(("done", {"success": success, "summary": summary}))

    def drain(self) -> List[Tuple[str, Any]]:
        events = []
        while True:
            try:
                events.append(self.q.get_nowait())
            except queue.Empty:
                break
        return events


# ─────────────────────────────────────────────────────────────────────────────
# LÓGICA DE CONVERSIÓN (portada del script original)
# ─────────────────────────────────────────────────────────────────────────────

def run_subprocess_streaming(executable, args, bridge, *, log_output=False):
    output_lines = []
    cmd = [executable] + args
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
            errors="replace", bufsize=1, creationflags=SUBPROCESS_FLAGS,
        )
    except FileNotFoundError:
        raise RuntimeError(f"No se encontró ImageMagick en: {executable}")

    bridge.cancel_token.active_process = proc
    try:
        for line in proc.stdout:
            line = line.rstrip("\r\n")
            if line:
                output_lines.append(line)
                if log_output:
                    bridge.log(f"  {line}", "DIM")
            if bridge.cancel_token.is_cancelled():
                break
        proc.wait()
    finally:
        bridge.cancel_token.active_process = None

    return proc.returncode, "\n".join(output_lines)


def _get_image_files(input_dir, extensions, recursive):
    allowed = set()
    for ext in extensions:
        ext = ext.strip().lower()
        if not ext.startswith("."):
            ext = "." + ext
        allowed.add(ext)
    iterator = input_dir.rglob("*") if recursive else input_dir.glob("*")
    return sorted([p for p in iterator if p.is_file() and p.suffix.lower() in allowed])


def _identify_width(file_path, magick_path, bridge):
    exit_code, output = run_subprocess_streaming(magick_path, ["identify", "-format", "%w", str(file_path)], bridge)
    if exit_code != 0:
        raise RuntimeError(output.strip() or "No se pudo identificar el ancho")
    try:
        return int(output.strip())
    except ValueError:
        return None


def _build_output_path(cfg, input_file, input_dir, output_dir):
    try:
        relative_parent = input_file.parent.relative_to(input_dir)
    except ValueError:
        relative_parent = Path()
    output_parent = output_dir / relative_parent
    base_name = input_file.stem
    if cfg.resize_enabled and cfg.append_resize_tag:
        base_name = f"{base_name}-{cfg.resize_width}px"
    return output_parent / f"{base_name}.{cfg.output_extension}"


def _convert_single_image(*, input_file, output_file, cfg, bridge):
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if output_file.exists() and not cfg.overwrite_existing:
        return {"success": True, "skipped": True, "message": "Ya existe"}

    args = [str(input_file)]
    should_resize = False
    if cfg.resize_enabled:
        current_width = _identify_width(input_file, cfg.magick_path, bridge)
        if cfg.force_resize_all or (current_width and current_width > cfg.resize_width):
            should_resize = True

    args += ["-quality", str(cfg.quality)]
    if should_resize:
        args += ["-resize", str(cfg.resize_width)]
        if cfg.auto_sharpening:
            args += ["-unsharp", "0x0.75+0.75+0.008"]
    if cfg.strip_metadata:
        args += ["-strip"]
    args += [str(output_file)]

    exit_code, output = run_subprocess_streaming(cfg.magick_path, args, bridge)
    if bridge.cancel_token.is_cancelled():
        raise OperationCancelled()
    if exit_code != 0:
        raise RuntimeError(output.strip() or f"ImageMagick error {exit_code}")
    if not output_file.exists():
        raise RuntimeError("El archivo de salida no fue creado")

    original_size = input_file.stat().st_size / (1024 * 1024)
    new_size = output_file.stat().st_size / (1024 * 1024)
    reduction = round((1 - new_size / original_size) * 100, 1) if original_size > 0 else 0
    return {
        "success": True, "skipped": False,
        "output": str(output_file),
        "original_size_mb": round(original_size, 2),
        "new_size_mb": round(new_size, 2),
        "reduction": reduction,
        "resized": should_resize,
    }


def run_image_conversion(cfg: ImageConverterConfig, bridge: WorkerBridge) -> None:
    cfg.normalize()
    input_dir = Path(cfg.input_dir)
    output_dir = Path(cfg.output_dir)

    if not input_dir.exists() or not input_dir.is_dir():
        raise RuntimeError(f"Carpeta de entrada no existe: {input_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    bridge.log(f"Carpeta entrada : {input_dir}", "INFO")
    bridge.log(f"Carpeta salida  : {output_dir}", "INFO")
    bridge.log(f"Formato         : .{cfg.output_extension} · calidad {cfg.quality}", "INFO")

    exit_code, version_output = run_subprocess_streaming(cfg.magick_path, ["-version"], bridge)
    if exit_code != 0:
        raise RuntimeError("No se pudo ejecutar ImageMagick. ¿Está instalado?")
    first_line = version_output.splitlines()[0] if version_output else "ImageMagick detectado"
    bridge.log(f"✓ {first_line}", "SUCCESS")

    files = _get_image_files(input_dir, cfg.image_extensions, cfg.recursive)
    total = len(files)
    bridge.log(f"Imágenes encontradas: {total}", "SUCCESS")

    if total == 0:
        bridge.log("No hay imágenes con las extensiones configuradas.", "WARNING")
        bridge.done(True, "Sin archivos")
        return

    errors = []
    stats = {"ok": 0, "fail": 0, "skipped": 0, "resized": 0, "total_original_mb": 0.0, "total_new_mb": 0.0}
    start_time = datetime.now()

    for index, file_path in enumerate(files, start=1):
        bridge.cancel_token.check()
        output_file = _build_output_path(cfg, file_path, input_dir, output_dir)
        bridge.progress(index, total, file_path.name)

        try:
            result = _convert_single_image(input_file=file_path, output_file=output_file, cfg=cfg, bridge=bridge)
            if result.get("skipped"):
                stats["skipped"] += 1
                bridge.log(f"⊙ Omitido: {file_path.name}", "WARNING")
            else:
                stats["ok"] += 1
                if result.get("resized"):
                    stats["resized"] += 1
                stats["total_original_mb"] += result["original_size_mb"]
                stats["total_new_mb"] += result["new_size_mb"]
                bridge.log(
                    f"✓ {file_path.name} · {result['original_size_mb']} MB → {result['new_size_mb']} MB ({result['reduction']}%)",
                    "SUCCESS"
                )
        except OperationCancelled:
            raise
        except Exception as exc:
            stats["fail"] += 1
            errors.append({"archivo": str(file_path), "error": str(exc)})
            bridge.log(f"✗ {file_path.name} — {exc}", "ERROR")

        bridge.stats({
            "ok": stats["ok"], "fail": stats["fail"], "skipped": stats["skipped"],
            "total": total, "current": index,
            "saved_mb": round(stats["total_original_mb"] - stats["total_new_mb"], 2),
            "reduction_pct": round((1 - stats["total_new_mb"] / stats["total_original_mb"]) * 100, 1)
                if stats["total_original_mb"] > 0 else 0,
        })

    elapsed = str(datetime.now() - start_time).split(".")[0]
    bridge.log(f"Completado en {elapsed} · {stats['ok']} ok · {stats['fail']} errores · {stats['skipped']} omitidos", "SUCCESS")
    bridge.done(True, "Conversión finalizada")

    if cfg.open_output_when_done and output_dir.exists():
        try:
            if sys.platform == "win32":
                os.startfile(str(output_dir))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(output_dir)])
            else:
                subprocess.Popen(["xdg-open", str(output_dir)])
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# ESTADO GLOBAL
# ─────────────────────────────────────────────────────────────────────────────

_worker_bridge: Optional[WorkerBridge] = None
_worker_thread: Optional[threading.Thread] = None

CONFIG_PATH = Path(__file__).parent / CONFIG_FILENAME


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_config(data: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# FASTAPI APP
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Image Converter API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/config")
def get_config():
    return _load_config()


@app.post("/api/config")
def save_config(req: ConfigSaveRequest):
    _save_config(req.config)
    return {"ok": True}


@app.get("/api/formats")
def get_formats():
    return FORMAT_PRESETS


@app.post("/api/start")
def start_conversion(req: ConversionRequest):
    global _worker_bridge, _worker_thread

    if _worker_thread and _worker_thread.is_alive():
        return {"ok": False, "error": "Ya hay una conversión en curso"}

    cfg = ImageConverterConfig(
        input_dir=req.input_dir,
        output_dir=req.output_dir,
        magick_path=req.magick_path,
        output_format=req.output_format,
        quality=req.quality,
        resize_enabled=req.resize_enabled,
        resize_width=req.resize_width,
        force_resize_all=req.force_resize_all,
        append_resize_tag=req.append_resize_tag,
        recursive=req.recursive,
        overwrite_existing=req.overwrite_existing,
        strip_metadata=req.strip_metadata,
        auto_sharpening=req.auto_sharpening,
        image_extensions=req.image_extensions or list(DEFAULT_IMAGE_EXTENSIONS),
    )
    cfg.normalize()

    _worker_bridge = WorkerBridge()
    bridge = _worker_bridge

    def worker():
        try:
            run_image_conversion(cfg, bridge)
        except OperationCancelled:
            bridge.log("Operación cancelada por el usuario", "WARNING")
            bridge.done(False, "Cancelado")
        except Exception as exc:
            bridge.log(f"Error: {exc}", "ERROR")
            bridge.log(traceback.format_exc(), "DIM")
            bridge.done(False, str(exc))

    _worker_thread = threading.Thread(target=worker, daemon=True)
    _worker_thread.start()
    return {"ok": True}


@app.post("/api/stop")
def stop_conversion():
    global _worker_bridge
    if _worker_bridge:
        _worker_bridge.cancel_token.cancel()
        return {"ok": True}
    return {"ok": False, "error": "No hay conversión activa"}


@app.get("/api/status")
def get_status():
    global _worker_thread
    return {"running": bool(_worker_thread and _worker_thread.is_alive())}


@app.post("/api/shutdown")
def shutdown():
    os.kill(os.getpid(), signal.SIGTERM)
    return {"ok": True}


@app.get("/api/select-folder")
def select_folder():
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        folder_path = filedialog.askdirectory()
        root.destroy()
        return {"folder_path": folder_path}
    except Exception as e:
        return {"folder_path": "", "error": str(e)}


@app.get("/api/events")
async def event_stream(request: Request):
    """SSE endpoint — el frontend se conecta aquí para recibir el progreso en tiempo real."""
    global _worker_bridge

    async def generator():
        while True:
            if await request.is_disconnected():
                break

            bridge = _worker_bridge
            if bridge:
                for event_type, payload in bridge.drain():
                    data = json.dumps({"type": event_type, "payload": payload})
                    yield f"data: {data}\n\n"

            await asyncio.sleep(0.05)

    return StreamingResponse(generator(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  Image Converter — Backend local")
    print("  http://localhost:8000")
    print("  Abre frontend/index.html en tu navegador")
    print("=" * 55)
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
