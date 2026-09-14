"""Captura la pantalla del PC.

Fase 1: guarda el PNG y devuelve la ruta. Todavia no viaja al movil; eso llega
con el video (Fase 4). De momento sirve para que Claude Code pueda mirarla.
"""

from __future__ import annotations

import time
from pathlib import Path

from PIL import ImageGrab

ARTIFACTS = Path(__file__).resolve().parent.parent / "artifacts"

SPEC = {
    "name": "screenshot",
    "description": (
        "Hace una captura de la pantalla del PC y la guarda como PNG. Devuelve la ruta "
        "del fichero. Util para ver que esta pasando en el escritorio."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

CONFIRM = False


def run() -> str:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    destino = ARTIFACTS / f"screen_{time.strftime('%Y%m%d_%H%M%S')}.png"

    try:
        # all_screens: el PC tiene varios monitores (incluidos los virtuales del visor).
        img = ImageGrab.grab(all_screens=True)
    except Exception as e:
        return f"No pude capturar la pantalla: {type(e).__name__}: {e}"

    img.save(destino)
    return f"Captura guardada: {destino} ({img.width}x{img.height})"
