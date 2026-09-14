"""El Cerebro D por el WebSocket, como lo hara el movil.

    python scripts/test_appctl_ws.py                     # solo lee y pulsa
    python scripts/test_appctl_ws.py --enviar "hola"     # ademas escribe y envia

Con el servicio arrancado. `test_appctl.py` prueba la capa `appctl` llamando a
sus clases por dentro; esto prueba el transporte real: los mensajes app.* del
protocolo v12, el cerebro "app" en server.py y el mismo mTLS que usa el movil.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import ssl
import sys
from pathlib import Path
from typing import Any

from websockets.asyncio.client import connect

PC_DIR = Path(__file__).resolve().parent.parent
CERTS = PC_DIR / "certs"
CONFIG = json.loads((PC_DIR / "config.json").read_text(encoding="utf-8"))

URI = f"wss://localhost:{CONFIG['port']}/ws"


def _ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(CERTS / "ca.crt"))
    ctx.load_cert_chain(str(CERTS / "client.crt"), str(CERTS / "client.key"))
    return ctx


async def esperar(ws, tipo: str, timeout: float = 60.0) -> dict[str, Any]:
    """El primer mensaje de ese tipo. Los de por medio se imprimen y se tiran."""
    limite = asyncio.get_running_loop().time() + timeout
    while True:
        restante = limite - asyncio.get_running_loop().time()
        if restante <= 0:
            raise TimeoutError(f"no llego ningun {tipo} en {timeout:.0f}s")
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=restante))
        if msg["type"] == "error":
            print(f"    [error del PC] {msg['message']}")
        if msg["type"] == tipo:
            return msg


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--enviar", metavar="TEXTO", help="escribe TEXTO en la app y espera respuesta")
    ap.add_argument("--sesion", default="", help="titulo de la conversacion destino")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    fallos = 0

    async with connect(
        URI, ssl=_ctx(), additional_headers={"Authorization": f"Bearer {CONFIG['token']}"}
    ) as ws:
        hello = json.loads(await ws.recv())
        print(f"hello: version={hello['version']} brains={hello['brains']}")
        if "app" not in hello["brains"]:
            print("  FALLO: el PC no anuncia el cerebro 'app'")
            fallos += 1
        if hello["version"] < 12:
            print(f"  FALLO: protocolo v{hello['version']}, se esperaba 12 o mas")
            fallos += 1

        print("\n--- app.request: el estado de la aplicacion ---")
        await ws.send(json.dumps({"type": "app.request"}))
        estado = await esperar(ws, "app.state")
        print(f"  abierta={estado['abierta']} titulo={estado['titulo']!r}")
        print(f"  modelo={estado['modelo']!r} uso={estado['uso']!r}")
        print(f"  mandos={estado['mandos']}")
        for s in estado["sesiones"][:4]:
            print(f"    {s['titulo']!r} trabajando={s['trabajando']} permisos={s['permisos']}")

        if not estado["abierta"]:
            print("  FALLO: la app de escritorio no esta abierta; abrela y repite")
            return 1
        if not estado["sesiones"]:
            print("  FALLO: ninguna conversacion visible")
            fallos += 1
        if not estado["mandos"]:
            print("  FALLO: ningun mando visible")
            fallos += 1

        # Se comprueba la ida y vuelta de una orden abriendo la conversacion que
        # YA esta abierta: el PC la busca en la barra lateral, la pulsa y
        # devuelve el estado, o sea el contrato entero de los app.*, pero sin
        # cambiar nada de lo que hay en pantalla.
        #
        # NO se prueba aqui ni `app.stop` ni pulsar mandos sueltos, y el motivo
        # es de los que hay que dejar escritos: esta prueba se ejecuta desde una
        # conversacion que corre DENTRO de esa misma aplicacion. `app.stop` manda
        # Escape a la ventana, y ese Escape cae sobre la tarjeta de aprobacion de
        # la propia orden que lo lanzo -- la app lo lee como "cancelado" y la
        # herramienta muere sola, sin que nadie haya tocado nada. Pasó de verdad,
        # tres veces seguidas, y desde fuera se ve como "el usuario ha
        # rechazado". Para probar esos dos hace falta que el PC no este pilotando
        # la sesion que lo esta pilotando: usa `--sesion` con OTRA conversacion.
        if estado["titulo"]:
            print(f"\n--- app.open: reabrir la que ya esta abierta ({estado['titulo']!r}) ---")
            await ws.send(json.dumps({"type": "app.open", "titulo": estado["titulo"]}))
            despues = await esperar(ws, "app.state")
            if despues["titulo"] == estado["titulo"]:
                print("  OK: sigue abierta la misma y el PC devolvio el estado")
            else:
                print(f"  FALLO: acabo abierta {despues['titulo']!r}")
                fallos += 1
        else:
            print("\n--- app.open: SALTADO (no hay ninguna conversacion abierta) ---")

        if args.enviar:
            print(f"\n--- chat con brain='app': {args.enviar!r} ---")
            await ws.send(
                json.dumps(
                    {
                        "type": "chat",
                        "id": "app-1",
                        "brain": "app",
                        "text": args.enviar,
                        "sesion": args.sesion,
                    }
                )
            )
            texto, tools = "", []
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=300))
                t = msg["type"]
                if t == "chat.delta":
                    texto += msg["text"]
                    print(f"    [texto] {msg['text'].strip()[:160]}")
                elif t == "tool":
                    tools.append(msg["name"])
                    print(f"    [tool]  {msg['name']}")
                elif t == "error":
                    print(f"    [ERROR] {msg['message']}")
                elif t == "chat.end":
                    break
            if not texto.strip() and not tools:
                print("  FALLO: el turno no devolvio ni texto ni herramientas")
                fallos += 1
            else:
                print(f"  OK: {len(texto)} caracteres, herramientas={tools}")
        else:
            print('\n--- chat con brain="app": SALTADO (pasa --enviar "texto") ---')

    print("\n" + "=" * 60)
    if fallos:
        print(f"{fallos} comprobaciones han fallado.")
        return 1
    print("Cerebro D por WebSocket: OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
