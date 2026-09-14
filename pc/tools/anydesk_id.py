"""Arranca AnyDesk (si hace falta) y dice el codigo para conectarse al PC.

Esta tool existe por un caso real: estando en el gym, si `arrancar.bat` se cierra
o el servicio se cuelga, el chat se cae y con el se va TODO el acceso al PC.
AnyDesk es la red de seguridad de eso -- pero justo cuando la necesitas es cuando
ya no te la puede dar el chat. Tenerla como tool no es un capricho: es el unico
camino a "recuperar el PC" que no depende de que el resto siga en pie, y por eso
merece un atajo en vez de dos comandos que aprobar a mano cada vez.

Por que no `AnyDesk.exe --get-id`: aqui AnyDesk es un portable suelto, sin
servicio instalado, y con esta version `--get-id` devuelve una cadena VACIA
(comprobado). El ID de verdad esta en `%APPDATA%\\AnyDesk\\system.conf`, en la
clave `ad.anynet.id`.

OJO -- no toques `service.conf`, que esta en esa misma carpeta: ahi dentro vive la
**clave privada** de esta instalacion de AnyDesk. Lo que sale de una tool lo lee
un modelo y viaja por el chat al movil; un secreto no tiene por que pasar por
ninguno de los dos. Esta tool solo abre `system.conf`, que no tiene claves.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from _util import spawn_detached
from controladora import paths

SPEC = {
    "name": "anydesk_id",
    "description": (
        "Abre AnyDesk en el PC (si no lo esta ya) y devuelve el codigo/ID de AnyDesk para "
        "conectarse a este ordenador en remoto. Usalo si te piden el codigo de AnyDesk, "
        "abrir AnyDesk, o poder controlar el PC en remoto por si falla el chat."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

CONFIRM = False

SYSTEM_CONF = Path(os.environ["APPDATA"]) / "AnyDesk" / "system.conf"


def _leer_id() -> str | None:
    if not SYSTEM_CONF.exists():
        return None
    for linea in SYSTEM_CONF.read_text(encoding="utf-8", errors="replace").splitlines():
        if linea.startswith("ad.anynet.id="):
            valor = linea.split("=", 1)[1].strip()
            return valor or None
    return None


def _bonito(codigo: str) -> str:
    """1047548243 -> '1 047 548 243', como lo enseña la propia ventana de AnyDesk."""
    resto = codigo
    grupos = []
    while len(resto) > 3:
        grupos.insert(0, resto[-3:])
        resto = resto[:-3]
    grupos.insert(0, resto)
    return " ".join(grupos)


def _corriendo() -> bool:
    import psutil

    return any(p.info["name"] == "AnyDesk.exe" for p in psutil.process_iter(["name"]))


def run() -> str:
    exe = paths.app("anydesk")
    if not exe:
        return "No se donde esta AnyDesk: falta la entrada 'anydesk' en apps de paths.json."
    if not Path(exe).exists():
        return f"AnyDesk esta configurado en {exe} pero ese fichero no existe."

    ya_estaba = _corriendo()
    if not ya_estaba:
        spawn_detached([exe])
        # AnyDesk tarda unos segundos en registrarse en la red y escribir el ID.
        # Sin esta espera, la primera vez se devolvia "no encuentro el codigo"
        # aunque un segundo despues ya estuviera.
        for _ in range(20):
            time.sleep(0.5)
            if _leer_id():
                break

    codigo = _leer_id()
    if not codigo:
        return (
            "He abierto AnyDesk pero todavia no encuentro el codigo en system.conf. "
            "Espera unos segundos y vuelve a pedirmelo."
        )

    estado = "ya estaba abierto" if ya_estaba else "lo acabo de abrir"
    return (
        f"Codigo de AnyDesk de este PC: {_bonito(codigo)}  ({estado})\n"
        "Metelo en AnyDesk del movil para controlar el PC en remoto."
    )
