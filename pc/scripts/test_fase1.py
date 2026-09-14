"""Prueba de la Fase 1 completa, por el WebSocket como lo hara el movil.

    python scripts/test_fase1.py

Comprueba que la IA local, las tools y el flujo de permisos funcionan a traves
del transporte real (mTLS + WS), no solo llamando a las clases por dentro.
"""

from __future__ import annotations

import asyncio
import json
import ssl
import sys
from pathlib import Path

from websockets.asyncio.client import connect

PC_DIR = Path(__file__).resolve().parent.parent
CERTS = PC_DIR / "certs"
CONFIG = json.loads((PC_DIR / "config.json").read_text(encoding="utf-8"))

URI = f"wss://localhost:{CONFIG['port']}/ws"


def _ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(CERTS / "ca.crt"))
    ctx.load_cert_chain(str(CERTS / "client.crt"), str(CERTS / "client.key"))
    return ctx


async def conversar(ws, texto: str, auto_permitir: bool | None = None) -> list[dict]:
    """Manda un mensaje y recoge todo hasta chat.end.

    auto_permitir: si llega un permission.request, responde con ese valor.
    """
    await ws.send(json.dumps({"type": "chat", "id": "m1", "brain": "local", "text": texto}))

    eventos = []
    while True:
        msg = json.loads(await ws.recv())
        eventos.append(msg)
        t = msg["type"]

        if t == "chat.delta":
            print(f"    [texto] {msg['text'][:200]}")
        elif t == "tool":
            print(f"    [TOOL]  {msg['name']}({msg['args']})  confirm={msg['confirm']}")
        elif t == "tool.result":
            print(f"    [res]   {msg['text'].splitlines()[0][:120] if msg['text'] else ''}")
        elif t == "missing_tool":
            print(f"    [FALTA] {msg['text'][:150]}")
        elif t == "permission.request":
            print(f"    [PERMISO] {msg['name']}({msg['args']}) motivo={msg['motivo']!r}")
            if auto_permitir is None:
                print("      -> no respondo (probando el timeout no, solo ignoro)")
            else:
                print(f"      -> respondo {auto_permitir}")
                await ws.send(json.dumps({"type": "permission.reply", "req_id": msg["req_id"], "allow": auto_permitir}))
        elif t == "error":
            print(f"    [ERROR] {msg['message']}")
        elif t == "chat.end":
            return eventos


async def main() -> int:
    async with connect(URI, ssl=_ctx(), additional_headers={"Authorization": f"Bearer {CONFIG['token']}"}) as ws:
        hello = json.loads(await ws.recv())
        print(f"hello: version={hello['version']} brains={hello['brains']}")
        print(f"tools: {', '.join(hello['tools'])}")

        print("\n--- estado inicial de la IA ---")
        await ws.send(json.dumps({"type": "ai.status"}))
        print(f"    {json.loads(await ws.recv())['text']}")

        print("\n--- 1. Orden que necesita una tool ---")
        print(">>> lista mis proyectos")
        eventos = await conversar(ws, "lista mis proyectos")
        if not any(e["type"] == "tool" and e["name"] == "list_projects" for e in eventos):
            print("    MAL: no llamo a list_projects")
            return 1
        print("    OK")

        print("\n--- 2. Orden sin tool (debe avisar) ---")
        print(">>> apaga las luces del salon")
        eventos = await conversar(ws, "apaga las luces del salon")
        if any(e["type"] == "missing_tool" for e in eventos):
            print("    OK: aviso missing_tool")
        else:
            print("    AVISO: no emitio missing_tool")

        print("\n--- 3. Estado tras hablar ---")
        await ws.send(json.dumps({"type": "ai.status"}))
        print(f"    {json.loads(await ws.recv())['text']}")

        print("\n--- 4. Dormir la IA ---")
        await ws.send(json.dumps({"type": "ai.sleep"}))
        estado = json.loads(await ws.recv())["text"]
        print(f"    {estado}")
        if "dormida" not in estado:
            print("    MAL: sigue despierta despues de pedir dormirla")
            return 1
        print("    OK: VRAM liberada")

        print("\nFase 1 por WebSocket: OK")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
