"""Cancela un apagado/reinicio que todavia este en su margen de gracia.

CONFIRM = False: cancelar es siempre la accion segura (si no habia nada
programado, no hace nada). El riesgo de verdad esta en reboot_pc/shutdown_pc,
no aqui.
"""

from __future__ import annotations

import subprocess

SPEC = {
    "name": "cancel_shutdown",
    "description": (
        "Cancela un apagado o reinicio pendiente, dentro del margen de segundos que dio "
        "reboot_pc o shutdown_pc. Si no habia nada programado, no hace nada."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

CONFIRM = False


def run() -> str:
    proc = subprocess.run(["shutdown", "/a"], capture_output=True, text=True, timeout=10)
    if proc.returncode == 0:
        return "Apagado/reinicio cancelado."
    detalle = (proc.stderr or proc.stdout).strip()
    return f"No habia nada que cancelar (o fallo): {detalle}"
