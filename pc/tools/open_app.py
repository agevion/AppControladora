"""Abre un IDE o aplicacion de desarrollo."""

from __future__ import annotations

from pathlib import Path

from _util import spawn_detached
from controladora import paths

SPEC = {
    "name": "open_app",
    "description": (
        "Abre una aplicacion de desarrollo en el PC: Android Studio, IntelliJ IDEA "
        "o Unity Hub. Opcionalmente abre directamente un proyecto concreto."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "app": {
                "type": "string",
                "enum": ["android_studio", "intellij", "unity_hub"],
                "description": "Que aplicacion abrir",
            },
            "proyecto": {
                "type": "string",
                "description": (
                    "Opcional. Nombre del proyecto a abrir con esa app "
                    "(usa list_projects para ver los nombres validos)."
                ),
            },
        },
        "required": ["app"],
    },
}

CONFIRM = False


def run(app: str, proyecto: str | None = None) -> str:
    exe = paths.app(app)
    if not exe:
        disponibles = ", ".join(paths.apps())
        return f"No conozco la app '{app}'. Disponibles: {disponibles}"

    if not Path(exe).exists():
        return f"La app '{app}' esta configurada en {exe} pero ese fichero no existe."

    cmd = [exe]
    detalle = ""

    if proyecto:
        p = paths.project(proyecto)
        if not p:
            disponibles = ", ".join(paths.projects())
            return f"No conozco el proyecto '{proyecto}'. Disponibles: {disponibles}"
        cmd.append(p["path"])
        detalle = f" con el proyecto {proyecto} ({p['path']})"

    spawn_detached(cmd)
    return f"Abriendo {app}{detalle}. Tarda unos segundos en aparecer."
