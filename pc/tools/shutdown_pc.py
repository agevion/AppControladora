"""Apaga el PC. CONFIRM = True: pide Permitir/Denegar en el movil antes de nada.

Da un margen antes de apagar de verdad (por defecto 15s), y `cancel_shutdown`
sirve para arrepentirse dentro de ese margen.
"""

from __future__ import annotations

import subprocess

SPEC = {
    "name": "shutdown_pc",
    "description": (
        "Apaga el ordenador por completo. Pide confirmacion en el movil antes de ejecutarse."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "segundos": {
                "type": "integer",
                "description": "Margen antes de apagar de verdad, para poder cancelar con cancel_shutdown. 15 por defecto.",
            },
        },
        "required": [],
    },
}

CONFIRM = True


def run(segundos: int = 15) -> str:
    subprocess.run(
        ["shutdown", "/s", "/t", str(segundos), "/c", "AppControladora: apagado pedido desde el movil"],
        timeout=10,
    )
    return f"Apagando en {segundos}s. Para cancelar ahora mismo: cancel_shutdown."
