"""Prueba el traspaso PC <-> movil: portapapeles y ficheros (v14).

    python scripts/test_traspaso.py            # necesita el servicio arrancado
    python scripts/test_traspaso.py 8444       # contra otra instancia, en otro puerto

Cinco comprobaciones, en el orden en que se usan de verdad:
  1. clip.get           -> el PC contesta con lo que tiene copiado
  2. clip.watch + Ctrl+C-> copiar en el PC empuja el texto al movil sin pedir nada
  3. clip.set           -> lo que manda el movil queda copiado en el PC
  4. POST /upload       -> el fichero aterriza en la carpeta de recibidos
  5. /upload sin token  -> rechazado

Toca el portapapeles de verdad (es lo que se esta probando), asi que guarda lo
que hubiera copiado al empezar y lo devuelve al terminar, pase lo que pase.

Lo que NO prueba: la parte de Compose. Es la misma leccion de la Fase E.1 -- las
pruebas del PC pasaban enteras con el movil sin funcionar. Esto dice que el PC
cumple su lado del contrato, no que en el telefono se vea nada.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import ssl
import sys
import time
from pathlib import Path
from urllib.parse import quote

PC_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PC_DIR))

from websockets.asyncio.client import connect  # noqa: E402

from controladora import portapapeles, recibidos  # noqa: E402

CERTS = PC_DIR / "certs"
CONFIG = json.loads((PC_DIR / "config.json").read_text(encoding="utf-8"))
# El puerto se puede cambiar para probar contra una instancia aparte sin tumbar
# el servicio que este atendiendo al movil:  python scripts/test_traspaso.py 8444
PUERTO = int(sys.argv[1]) if len(sys.argv) > 1 else CONFIG["port"]
TOKEN = CONFIG["token"]
URI = f"wss://localhost:{PUERTO}/ws"

MARCA = f"traspaso-{int(time.time())}"


def _ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(CERTS / "ca.crt"))
    ctx.load_cert_chain(str(CERTS / "client.crt"), str(CERTS / "client.key"))
    return ctx


async def _esperar(ws, tipo: str, segundos: float = 6.0) -> dict | None:
    """El primer mensaje de ese tipo, saltandose lo que llegue por medio."""
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        try:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=limite - time.monotonic()))
        except asyncio.TimeoutError:
            return None
        if msg.get("type") == tipo:
            return msg
    return None


async def pruebas_portapapeles() -> list[bool]:
    resultados: list[bool] = []
    async with connect(URI, ssl=_ctx(), additional_headers={"Authorization": f"Bearer {TOKEN}"}) as ws:
        await _esperar(ws, "hello")

        print("1) clip.get: el PC contesta con lo que tiene copiado")
        portapapeles.escribir(f"{MARCA}-uno")
        await ws.send(json.dumps({"type": "clip.get"}))
        msg = await _esperar(ws, "clip.text")
        ok = bool(msg) and msg.get("text") == f"{MARCA}-uno"
        print("   OK" if ok else f"   MAL: llego {msg}")
        resultados.append(ok)

        print("2) clip.watch: copiar en el PC empuja el texto solo")
        await ws.send(json.dumps({"type": "clip.watch", "on": True}))
        # Un respiro para que el vigilante arranque y de por visto lo de antes.
        await asyncio.sleep(1.0)
        portapapeles.escribir(f"{MARCA}-dos")
        msg = await _esperar(ws, "clip.text")
        ok = bool(msg) and msg.get("text") == f"{MARCA}-dos"
        print("   OK" if ok else f"   MAL: llego {msg}")
        resultados.append(ok)

        print("3) clip.set: lo del movil queda copiado en el PC")
        await ws.send(json.dumps({"type": "clip.set", "text": f"{MARCA}-tres"}))
        await asyncio.sleep(1.0)
        ok = portapapeles.leer() == f"{MARCA}-tres"
        print("   OK" if ok else f"   MAL: el PC tiene {portapapeles.leer()!r}")
        resultados.append(ok)

        # Y no debe rebotar: escribirlo nosotros no es "el usuario copio algo".
        eco = await _esperar(ws, "clip.text", segundos=2.0)
        ok = eco is None
        print("   OK: no rebota" if ok else f"   MAL: volvio el eco {eco}")
        resultados.append(ok)

        await ws.send(json.dumps({"type": "clip.watch", "on": False}))
    return resultados


def _subir(
    nombre: str,
    datos: bytes,
    token: str | None = TOKEN,
    dice_bytes: int | None = None,
) -> tuple[int, dict | str]:
    conn = http.client.HTTPSConnection("localhost", PUERTO, context=_ctx(), timeout=30)
    cabeceras = {"X-Nombre": quote(nombre), "Content-Type": "application/octet-stream"}
    if dice_bytes is not None:
        cabeceras["X-Bytes"] = str(dice_bytes)
    if token is not None:
        cabeceras["Authorization"] = f"Bearer {token}"
    conn.request("POST", "/upload", body=datos, headers=cabeceras)
    r = conn.getresponse()
    cuerpo = r.read().decode("utf-8", "replace")
    conn.close()
    try:
        return r.status, json.loads(cuerpo)
    except json.JSONDecodeError:
        return r.status, cuerpo


def pruebas_ficheros() -> list[bool]:
    resultados: list[bool] = []
    datos = f"contenido de prueba {MARCA}".encode("utf-8")

    print("4) POST /upload: el fichero aterriza en la carpeta")
    # Con una ruta dentro del nombre a proposito: tiene que quedarse en el nombre
    # pelado y NO salir de la carpeta (ver recibidos.nombre_seguro).
    estado, cuerpo = _subir(f"../../{MARCA}.txt", datos)
    ok = estado == 200 and isinstance(cuerpo, dict) and cuerpo.get("ok")
    if ok:
        guardado = Path(cuerpo["ruta"])
        ok = (
            guardado.parent == recibidos.carpeta()
            and guardado.read_bytes() == datos
            and guardado.name == f"{MARCA}.txt"
        )
        print(f"   OK: {guardado}" if ok else f"   MAL: acabo en {guardado}")
    else:
        print(f"   MAL: HTTP {estado} {cuerpo}")
    resultados.append(bool(ok))

    print("   ... y el segundo con el mismo nombre no pisa al primero")
    estado, cuerpo = _subir(f"{MARCA}.txt", datos)
    ok = estado == 200 and isinstance(cuerpo, dict) and cuerpo.get("nombre") == f"{MARCA} (2).txt"
    print("   OK" if ok else f"   MAL: HTTP {estado} {cuerpo}")
    resultados.append(ok)

    print("5) POST /upload con X-Bytes que no cuadra: se tira, no se queda a medias")
    estado, cuerpo = _subir(f"{MARCA}-cortado.txt", datos, dice_bytes=len(datos) + 100)
    quedo = (recibidos.carpeta() / f"{MARCA}-cortado.txt").exists()
    ok = estado == 400 and not quedo
    print("   OK" if ok else f"   MAL: HTTP {estado} {cuerpo}, fichero en la carpeta: {quedo}")
    resultados.append(ok)

    print("6) POST /upload sin token: rechazado")
    estado, cuerpo = _subir(f"{MARCA}-cuela.txt", datos, token=None)
    ok = estado == 403
    print("   OK" if ok else f"   MAL: HTTP {estado} {cuerpo}")
    resultados.append(ok)
    return resultados


async def main() -> int:
    antes = portapapeles.leer()
    print(f"(guardado tu portapapeles: {len(antes)} caracteres)" if antes else "(tu portapapeles no tenia texto)")
    try:
        resultados = await pruebas_portapapeles()
        resultados += pruebas_ficheros()
    finally:
        if antes:
            portapapeles.escribir(antes)
            print("(portapapeles devuelto a como estaba)")

    print()
    fallan = resultados.count(False)
    if not fallan:
        print(f"Traspaso: las {len(resultados)} comprobaciones pasan")
        print(f"Los ficheros de prueba quedan en {recibidos.carpeta()} (empiezan por {MARCA})")
        return 0
    print(f"FALLAN {fallan} de {len(resultados)}")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
