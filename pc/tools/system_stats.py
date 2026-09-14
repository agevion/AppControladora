"""Estado del PC ahora mismo: CPU, RAM, GPU y discos.

Aqui no hay logica: medir es cosa de `controladora/sysinfo.py`, que sirve a la
vez a esta tool (texto para el modelo) y a la pantalla de Monitor del movil
(datos para dibujar barras). Si se midiera en cada sitio por separado, el chat y
el monitor acabarian diciendo cosas distintas del mismo PC.
"""

from __future__ import annotations

from controladora import sysinfo

SPEC = {
    "name": "system_stats",
    "description": (
        "Estado del PC ahora mismo: uso de CPU, RAM, GPU (carga, VRAM, temperatura) y "
        "espacio en disco. Usalo si preguntan como va de carga, de temperatura o de espacio."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

CONFIRM = False


def run() -> str:
    return sysinfo.to_text()
