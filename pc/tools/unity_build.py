"""Compila un proyecto Unity en batchmode.

AVISO: Unity en batchmode necesita un metodo estatico de build DENTRO del proyecto
(-executeMethod). No es gratis: si el proyecto no lo tiene, esta tool no puede
hacer nada y te lo dice en vez de fallar de forma rara.
"""

from __future__ import annotations

from pathlib import Path

from _util import run_process, tail
from controladora import paths, progress

SPEC = {
    "name": "unity_build",
    "description": (
        "Compila un proyecto de Unity en modo batch (sin abrir el editor). Requiere "
        "que el proyecto tenga un metodo estatico de build. Tarda varios minutos."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "proyecto": {
                "type": "string",
                "description": "Nombre del proyecto Unity (usa list_projects)",
            },
            "metodo": {
                "type": "string",
                "description": (
                    "Metodo estatico de build, formato 'Clase.Metodo' "
                    "(ej: 'BuildScript.BuildWindows'). Si no lo sabes, preguntale al usuario."
                ),
            },
        },
        "required": ["proyecto", "metodo"],
    },
}

CONFIRM = False


def run(proyecto: str, metodo: str) -> str:
    p = paths.project(proyecto)
    if not p:
        return f"No conozco el proyecto '{proyecto}'. Disponibles: {', '.join(paths.projects())}"

    if p.get("type") != "unity":
        return f"'{proyecto}' es de tipo '{p.get('type')}', no unity. Para Gradle usa build_gradle."

    version = p.get("unity_version")
    editor = paths.unity_editor(version) if version else None
    if not editor:
        return f"No tengo el editor de Unity {version} en paths.json (unity_editors)."
    if not Path(editor).exists():
        return f"El editor {version} deberia estar en {editor} pero no existe."

    root = Path(p["path"])
    log_file = root / "controladora_build.log"

    # Unity en batchmode escribe casi todo al -logFile, no a stdout, asi que
    # stream_progress no serviria de nada aqui (no hay lineas que streamear).
    # Sin esto habria el mismo silencio total que tenian build_gradle/adb_install
    # antes de este cambio: un aviso de que ha empezado es mejor que nada, sin
    # complicar la tool con un segundo hilo leyendo el fichero de log en vivo.
    progress.report(f"Compilando {proyecto} con Unity {version} (puede tardar varios minutos)...")

    code, out = run_process(
        [
            editor,
            "-batchmode",
            "-quit",
            "-nographics",
            "-projectPath", str(root),
            "-executeMethod", metodo,
            "-logFile", str(log_file),
        ],
        timeout=1800,
    )

    log_txt = ""
    if log_file.exists():
        log_txt = log_file.read_text(encoding="utf-8", errors="replace")

    estado = "OK" if code == 0 else f"FALLO (codigo {code})"
    cuerpo = tail(log_txt) if log_txt else tail(out)
    return f"unity_build {proyecto} :: {metodo} ({version}) -> {estado}\n\n{cuerpo}"
