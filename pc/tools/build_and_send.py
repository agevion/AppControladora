"""Compila un proyecto Android y manda el APK al movil por el propio chat
(WSS/mTLS, la misma conexion de siempre) -- sin adb y sin que el movil
necesite estar en la misma red ni tener la depuracion inalambrica activa.

Antes esto encadenaba build_gradle + adb_install (build_and_install.py), pero
eso depende de que el movil sea alcanzable por adb: mismo WiFi, o el modo
tcpip fijo que se resetea solo al reiniciar el telefono o al tocar el
interruptor de Depuracion inalambrica (ver adb_connect.py). Va justo al reves
de la idea del proyecto: PC con arrancar.bat abierto en casa, movil en el gym
con datos moviles, sin ninguna dependencia de red local. El APK viaja por el
mismo sitio que ya usa el chat (ver controladora/artifacts.py y el endpoint
GET /artifact/<id> en server.py); el movil lo instala tocando "Instalar"
cuando le llega el aviso.

Que variante se manda NO se decide aqui a ojo: la elige controladora/variantes.py
mirando el build.gradle del proyecto, y por defecto es release. Durante mucho
tiempo esto mandaba siempre `assembleDebug`, y un APK de debug lleva el flag
`debuggable`, que apaga optimizaciones de ART: la app que acababa instalada en
el movil iba medible y notablemente mas lenta que la de verdad, sin que nadie
lo hubiera pedido.

adb_install y adb_connect siguen existiendo tal cual para cuando el movil esta
conectado de verdad (USB, o en casa por la misma red): no son la via para
"mandame la build" pero siguen siendo utiles para eso otro.
"""

from __future__ import annotations

import build_gradle
from controladora import apk, artifacts, paths, progress, variantes

SPEC = {
    "name": "build_and_send",
    "description": (
        "Compila un proyecto Android Y manda el APK al chat del movil (sin adb, sin USB, sin "
        "que el movil necesite wifi ni depuracion inalambrica). Usa esta tool (no build_gradle "
        "ni adb_install) cuando te pidan compilar y mandar/instalar/desplegar en el telefono. "
        "Tarda entre segundos y varios minutos."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "proyecto": {
                "type": "string",
                "description": "Nombre del proyecto (usa list_projects si no lo sabes)",
            },
            "tarea": {
                "type": "string",
                "description": (
                    "Tarea de Gradle. NO la pongas salvo que te la pidan: si la omites se "
                    "manda la build de release (la app va a su velocidad real), y solo se "
                    "cae a debug si ese proyecto no puede firmar releases. Ponla solo si "
                    "te piden expresamente una build de debug ('assembleDebug')."
                ),
            },
        },
        "required": ["proyecto"],
    },
}

CONFIRM = False


def _compilar_y_localizar(proyecto: str, tarea: str | None):
    """Compila y devuelve (log, ruta_apk, tarea_usada). ruta_apk None si no hay."""
    usada = tarea or (variantes.por_nombre(proyecto) or variantes.Variante("", "")).tarea
    log = build_gradle.run(proyecto, tarea)

    primera = log.splitlines()[0] if log else ""
    if "FALLO" in primera:
        return log, None, usada

    p = paths.project(proyecto)
    return log, (paths.latest_apk(p, usada) if p else None), usada


def run(proyecto: str, tarea: str | None = None) -> str:
    log, ruta, usada = _compilar_y_localizar(proyecto, tarea)

    if ruta is None:
        if "FALLO" in (log.splitlines()[0] if log else ""):
            return log + "\n\n(No se ha mandado nada: el build ha fallado.)"
        return log + "\n\n(Build OK, pero no encuentro el APK para mandarlo.)"

    # El build puede ir OK y aun asi producir algo que el movil no puede instalar:
    # un release sin signingConfig compila perfectamente y sale sin firmar. Quien
    # lo decide es el fichero, no el nombre de la variante (ver apk.py).
    if not apk.is_signed(ruta):
        # Si la release la elegimos nosotros (no la pidio el usuario), no le
        # devolvemos un error: nos caemos a debug y se lo decimos. Preferible una
        # app en modo lento que un "no se puede instalar" y quedarse sin nada.
        if not tarea and usada == "assembleRelease":
            progress.report("La release sale sin firmar. Recompilando en debug...")
            log_debug, ruta, _ = _compilar_y_localizar(proyecto, "assembleDebug")
            log = (
                log
                + "\n\nLa release de este proyecto ha salido SIN FIRMAR (no tiene "
                "signingConfig que valga), asi que el movil no la aceptaria. "
                "Recompilo en debug y te mando esa; ojo, va mas lenta que la real.\n\n"
                + log_debug
            )
            if ruta is None or not apk.is_signed(ruta):
                return log + "\n\n(Tampoco la debug se puede mandar. Nada enviado.)"
        else:
            return log + "\n\n--- Envio al movil ---\n" + apk.signing_error(ruta)

    progress.report(f"Build OK. Mandando {ruta.name} al movil...")
    aviso = artifacts.ready(ruta)
    mb = aviso.size / 1024 / 1024
    texto = (
        log
        + f"\n\n--- Envio al movil ---\n{aviso.name} ({mb:.1f} MB) listo. "
        "Te llega un aviso en el chat con un boton Instalar."
    )

    # La release va firmada con otra clave que la debug, y Android no deja
    # instalar encima una app cuya firma no coincide con la instalada: sale
    # "aplicacion no instalada" sin decir por que. Es justo lo que va a pasar la
    # primera vez que se manda release a un movil que tenia la debug puesta, asi
    # que se dice antes de que ocurra en vez de dejar adivinarlo.
    if "release" in ruta.name.lower() or "release" in str(usada).lower():
        texto += (
            "\n\nSi al instalar dice 'aplicacion no instalada': es que ahi tienes "
            "puesta la version de debug, que va firmada con otra clave. Desinstala "
            "esa primero y vuelve a darle a Instalar."
        )
    return texto
