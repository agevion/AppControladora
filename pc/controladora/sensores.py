"""Levanta LibreHardwareMonitor junto con el servidor, y que muera con el.

Es el equivalente de `ollama.ensure_up()` para los sensores: lo llama `run.py` al
arrancar, avisa en vez de bloquear, y si LHM ya estaba abierto lo detecta y no lo
toca (ni al arrancar ni al salir).

La diferencia con Ollama es que esto necesita privilegios de administrador —el
driver que lee la temperatura de la CPU no carga sin ellos— y `run.py` corre como
usuario normal. De ahi el rodeo: se dispara la tarea `ControladoraSensores`, que
lanza `scripts/sensor_supervisor.py` ya elevado, y es ese supervisor el que abre
LHM y lo mata cuando este proceso muere. El porque de no usar el Job Object de
winjob.py (que es como muere todo lo demas) esta explicado en el supervisor: un
proceso elevado no es hijo nuestro y no hereda el job.

Sin la tarea instalada esto no rompe nada: avisa, y lo unico que pasa es que el
Monitor enseña la nota de "temperatura no disponible" en vez del numero.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from . import paths

log = logging.getLogger("controladora.sensores")

PC_DIR = Path(__file__).resolve().parent.parent
SPOOL = PC_DIR / ".admin"
INFO = SPOOL / "sensores.json"

TASK_NAME = "ControladoraSensores"


def _sin_ventana() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def instalado() -> bool:
    try:
        proc = subprocess.run(
            ["schtasks", "/query", "/tn", TASK_NAME],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=_sin_ventana(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def ensure_up() -> str:
    """Deja LHM corriendo y atado a la vida de ESTE proceso. Nunca lanza."""
    cfg = paths.sensores()
    exe = cfg.get("lhm_exe")

    if not exe:
        return "sensores: sin 'lhm_exe' en paths.json -> el Monitor no podra dar temperatura de CPU"
    if not Path(exe).exists():
        return f"sensores: no existe {exe} -> sin temperatura de CPU (revisa paths.json)"
    if not instalado():
        return (
            "sensores: falta la tarea ControladoraSensores -> sin temperatura de CPU.\n"
            "  Arreglalo una vez con: pc\\instalar_admin.bat"
        )

    try:
        SPOOL.mkdir(exist_ok=True)
        # El PID va aqui y no como argumento de la tarea porque `schtasks /run` no
        # sabe pasar parametros: la tarea esta registrada con una linea de comandos
        # fija, asi que lo variable viaja por fichero (igual que en elevate.py).
        INFO.write_text(json.dumps({"pid": os.getpid(), "lhm": exe}), encoding="utf-8")
        proc = subprocess.run(
            ["schtasks", "/run", "/tn", TASK_NAME],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=_sin_ventana(),
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"sensores: no se pudo lanzar el supervisor ({type(e).__name__}: {e}) -> sin temperatura de CPU"

    if proc.returncode != 0:
        return f"sensores: la tarea no arranco ({(proc.stderr or proc.stdout).strip()[:80]}) -> sin temperatura de CPU"

    return "sensores: LibreHardwareMonitor arriba (temperatura de CPU disponible; se cierra con esta ventana)"
