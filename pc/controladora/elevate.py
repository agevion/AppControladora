"""Ejecutar un comando COMO ADMINISTRADOR sin que nadie tenga que estar delante.

El problema, tal cual: el UAC de Windows se pide en el escritorio del PC. Estando
en el gym no hay quien lo pulse, asi que cualquier cosa que necesite privilegios
(instalar un programa, tocar un servicio, HKLM) fallaba con "Access denied" y ahi
se acababa la conversacion. Un boton que no puede funcionar no vale para nada.

Como se resuelve: una **tarea programada** (`ControladoraAdmin`) registrada UNA vez
con "ejecutar con los privilegios mas altos". Windows lanza esas tareas ya
elevadas y **sin pedir UAC**, asi que un proceso normal puede dispararla con
`schtasks /run`. El proceso normal deja el comando en un fichero, dispara la
tarea, y el ayudante elevado lo ejecuta y deja la salida en otro fichero.

    servidor (usuario normal) --request.json--> [tarea elevada] --result.json--> servidor

QUE SE PIERDE CON ESTO, dicho claro (ARQUITECTURA.md seccion 9):

Esto crea un camino permanente para subir a administrador SIN UAC, y lo puede
usar cualquier cosa que ya corra como este usuario, no solo nosotros: basta con
escribir el fichero y disparar la tarea. Es una decision tomada a sabiendas
(2026-07-17) y el motivo por el que se puede defender es que **UAC no es una
frontera de seguridad** -- lo dice Microsoft, no nosotros: si algo malo ya corre
como tu, tiene decenas de formas de auto-elevarse igualmente. La frontera de este
proyecto no era UAC y sigue sin serlo: es mTLS + token + que TU leas el comando y
lo apruebes en el movil.

Lo que NO cambia:
- Lo normal sigue corriendo como usuario normal. Esto solo se usa con `admin=True`.
- Un comando admin SIEMPRE pasa por la tarjeta del movil, y sale en rojo diciendo
  que va como administrador. No hay admin silencioso.
- Un comando admin NO se puede congelar como tool con "Guardar" (ver server.py):
  una tool guardada no vuelve a preguntar, y "admin para siempre y sin tarjeta" es
  exactamente lo que no queremos.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
import uuid
from pathlib import Path

log = logging.getLogger("controladora.elevate")

PC_DIR = Path(__file__).resolve().parent.parent
SPOOL = PC_DIR / ".admin"
REQUEST = SPOOL / "request.json"
RESULT = SPOOL / "result.json"

TASK_NAME = "ControladoraAdmin"

# Margen que se le da al ayudante por encima del timeout del propio comando:
# arrancar la tarea y el python del ayudante no es instantaneo (~1-2s).
MARGEN = 30.0

# Una peticion cada vez: el spool es un unico par de ficheros con nombre fijo, asi
# que dos comandos a la vez se pisarian. Las tools corren en hilos (to_thread), de
# ahi que sea un Lock de verdad y no un flag.
_lock = threading.Lock()


class NoInstalado(Exception):
    """La tarea no existe todavia. Se distingue de un fallo del comando."""


def _sin_ventana() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def instalado() -> bool:
    """Si la tarea elevada esta registrada. No lanza: es una pregunta."""
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


def run(comando: str, timeout: float = 600, shell: str = "powershell") -> tuple[int, str, bool]:
    """Ejecuta `comando` elevado. Devuelve (codigo, salida, elevado_de_verdad).

    `elevado_de_verdad` lo dice el propio ayudante mirando su token, no nosotros
    suponiendolo: si la tarea se registrara mal y acabara corriendo sin
    privilegios, el comando fallaria por permisos y el motivo real (que no estaba
    elevado) quedaria invisible detras de un "Access denied" cualquiera.

    `shell` es "powershell" (por defecto) o "cmd": lo elige la ventana Terminal
    del movil. El ayudante elevado (scripts/admin_runner.py) es quien lo mira y
    escoge el ejecutable; aqui solo viaja dentro del request.
    """
    if not instalado():
        raise NoInstalado(
            "El ayudante de administrador no esta instalado. En el PC, una sola vez:\n"
            "  pc\\instalar_admin.bat  (pide UAC)\n"
            "Sin eso no se pueden ejecutar comandos como administrador."
        )

    with _lock:
        SPOOL.mkdir(exist_ok=True)
        rid = uuid.uuid4().hex

        # Se borra ANTES de pedir nada: si quedara el result de una llamada
        # anterior, el bucle de abajo podria leerlo y darlo por bueno.
        RESULT.unlink(missing_ok=True)
        REQUEST.write_text(
            json.dumps({"id": rid, "comando": comando, "timeout": timeout, "shell": shell}),
            encoding="utf-8",
        )

        log.info("admin: disparando tarea para %s", comando[:80])
        disparo = subprocess.run(
            ["schtasks", "/run", "/tn", TASK_NAME],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=_sin_ventana(),
        )
        if disparo.returncode != 0:
            return (
                1,
                f"No se pudo lanzar el ayudante de administrador: {disparo.stderr.strip() or disparo.stdout.strip()}",
                False,
            )

        limite = time.monotonic() + timeout + MARGEN
        while time.monotonic() < limite:
            if RESULT.exists():
                try:
                    data = json.loads(RESULT.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    # El ayudante escribe con rename atomico, asi que esto no
                    # deberia pasar; si pasa, se reintenta en la vuelta siguiente.
                    time.sleep(0.2)
                    continue
                if data.get("id") == rid:
                    RESULT.unlink(missing_ok=True)
                    return int(data.get("code", 1)), str(data.get("salida", "")), bool(data.get("elevado"))
            time.sleep(0.3)

        return (124, f"TIMEOUT: el ayudante de administrador no contesto en {timeout + MARGEN:.0f}s", False)
