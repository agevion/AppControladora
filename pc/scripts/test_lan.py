"""Prueba de conexion contra la IP de LAN (no localhost), para descartar que el
problema sea especifico de esa interfaz.

    python scripts/test_lan.py
"""

from __future__ import annotations

import asyncio
import json
import os
import ssl
from pathlib import Path

from websockets.asyncio.client import connect

PC_DIR = Path(__file__).resolve().parent.parent
CERTS = PC_DIR / "certs"
CONFIG = json.loads((PC_DIR / "config.json").read_text(encoding="utf-8"))

# La IP real no vive en el repo: sale del entorno o de config.json.
HOST = os.environ.get("CONTROLADORA_HOST") or CONFIG.get("lan_host")
if not HOST:
    raise SystemExit(
        'Falta la IP LAN del PC: exporta CONTROLADORA_HOST=192.168.1.X o anade\n'
        '"lan_host" a config.json.'
    )
URI = f"wss://{HOST}:{CONFIG['port']}/ws"


async def main() -> None:
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(CERTS / "ca.crt"))
    ctx.load_cert_chain(str(CERTS / "client.crt"), str(CERTS / "client.key"))

    print(f"conectando a {URI} ...")
    async with connect(URI, ssl=ctx, additional_headers={"Authorization": f"Bearer {CONFIG['token']}"}) as ws:
        print("CONECTADO:", await ws.recv())


if __name__ == "__main__":
    asyncio.run(main())
