@echo off
REM Arranca la Controladora entera: Tailscale, Ollama, tools y servidor.
REM Doble clic, o desde cualquier sitio: E:\AppControladora\pc\arrancar.bat
REM
REM Existe porque el PATH de este PC no tiene python: hay que usar si o si el
REM del entorno virtual, por ruta absoluta. Ver ARQUITECTURA.md seccion 2.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo No existe el entorno virtual en pc\.venv
    echo Crealo con:
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

.venv\Scripts\python.exe run.py

REM Si algo falla al arrancar, la ventana no debe cerrarse antes de que leas por que.
if errorlevel 1 (
    echo.
    echo -- El servidor termino con error %errorlevel% --
    pause
)
