@echo off
echo ===================================================
echo   Subiendo Image Converter a GitHub (Forzado)
echo ===================================================

:: Verificar si es un repositorio git
if not exist .git (
    echo Inicializando repositorio Git...
    git init
)

:: Intentar añadir el remoto
git remote add origin https://github.com/gwalls86/image-converter 2>nul
if %errorlevel% neq 0 (
    echo El remoto ya existe, actualizando URL...
    git remote set-url origin https://github.com/gwalls86/image-converter
)

echo Añadiendo archivos...
git add .

echo Creando commit...
git commit -m "Initial commit - Web UI version"

echo Renombrando rama local a main...
git branch -M main

echo Subiendo a GitHub (Forzado)...
git push -u origin main --force

echo.
echo Proceso finalizado. Verifica si se subió correctamente.
pause
