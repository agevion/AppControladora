"""Prueba de las Acciones rapidas y el Monitor, por el WebSocket real.

    python scripts/test_acciones.py

Comprueba lo que estaba roto y por que:

- `projects.request`: la lista de proyectos la manda el PC leyendo su propio
  paths.json. Antes esto era un mensaje a Claude Code pidiendole que buscase
  "pc/paths.json", que ni podia encontrar (su cwd es la carpeta del proyecto)
  ni tenia por que buscar (el fichero esta en este mismo proceso).
- `action.request` CON argumentos: un boton llama a la tool que quiere con los
  argumentos que quiere, sin cerebro y sin tokens. Antes solo se podian llamar
  tools sin parametros, asi que "compila tal proyecto" no podia ser un boton.
- `stats.request`: ademas del texto, manda los numeros para dibujar.

No necesita Ollama: nada de esto pasa por un cerebro. Ese es justo el punto.
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


async def recibir_hasta(ws, tipo: str, timeout: float = 30.0) -> list[dict]:
    """Recoge mensajes hasta ver `tipo`. Devuelve todo lo que llego.

    wait_for y no asyncio.timeout: este PC tiene Python 3.10 (ARQUITECTURA.md
    seccion 2) y asyncio.timeout no existe hasta la 3.11.
    """
    eventos: list[dict] = []

    async def _bucle() -> list[dict]:
        while True:
            msg = json.loads(await ws.recv())
            eventos.append(msg)
            if msg["type"] == tipo:
                return eventos

    return await asyncio.wait_for(_bucle(), timeout)


async def main() -> int:
    fallos = 0

    async with connect(
        URI, ssl=_ctx(), additional_headers={"Authorization": f"Bearer {CONFIG['token']}"}
    ) as ws:
        hello = json.loads(await ws.recv())
        print(f"hello: protocolo v{hello['version']}, {len(hello['tools'])} tools")

        # --- proyectos, sin LLM de por medio -------------------------------
        await ws.send(json.dumps({"type": "projects.request"}))
        eventos = await recibir_hasta(ws, "projects.result")
        proyectos = eventos[-1]["projects"]
        print(f"\nprojects.result: {len(proyectos)} proyectos")
        for p in proyectos[:4]:
            print(f"   {p['nombre']:20} {p['tipo']:7} existe={p['existe']}")
        if not proyectos:
            print("FALLO: sin proyectos")
            fallos += 1

        # --- stats con datos, no solo un parrafo --------------------------
        await ws.send(json.dumps({"type": "stats.request"}))
        eventos = await recibir_hasta(ws, "stats.result")
        stats = eventos[-1]
        data = stats.get("data") or {}
        print("\nstats.result:")
        print(f"   texto: {stats['text'].splitlines()[0]}")
        if not data.get("cpu"):
            print("FALLO: stats.result sin datos para dibujar")
            fallos += 1
        else:
            print(f"   data: cpu={data['cpu']['pct']}% ram={data['ram']['pct']}% "
                  f"nucleos={len(data['cpu']['por_nucleo'])} discos={len(data['discos'])}")
            print(f"   temp cpu: {data['cpu']['temp_c']} (nota: {'si' if data['cpu']['temp_nota'] else 'no'})")

        # --- una accion CON argumentos, que es lo que no se podia ----------
        # system_stats no toca nada y no pide confirmacion: sirve para probar el
        # camino entero (tool -> tool.result -> action.result -> chat.end) sin
        # arrancar un build de tres minutos en una prueba.
        await ws.send(json.dumps({"type": "action.request", "id": "acc1", "name": "system_stats", "args": {}}))
        eventos = await recibir_hasta(ws, "chat.end")
        tipos = [e["type"] for e in eventos]
        print(f"\naction.request(system_stats): {tipos}")
        for esperado in ("tool", "tool.result", "action.result", "chat.end"):
            if esperado not in tipos:
                print(f"FALLO: falta {esperado}")
                fallos += 1
        if not any(e["type"] == "action.result" and e["ok"] for e in eventos):
            print("FALLO: action.result no dice ok")
            fallos += 1
        if not all(e.get("id") == "acc1" for e in eventos if "id" in e):
            print("FALLO: los eventos no llevan el id que mando el movil (el turno no se cerraria)")
            fallos += 1

        # --- una accion con argumentos de verdad, y que falle bien ---------
        # Un proyecto que no existe: la tool tiene que contestar que no lo conoce
        # y la accion tiene que cerrarse igual (chat.end), no dejar el indicador
        # del movil colgado para siempre.
        await ws.send(json.dumps({
            "type": "action.request", "id": "acc2", "name": "open_app",
            "args": {"app": "android_studio", "proyecto": "no_existe_este_proyecto"},
        }))
        eventos = await recibir_hasta(ws, "chat.end")
        resultado = next((e for e in eventos if e["type"] == "action.result"), None)
        print(f"\naction.request(open_app, proyecto inexistente): {resultado['text'][:60] if resultado else 'SIN RESPUESTA'}")
        if resultado is None or "no conozco" not in resultado["text"].lower():
            print("FALLO: no se paso el argumento 'proyecto' a la tool")
            fallos += 1
        if "chat.end" not in [e["type"] for e in eventos]:
            print("FALLO: sin chat.end -> el movil se quedaria 'ejecutando...' para siempre")
            fallos += 1

    print("\n" + ("TODO OK" if fallos == 0 else f"{fallos} FALLOS"))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
