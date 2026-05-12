@echo off
:: Abre el archivo HTML en el navegador predeterminado
start "" "frontend\index.html"

:: Cambia al directorio del backend y arranca el servidor
cd backend
python main.py
