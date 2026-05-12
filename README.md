# Image Converter

Una solución de escritorio elegante y potente para la conversión, redimensionamiento y optimización masiva de imágenes. Esta versión utiliza una interfaz web moderna (Vue 3) conectada a un backend local (FastAPI), manteniendo la potencia de **ImageMagick** como motor de procesamiento.

![Versión](https://img.shields.io/badge/version-2.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.8+-green.svg)
![ImageMagick](https://img.shields.io/badge/engine-ImageMagick-orange.svg)
![Interfaz](https://img.shields.io/badge/UI-Vue%203-green.svg)

---

## 🎨 Identidad Visual

<p align="center">
  <img src="frontend/icon.png" width="160" alt="PDF Tool Icon">
</p>

---

## 📁 Estructura del Proyecto

```
Image Converter 2.0/
├── backend/
│   └── main.py          ← Servidor FastAPI
├── frontend/
│   └── index.html       ← Interfaz de usuario (Vue 3)
├── start.bat            ← Script de inicio rápido
└── ImageMagick-...exe   ← Instalador de ImageMagick (opcional)
```

---

## ✨ Características Principales

*   **🔄 Conversión Multi-formato**: Soporte avanzado para **WEBP, AVIF, JPG y PNG**.
*   **📂 Estructura Inteligente**: Procesa carpetas de forma recursiva manteniendo la jerarquía de subdirectorios.
*   **📏 Redimensionamiento Adaptativo**: Define un ancho máximo y elige si deseas forzar el tamaño o solo reducir las más grandes.
*   **⚡ Optimización de Peso**: Algoritmos de compresión configurables para equilibrar calidad y tamaño de archivo.
*   **🛠️ Control Total**: Opción para eliminar metadatos (strip) para mayor privacidad y ligereza, y auto-nitidez (sharpening) tras redimensionar.
*   **📊 Análisis en Tiempo Real**: Visualiza el progreso y estadísticas detalladas transmitidas en tiempo real via Server-Sent Events (SSE).

---

## 📋 Requisitos del Sistema

### 1. Python 3.8 o superior
Asegúrate de tener Python instalado. Durante la instalación en Windows, marca la casilla **"Add Python to PATH"**.

Instala las dependencias necesarias:
```bash
pip install fastapi uvicorn
```

### 2. ImageMagick (El Motor)
Esta aplicación utiliza ImageMagick para el procesamiento pesado de imágenes.
1. Puedes usar el instalador incluido en la raíz del proyecto (`ImageMagick-7.1.2-7-Q16-HDRI-x64-dll.exe`).
2. **IMPORTANTE**: Durante la instalación, asegúrate de marcar la opción **"Install legacy utilities (e.g. convert)"** y **"Add application directory to your system path"**.
3. Si prefieres no instalarlo en el sistema o ya lo tienes en otra ruta, puedes configurar la ruta del ejecutable `magick.exe` en la aplicación.

---

## 🚀 Cómo Usar

### Opción A: Inicio Rápido (Recomendado)
Simplemente haz doble clic en el archivo **`start.bat`**. Esto hará dos cosas:
1. Abrirá la interfaz web (`frontend/index.html`) en tu navegador predeterminado.
2. Iniciará el servidor backend de Python.

### Opción B: Inicio Manual
Si prefieres iniciarlo manualmente:
1. Abre una terminal en la carpeta `backend` y ejecuta:
   ```bash
   python main.py
   ```
2. Abre el archivo `frontend/index.html` directamente en tu navegador (no necesita servidor web para la interfaz, se conecta al backend local).

---

## 🔌 API Endpoints

El backend expone una API en `http://localhost:8000`:

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/config` | Carga la configuración guardada |
| POST | `/api/config` | Guarda la configuración |
| POST | `/api/start` | Inicia la conversión |
| POST | `/api/stop` | Detiene la conversión |
| GET | `/api/events` | Stream SSE de progreso en tiempo real |
| GET | `/api/status` | Estado actual del worker |
| POST | `/api/shutdown` | Apaga el servidor backend |
| GET | `/api/select-folder` | Abre diálogo para seleccionar carpeta |

---

## 📝 Notas
- La configuración se guarda automáticamente en `backend/image_converter_config.json`.
- El diálogo de selección de carpetas utiliza una ventana nativa (Tkinter) que se abrirá sobre tu navegador cuando hagas clic en seleccionar carpeta.

---
*Desarrollado por **gwalls86***
