"""Prueba del boton "Guardar": run_shell -> tool permanente, por el WS real.

    python scripts/test_toolgen.py

Cubre el bucle entero de la seccion 8.1: la IA local propone un comando para algo
que no tiene tool, el usuario lo guarda, el registry lo recarga en caliente, y la
tool ya se puede pedir por su nombre sin que vuelva a pedir permiso.

Limpia detras de si: borra la tool que genera.
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
NOMBRE = "test_listar_procesos"
GENERADA = PC_DIR / "tools" / f"{NOMBRE}.py"


def _ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(CERTS / "ca.crt"))
    ctx.load_cert_chain(str(CERTS / "client.crt"), str(CERTS / "client.key"))
    return ctx


async def conversar(ws, texto: str, accion: str | None = None, nombre: str = "") -> list[dict]:
    """Manda un mensaje y recoge todo hasta chat.end, respondiendo a los permisos."""
    await ws.send(json.dumps({"type": "chat", "id": "m1", "brain": "local", "text": texto}))

    eventos = []
    while True:
        msg = json.loads(await ws.recv())
        eventos.append(msg)
        t = msg["type"]

        if t == "chat.delta":
            print(f"    [texto] {msg['text'][:160]}")
        elif t == "tool":
            print(f"    [TOOL]  {msg['name']}({msg['args']})  confirm={msg['confirm']}")
        elif t == "tool.result":
            primera = msg["text"].splitlines()[0][:110] if msg["text"] else ""
            print(f"    [res]   {primera}")
        elif t == "missing_tool":
            print(f"    [FALTA] {msg['text'][:140]}")
        elif t == "tool.saved":
            print(f"    [GUARDAR] ok={msg['ok']} {msg['text']}")
        elif t == "hello":
            print(f"    [hello] {len(msg['tools'])} tools")
        elif t == "permission.request":
            print(f"    [PERMISO] {msg['name']}({msg['args']})")
            print(f"      savable={msg.get('savable')} sugerencia={msg.get('sugerencia')!r}")
            if accion is None:
                print("      -> lo ignoro")
                continue
            print(f"      -> respondo {accion!r} nombre={nombre!r}")
            await ws.send(
                json.dumps(
                    {"type": "permission.reply", "req_id": msg["req_id"], "action": accion, "nombre": nombre}
                )
            )
        elif t == "error":
            print(f"    [ERROR] {msg['message']}")
        elif t == "chat.end":
            return eventos


async def main() -> int:
    if GENERADA.exists():
        GENERADA.unlink()

    fallos: list[str] = []

    async with connect(
        URI, ssl=_ctx(), additional_headers={"Authorization": f"Bearer {CONFIG['token']}"}
    ) as ws:
        hello = json.loads(await ws.recv())
        antes = len(hello["tools"])
        print(f"hello: version={hello['version']}  {antes} tools")

        print("\n--- 1. Algo sin tool que SI se hace con PowerShell ---")
        print(">>> que procesos estan consumiendo mas CPU?")
        eventos = await conversar(
            ws, "que procesos estan consumiendo mas CPU?", accion="save", nombre=NOMBRE
        )

        permisos = [e for e in eventos if e["type"] == "permission.request"]
        if not permisos:
            fallos.append("no pidio permiso: el modelo no uso run_shell (antes decia 'no disponible')")
        elif not permisos[0].get("savable"):
            fallos.append("el permiso de run_shell no vino marcado como savable")
        elif not permisos[0].get("sugerencia"):
            fallos.append("no propuso ningun nombre para guardar")

        guardadas = [e for e in eventos if e["type"] == "tool.saved"]
        if not guardadas:
            fallos.append("no llego tool.saved tras responder 'save'")
        elif not guardadas[0]["ok"]:
            fallos.append(f"no la guardo: {guardadas[0]['text']}")

        if not GENERADA.exists():
            fallos.append(f"no existe el fichero {GENERADA.name}")
        else:
            print(f"    OK: escrito {GENERADA.name}")

        hellos = [e for e in eventos if e["type"] == "hello"]
        if not hellos:
            fallos.append("no reenvio la lista de tools tras guardar")
        elif NOMBRE not in hellos[-1]["tools"]:
            fallos.append("la tool nueva no aparece en la lista del movil")
        else:
            print(f"    OK: el movil ya ve {len(hellos[-1]['tools'])} tools (antes {antes})")

        if fallos:
            return _resumen(fallos)

        print("\n--- 2. Usarla por su nombre: ya no debe pedir permiso ---")
        print(f">>> usa la herramienta {NOMBRE}")
        eventos = await conversar(ws, f"usa la herramienta {NOMBRE}", accion=None)

        if any(e["type"] == "permission.request" for e in eventos):
            fallos.append("volvio a pedir permiso: la tool guardada deberia tener CONFIRM=False")
        llamadas = [e for e in eventos if e["type"] == "tool" and e["name"] == NOMBRE]
        if not llamadas:
            fallos.append("no llamo a la tool recien guardada")
        else:
            print("    OK: la llamo sola y sin tarjeta de permiso")

        print("\n--- 3. Un comando que falla NO se guarda ---")
        print(">>> ejecuta en PowerShell: estecomandonoexiste123")
        eventos = await conversar(
            ws, "ejecuta en PowerShell este comando: estecomandonoexiste123", accion="save", nombre="test_fallo"
        )
        guardadas = [e for e in eventos if e["type"] == "tool.saved"]
        if guardadas and guardadas[0]["ok"]:
            fallos.append("guardo una tool a partir de un comando que fallo")
        elif guardadas:
            print(f"    OK: se nego -> {guardadas[0]['text']}")
        else:
            print("    (el modelo no llego a ejecutar nada; sin comprobar)")
        if (PC_DIR / "tools" / "test_fallo.py").exists():
            fallos.append("existe test_fallo.py: guardo un comando fallido")

    return _resumen(fallos)


def _resumen(fallos: list[str]) -> int:
    print()
    if fallos:
        for f in fallos:
            print(f"MAL: {f}")
        return 1
    print("Guardar herramienta por WebSocket: OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    finally:
        # La prueba no debe dejar tools de mentira en el sistema de verdad.
        for f in (GENERADA, PC_DIR / "tools" / "test_fallo.py"):
            if f.exists():
                f.unlink()
                print(f"(limpieza: borrado {f.name})")
