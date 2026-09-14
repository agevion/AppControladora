"""Mantiene LibreHardwareMonitor vivo exactamente lo que viva el servidor.

Lo lanza la tarea `ControladoraSensores`, no lo llames tu. Corre ELEVADO, porque
LHM necesita privilegios para cargar el driver que lee la temperatura de la CPU
(ARQUITECTURA.md, apartado de la temperatura).

Por que hace falta este intermediario y no vale el Job Object de winjob.py, que es
como muere todo lo demas (Ollama, claude.exe, gradlew): **un proceso elevado no es
hijo nuestro**. `run.py` corre como usuario normal; quien crea de verdad el proceso
elevado es el Programador de tareas, asi que LHM nace fuera de nuestro job y el
kernel no se lo lleva cuando cerramos. No es que se nos olvidara meterlo: es que no
se puede meter.

Asi que lo que hace este supervisor es lo unico que se puede hacer desde fuera:
mira el PID del servidor y, en cuanto desaparece —da igual como: Ctrl+C, la X, un
taskkill, un pantallazo azul—, mata LHM. No es tan fuerte como el job (si a ESTE
proceso lo matan a la fuerza, LHM se queda), pero cubre el caso real: cerrar la
ventana del .bat.

Regla que copia de Ollama (run.py): **si LHM ya estaba abierto antes, no se toca al
salir.** No es nuestro. Solo se cierra lo que hemos abierto nosotros.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import psutil

SPOOL = Path(__file__).resolve().parent.parent / ".admin"
INFO = SPOOL / "sensores.json"

NOMBRE = "LibreHardwareMonitor"


def _proceso_lhm() -> psutil.Process | None:
    for p in psutil.process_iter(["name"]):
        if (p.info["name"] or "").lower() == f"{NOMBRE.lower()}.exe":
            return p
    return None


def main() -> int:
    try:
        info = json.loads(INFO.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 1

    exe = Path(str(info.get("lhm") or ""))
    pid_servidor = int(info.get("pid") or 0)
    if not exe.exists() or not pid_servidor:
        return 1

    # Engancharse al Process ANTES de nada: psutil guarda tambien su create_time,
    # asi que si el PID se reciclara para otro proceso distinto no lo confundiria
    # con nuestro servidor y no se quedaria vigilando a un desconocido para siempre.
    try:
        servidor = psutil.Process(pid_servidor)
    except psutil.NoSuchProcess:
        return 0

    ya_estaba = _proceso_lhm() is not None
    if not ya_estaba:
        subprocess.Popen([str(exe)], cwd=str(exe.parent))
        # Da igual si tarda en pintar la ventana: lo que nos importa es que abra
        # su servidor web, y sysinfo ya sabe esperar (devuelve None entre tanto).
        time.sleep(1)

    # Bloquea hasta que el servidor muera, sea como sea. psutil.wait() sobre un
    # proceso que no es hijo nuestro hace polling por dentro; no hay que montar
    # ningun bucle a mano.
    servidor.wait()

    if ya_estaba:
        # No lo abrimos nosotros: no es nuestro y no se toca. Mismo criterio que
        # run.py con un Ollama que ya estaba levantado.
        return 0

    lhm = _proceso_lhm()
    if lhm is not None:
        try:
            lhm.terminate()
            lhm.wait(timeout=5)
        except psutil.TimeoutExpired:
            lhm.kill()
        except psutil.NoSuchProcess:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
