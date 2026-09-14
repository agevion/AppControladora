"""Helpers compartidos por las tools.

Empieza por "_" a proposito: el registry ignora estos ficheros, no es una tool.
"""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from controladora import progress

# Lo que devuelve una tool lo lee un modelo de 8B con ventana limitada. Un log de
# Gradle son miles de lineas y casi todas son ruido: lo que importa esta al final.
MAX_LINES = 40


def tail(text: str, max_lines: int = MAX_LINES) -> str:
    lines = text.strip().splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)
    hidden = len(lines) - max_lines
    return f"[... {hidden} lineas omitidas ...]\n" + "\n".join(lines[-max_lines:])


def run_process(
    cmd: list[str],
    cwd: str | Path | None = None,
    timeout: float = 600,
    extra_env: dict[str, str] | None = None,
    stream_progress: bool = False,
) -> tuple[int, str]:
    """Ejecuta y espera. Devuelve (codigo, salida combinada).

    Sincrono a proposito: el registry ya lo llama desde un hilo aparte. Un build
    de Gradle tarda minutos y eso es normal, no un cuelgue.

    `stream_progress=True`: ademas de devolver la salida completa al final (como
    siempre), manda cada linea a `progress.report()` segun se produce -- para que
    el movil vea algo mientras el comando corre, no silencio total hasta el
    final. Activarlo es gratis: si nadie esta escuchando ahora mismo (la tool se
    ejecuta fuera de una conversacion), esas llamadas no hacen nada.

    stdout y stderr se combinan EN ORDEN CRONOLOGICO (antes se pegaba primero
    todo stdout y luego todo stderr, que no es el orden real en que salio).

    Se lee con un hilo lector + cola en vez de `subprocess.run(..., timeout=)`
    a proposito: asi el timeout se cumple de verdad aunque el proceso este
    colgado SIN producir ninguna linea de salida, que es justo el caso en que
    mas hace falta poder cortarlo.
    """
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except FileNotFoundError:
        return 127, f"No existe el ejecutable: {cmd[0]}"

    lineas: list[str] = []
    cola: queue.Queue[str | None] = queue.Queue()

    def _leer() -> None:
        assert proc.stdout is not None
        for linea in proc.stdout:
            cola.put(linea)
        cola.put(None)  # EOF

    hilo = threading.Thread(target=_leer, daemon=True)
    hilo.start()

    limite = time.monotonic() + timeout
    while True:
        restante = limite - time.monotonic()
        if restante <= 0:
            proc.kill()
            proc.wait()
            salida = "".join(lineas)
            extra = f"\n\n(iban {len(lineas)} lineas de salida cuando se corto)" if lineas else ""
            return 124, f"TIMEOUT: el comando no termino en {timeout:.0f}s{extra}\n\n{salida}"
        try:
            item = cola.get(timeout=min(restante, 1.0))
        except queue.Empty:
            continue
        if item is None:
            break
        lineas.append(item)
        if stream_progress:
            progress.report(item.rstrip("\n"))

    codigo = proc.wait()
    return codigo, "".join(lineas)


def spawn_detached(cmd: list[str], cwd: str | Path | None = None) -> None:
    """Lanza y se desentiende. Para abrir GUIs (IDEs): no queremos esperarlas."""
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        creationflags=creationflags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
