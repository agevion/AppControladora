"""Instala un APK en el movil conectado al PC.

Antes de instalar, si `adb devices` no ve ningun dispositivo, intenta reconectar
solo via adb_connect (Tailscale) antes de rendirse. Es la misma logica que ya
justifica build_and_install: encadenar dos tools a mano depende de que un
modelo de 8B se acuerde de hacerlo en ese orden, y eso es fragil. Mejor que el
propio adb_install se autorepare, sin que nadie tenga que pedirlo.
"""

from __future__ import annotations

from pathlib import Path

import adb_connect
from _util import run_process, tail
from controladora import apk as apk_util
from controladora import paths, progress, variantes

SPEC = {
    "name": "adb_install",
    "description": (
        "Instala un APK en el dispositivo Android conectado al PC. Si le pasas un "
        "nombre de proyecto en vez de una ruta, coge el APK mas reciente de la variante "
        "que le toca a ese proyecto (release si puede firmarla)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "apk": {
                "type": "string",
                "description": "Ruta completa a un .apk, O el nombre de un proyecto gradle conocido",
            },
        },
        "required": ["apk"],
    },
}

CONFIRM = False


def _resolve(apk: str) -> tuple[Path | None, str]:
    directo = Path(apk)
    if directo.suffix.lower() == ".apk" and directo.exists():
        return directo, ""

    p = paths.project(apk)
    if not p:
        return None, (
            f"'{apk}' no es ni un .apk existente ni un proyecto conocido. "
            f"Proyectos: {', '.join(paths.projects())}"
        )
    if p.get("type") != "gradle":
        return None, f"'{apk}' es un proyecto {p.get('type')}, no genera APKs."

    # De la variante que le toca al proyecto, no "el mas reciente de cualquiera":
    # si acabas de compilar una debug para depurar, un release viejo tirado en
    # outputs/ no debe colarse como lo que se instala (ni al reves).
    reciente = paths.latest_apk(p, variantes.para(p).tarea)
    if reciente is None:
        return None, f"'{apk}' no tiene ningun APK compilado todavia. Usa build_gradle primero."

    return reciente, ""


def _hay_dispositivo(adb: str) -> bool:
    code, out = run_process([adb, "devices"], timeout=15)
    if code != 0:
        return False
    # La primera linea es la cabecera ("List of devices attached"); un
    # dispositivo "offline" no sirve para instalar, solo "device" cuenta.
    lineas = out.strip().splitlines()[1:]
    return any(l.strip().endswith("device") for l in lineas)


def run(apk: str) -> str:
    adb = paths.binary("adb")
    if not adb:
        return "adb no configurado en paths.json (bin.adb)"

    ruta, error = _resolve(apk)
    if error:
        return error
    assert ruta is not None

    if not apk_util.is_signed(ruta):
        return apk_util.signing_error(ruta)

    aviso_reconexion = ""
    if not _hay_dispositivo(adb):
        # No hay cable ni sesion adb viva: la unica via inalambrica que cruza
        # Tailscale es el modo tcpip fijo (ver adb_connect.py). Se intenta
        # sola en vez de devolver un error y esperar a que alguien la pida.
        progress.report("No hay movil conectado, reconectando por Tailscale...")
        resultado_conexion = adb_connect.run()
        if "Conectado a" not in resultado_conexion:
            return (
                "No hay ningun dispositivo y no he podido reconectar por Tailscale:\n\n"
                f"{resultado_conexion}"
            )
        aviso_reconexion = f"(sin dispositivo -> reconectado solo)\n{resultado_conexion}\n\n"
        progress.report(f"Reconectado. Instalando {ruta.name}...")
    else:
        progress.report(f"Instalando {ruta.name} en el movil...")

    code, out = run_process([adb, "install", "-r", str(ruta)], timeout=300, stream_progress=True)
    estado = "OK" if code == 0 and "Success" in out else f"FALLO (codigo {code})"
    return f"{aviso_reconexion}adb_install {ruta.name} -> {estado}\n\n{tail(out, 15)}"
