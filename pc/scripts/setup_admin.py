"""Registra la tarea `ControladoraAdmin`. UNA vez, y hay que ser administrador.

    pc\\instalar_admin.bat        (pide UAC y llama aqui)

Que hace: crea una tarea programada SIN disparador (no se ejecuta sola nunca) que
lanza `scripts/admin_runner.py` con los privilegios mas altos. A partir de ahi el
servidor, corriendo como usuario normal, puede pedirle a esa tarea que ejecute un
comando elevado sin que salte ningun UAC -- que es justo lo que hace falta cuando
el que da la orden esta en el gym y no hay nadie delante del PC.

Lee ARQUITECTURA.md seccion 9 antes de tocar esto: crea a proposito un camino a
administrador sin UAC, y ese es el precio que se acepto para que "instalame esto"
funcione de verdad desde el movil.

Para deshacerlo:  schtasks /delete /tn ControladoraAdmin /f   (como administrador)
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path

PC_DIR = Path(__file__).resolve().parent.parent
RUNNER = PC_DIR / "scripts" / "admin_runner.py"
SUPERVISOR = PC_DIR / "scripts" / "sensor_supervisor.py"
PYTHON = PC_DIR / ".venv" / "Scripts" / "pythonw.exe"

TASK_NAME = "ControladoraAdmin"
TASK_SENSORES = "ControladoraSensores"

# La tarea que arrancaba LibreHardwareMonitor al iniciar sesion. Fue un error:
# dejaba LHM corriendo por su cuenta, con o sin servidor, en contra del "sin
# rastro al cerrar" de ARQUITECTURA.md seccion 5.0. Ahora lo levanta y lo mata
# run.py (ver controladora/sensores.py), asi que esta sobra y se borra.
TASK_VIEJA_LHM = "LibreHardwareMonitor (sensores para Controladora)"


def _es_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def main() -> int:
    if not _es_admin():
        print("ERROR: esto hay que ejecutarlo como ADMINISTRADOR.")
        print("Usa pc\\instalar_admin.bat, que pide el UAC por ti.")
        return 1

    # pythonw y no python: el ayudante no tiene consola que enseñar, y con
    # python.exe cada comando administrativo haria parpadear una ventana negra.
    interprete = PYTHON if PYTHON.exists() else PC_DIR / ".venv" / "Scripts" / "python.exe"
    if not interprete.exists():
        print(f"ERROR: no encuentro el python del entorno virtual en {interprete}")
        return 1

    # Register-ScheduledTask y no `schtasks /create`: para crear la tarea a nombre
    # del usuario con LogonType Interactive no hace falta su contraseña, y con
    # schtasks /ru si la pediria.
    #
    # Ninguna de las dos tareas lleva disparador: no se ejecutan solas nunca, solo
    # cuando el servidor las dispara con `schtasks /run`.
    ps = f"""
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\\$env:USERNAME" -RunLevel Highest -LogonType Interactive
$opciones = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0 -MultipleInstances IgnoreNew

$accion = New-ScheduledTaskAction -Execute '{interprete}' -Argument '"{RUNNER}"' -WorkingDirectory '{PC_DIR}'
Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $accion -Principal $principal -Settings $opciones -Description 'Ayudante de AppControladora: ejecuta comandos como administrador que ya has aprobado desde el movil. No se ejecuta solo: solo cuando el servidor lo dispara.' -Force | Out-Null

$accionSens = New-ScheduledTaskAction -Execute '{interprete}' -Argument '"{SUPERVISOR}"' -WorkingDirectory '{PC_DIR}'
Register-ScheduledTask -TaskName '{TASK_SENSORES}' -Action $accionSens -Principal $principal -Settings $opciones -Description 'Abre LibreHardwareMonitor (temperatura de CPU) cuando arranca la Controladora y lo cierra cuando esta se cierra.' -Force | Out-Null

# La de inicio de sesion sobra: LHM ya no vive por su cuenta, vive con arrancar.bat.
Unregister-ScheduledTask -TaskName '{TASK_VIEJA_LHM}' -Confirm:$false -ErrorAction SilentlyContinue

Write-Output 'OK'
"""
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0 or "OK" not in proc.stdout:
        print("ERROR al registrar la tarea:")
        print(proc.stdout, proc.stderr)
        return 1

    (PC_DIR / ".admin").mkdir(exist_ok=True)

    print("Listo. Dos tareas registradas, ninguna se ejecuta sola:")
    print(f"  {TASK_NAME:22} -> comandos como administrador que apruebas en el movil")
    print(f"  {TASK_SENSORES:22} -> LibreHardwareMonitor (temperatura de CPU)")
    print(f"  interprete: {interprete}")
    print()
    print("La tarea vieja que abria LibreHardwareMonitor al iniciar sesion se ha quitado:")
    print("ahora se abre con arrancar.bat y se cierra con el, como Ollama.")
    print()
    print("Ya puedes pedir desde el movil cosas que necesiten administrador.")
    print("Cada una sale en una tarjeta ROJA que hay que aprobar.")
    print()
    print("Para quitarlo todo (como administrador):")
    print(f"  schtasks /delete /tn {TASK_NAME} /f")
    print(f"  schtasks /delete /tn {TASK_SENSORES} /f")
    return 0


if __name__ == "__main__":
    sys.exit(main())
