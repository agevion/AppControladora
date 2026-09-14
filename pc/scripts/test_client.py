"""Prueba del transporte (Fase 0). Simula lo que hace la app Android.

    python scripts/test_client.py

Comprueba las tres cosas que importan del transporte:
  1. Con cert de cliente + token correcto  -> entra y recibe el hello
  2. Sin cert de cliente                   -> el handshake TLS ni empieza
  3. Con cert pero token incorrecto        -> rechazado en el handshake HTTP

Para probar la IA local y las tools, usa test_fase1.py.
"""

from __future__ import annotations

import asyncio
import json
import ssl
import sys
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus, WebSocketException

PC_DIR = Path(__file__).resolve().parent.parent
CERTS = PC_DIR / "certs"
CONFIG = json.loads((PC_DIR / "config.json").read_text(encoding="utf-8"))

URI = f"wss://localhost:{CONFIG['port']}/ws"
TOKEN = CONFIG["token"]


def _ctx(with_client_cert: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(CERTS / "ca.crt"))
    if with_client_cert:
        ctx.load_cert_chain(str(CERTS / "client.crt"), str(CERTS / "client.key"))
    return ctx


async def test_happy() -> bool:
    print("1) cert valido + token valido")
    try:
        async with connect(URI, ssl=_ctx(True), additional_headers={"Authorization": f"Bearer {TOKEN}"}) as ws:
            hello = json.loads(await ws.recv())
            if hello.get("type") != "hello":
                print(f"   MAL: esperaba un hello, llego {hello}")
                return False
            print(f"   hello v{hello['version']}  brains={hello['brains']}  tools={len(hello.get('tools', []))}")
            print("   OK")
            return True
    except Exception as e:
        print(f"   MAL: {type(e).__name__}: {e}")
        return False


async def test_no_cert() -> bool:
    print("2) sin cert de cliente (debe rechazar)")
    try:
        async with connect(URI, ssl=_ctx(False), additional_headers={"Authorization": f"Bearer {TOKEN}"}):
            print("   MAL: ha entrado sin certificado")
            return False
    # Segun la version de OpenSSL, el rechazo llega como alerta TLS o como un
    # cierre en seco (EOFError). Las dos cosas son un "no".
    except (ssl.SSLError, WebSocketException, OSError, EOFError) as e:
        print(f"   OK: rechazado en TLS ({type(e).__name__})")
        return True


async def test_bad_token() -> bool:
    print("3) cert valido + token invalido (debe rechazar)")
    try:
        async with connect(URI, ssl=_ctx(True), additional_headers={"Authorization": "Bearer chungo"}) as ws:
            await ws.recv()
            print("   MAL: ha entrado con token invalido")
            return False
    except InvalidStatus as e:
        print(f"   OK: rechazado en el handshake HTTP ({e.response.status_code})")
        return True
    except WebSocketException as e:
        print(f"   OK: cerrado ({type(e).__name__})")
        return True


async def main() -> int:
    results = [await test_happy(), await test_no_cert(), await test_bad_token()]
    print()
    if all(results):
        print("Transporte: las 3 pruebas pasan")
        return 0
    print(f"FALLAN {results.count(False)} de 3")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
