@echo off
REM Registra el ayudante que ejecuta comandos como administrador. UNA sola vez.
REM
REM Doble clic aqui: pide UAC (este es el ultimo UAC que veras) y deja registrada
REM la tarea `ControladoraAdmin`. A partir de ahi, cuando desde el movil pidas algo
REM que necesite privilegios, te sale una tarjeta ROJA y se ejecuta al aprobarla,
REM sin que nadie tenga que estar delante del PC.
REM
REM Lee ARQUITECTURA.md seccion 9: esto crea a proposito un camino a administrador
REM sin UAC. Para deshacerlo, como administrador:
REM     schtasks /delete /tn ControladoraAdmin /f

cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 (
    echo Pidiendo permisos de administrador...
    REM Se relanza este mismo .bat elevado. El "cd /d" de arriba se repite dentro,
    REM porque un proceso elevado arranca en system32, no aqui.
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b 0
)

.venv\Scripts\python.exe scripts\setup_admin.py

echo.
pause
