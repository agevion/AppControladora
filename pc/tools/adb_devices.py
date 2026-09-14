"""Lista los dispositivos Android visibles por adb."""

from __future__ import annotations

from _util import run_process
from controladora import paths

SPEC = {
    "name": "adb_devices",
    "description": "Lista los dispositivos Android conectados al PC (por USB o inalambricos).",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

CONFIRM = False


def run() -> str:
    adb = paths.binary("adb")
    if not adb:
        return "adb no configurado en paths.json (bin.adb)"

    code, out = run_process([adb, "devices", "-l"], timeout=30)
    if code != 0:
        return f"adb devices fallo (codigo {code}):\n{out}"

    lineas = [l for l in out.strip().splitlines()[1:] if l.strip()]
    if not lineas:
        return "No hay ningun dispositivo conectado."
    return "Dispositivos:\n" + "\n".join(lineas)
