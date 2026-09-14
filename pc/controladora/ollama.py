"""Se asegura de que Ollama este sirviendo antes de arrancar el servidor.

Hermano de tailscale.py, y con la misma regla: **nunca impide arrancar**. Si
Ollama no esta, el chat de Claude Code funciona igual y el de la IA local dara un
error claro cuando lo uses ("Ollama no responde en..."). Un aviso al arrancar es
mas util que un servidor que se niega a existir.

Que esto no cuesta nada tenerlo levantado siempre esta medido en ARQUITECTURA.md
seccion 7: `ollama serve` en reposo son unos cientos de MB de RAM y **0 VRAM**.
El modelo solo ocupa VRAM mientras responde, y se descarga solo pasado keep_alive.

Se lanza DESACOPLADO de la consola (para que no se le cierre encima si esta
ventana se cierra), pero NO independiente del proceso: `run.py` mete su propio
proceso en un Job de Windows (`winjob.py`) antes de llegar aqui, y ese job se
hereda automaticamente por todo lo que se lance despues. Si `run.py` muere --
por Ctrl+C, por la X, por un crash-- Ollama muere con el. Sin rastro.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import paths


def _tags(url: str, timeout: float) -> dict | None:
    """Que modelos tiene Ollama instalados. None = no responde."""
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None


def _instalados(tags: dict) -> list[str]:
    return [m.get("name", "") for m in (tags.get("models") or [])]


def _find_exe(cfg: dict) -> str | None:
    ruta = cfg.get("exe")
    if ruta and Path(ruta).exists():
        return ruta
    return shutil.which("ollama")


def _falta_modelo(tags: dict, modelo: str) -> str | None:
    """Aviso si el modelo configurado no esta descargado, o None si esta."""
    if modelo in _instalados(tags):
        return None
    return (
        f"ollama: sirviendo, pero NO tiene el modelo '{modelo}'. "
        f"Descargalo con:  ollama pull {modelo}"
    )


def ensure_up(timeout: float = 25.0) -> tuple[str, int | None]:
    """Devuelve (mensaje, pid). `pid` es el de Ollama SOLO si lo hemos lanzado
    nosotros ahora mismo -- es lo que `run.py` usa para protegerlo ademas de
    con `protect_self()` (ver winjob.py), por si esa protecion fallara. Si ya
    estaba sirviendo (lo lanzo otra cosa, ej. el icono de bandeja de Windows),
    `pid` es None: no es nuestro y no lo tocamos ni al arrancar ni al morir.
    """
    cfg = paths.ollama()
    url = cfg.get("url", "http://127.0.0.1:11434")
    modelo = cfg.get("model", "qwen3:8b")

    # Puede estar ya sirviendo: Ollama se instala con un icono de bandeja que
    # arranca solo con Windows. Si ya responde, no hay nada que hacer.
    tags = _tags(url, timeout=2)
    if tags is not None:
        msg = _falta_modelo(tags, modelo) or f"ollama: ya estaba sirviendo (modelo {modelo} listo)"
        return msg, None

    exe = _find_exe(cfg)
    if not exe:
        return (
            "ollama: no encontrado. Revisa la ruta en paths.json (ollama.exe) o instalalo. "
            "El chat de la IA local no funcionara; el de Claude Code si."
        ), None

    try:
        proc = subprocess.Popen(
            [exe, "serve"],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        return f"ollama: fallo al arrancar ({type(e).__name__}: {e})", None

    # Tarda un par de segundos en abrir el puerto. Se pregunta, no se duerme a ciegas.
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        tags = _tags(url, timeout=2)
        if tags is not None:
            msg = _falta_modelo(tags, modelo) or f"ollama: arrancado (modelo {modelo} listo)"
            return msg, proc.pid
        time.sleep(0.5)

    # Sigue vivo (no ha fallado), solo tarda: lo devolvemos igual para que se proteja.
    return f"ollama: se lanzo pero no responde en {url} tras {timeout:.0f}s", proc.pid
