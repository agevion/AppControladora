"""Abre en el PC la carpeta donde aterrizan los ficheros que manda el movil."""

from __future__ import annotations

import os
from pathlib import Path

from _util import spawn_detached
from controladora import recibidos

SPEC = {
    "name": "abrir_recibidos",
    "description": (
        "Abre en el Explorador de Windows la carpeta donde se guardan los ficheros "
        "que se mandan desde el movil (Documentos/ControlaPics por defecto). Util "
        "para ver de golpe lo que se acaba de traspasar."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

CONFIRM = False


def run() -> str:
    carpeta = recibidos.carpeta()
    ficheros = [f for f in carpeta.iterdir() if f.is_file() and f.suffix != ".parte"]
    # Por ruta absoluta y no "explorer.exe" a secas: la regla de este proyecto es
    # no depender NUNCA del PATH (ver paths.py). Y explorer y no os.startfile,
    # porque startfile bloquearia si el shell tarda, y esto lo llama el registry
    # desde un hilo que preferimos devolver ya.
    explorer = Path(os.environ.get("WINDIR", "C:/Windows")) / "explorer.exe"
    spawn_detached([str(explorer), str(carpeta)])
    return f"Abierta {carpeta} ({len(ficheros)} ficheros dentro)."
