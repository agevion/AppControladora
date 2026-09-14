"""Compila un proyecto Gradle llamando a gradlew.bat directamente.

No se pilota el IDE: llamar al build tool es mucho mas fiable que hacer que una
IA busque el boton de Play en una captura de pantalla (ARQUITECTURA.md seccion 5).
"""

from __future__ import annotations

from pathlib import Path

from _util import run_process, tail
from controladora import paths, progress, variantes

SPEC = {
    "name": "build_gradle",
    "description": (
        "Compila un proyecto Android/Java con Gradle. Devuelve si ha ido bien y el "
        "final del log. Tarda entre segundos y varios minutos."
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
                    "elige sola la correcta para ese proyecto (assembleRelease si puede "
                    "firmar, assembleDebug si no, 'build' si no es una app Android). "
                    "Ponla solo si te piden algo concreto: 'assembleDebug' para depurar, "
                    "'clean', 'test'."
                ),
            },
        },
        "required": ["proyecto"],
    },
}

CONFIRM = False


def _entorno(java_home: str) -> dict[str, str]:
    """JAVA_HOME y ANDROID_HOME para Gradle.

    El PATH de esta maquina no tiene java, asi que JAVA_HOME es obligatorio y
    sale del JDK que trae Android Studio (paths.json), sin depender de un Java
    instalado aparte.

    ANDROID_HOME va tambien porque un proyecto cuyo local.properties venga de
    otro ordenador (sdk.dir apuntando a un usuario que aqui no existe) fallaba
    con "SDK location not found" antes de compilar una sola linea. Con esto el
    SDK se encuentra igual, sin tener que arreglar el local.properties de cada
    proyecto a mano.
    """
    env = {"JAVA_HOME": java_home}
    sdk = paths.binary("android_sdk")
    if sdk and Path(sdk).is_dir():
        env["ANDROID_HOME"] = sdk
    return env


def run(proyecto: str, tarea: str | None = None) -> str:
    p = paths.project(proyecto)
    if not p:
        return f"No conozco el proyecto '{proyecto}'. Disponibles: {', '.join(paths.projects())}"

    if p.get("type") != "gradle":
        return f"'{proyecto}' es de tipo '{p.get('type')}', no gradle. Para Unity usa unity_build."

    root = Path(p["path"])
    gradlew = root / "gradlew.bat"
    if not gradlew.exists():
        return f"No hay gradlew.bat en {root}"

    # Sin tarea explicita la elige variantes.py mirando el build.gradle: por
    # defecto release (la app va como va de verdad), debug solo si ese proyecto
    # no puede firmar release. Antes el defecto era assembleDebug a secas y por
    # eso TODO lo que se instalaba en el movil iba en modo lento.
    aviso = ""
    if not tarea:
        elegida = variantes.para(p)
        tarea, aviso = elegida.tarea, elegida.motivo

    java_home = paths.binary("java_home")
    if not java_home or not Path(java_home).is_dir():
        return f"java_home no valido en paths.json: {java_home}"

    progress.report(f"Compilando {proyecto} ({tarea})...")
    code, out = run_process(
        [str(gradlew), tarea, "--no-daemon"],
        cwd=root,
        timeout=900,
        extra_env=_entorno(java_home),
        # Cada linea que Gradle imprime (tareas, warnings) llega en vivo al
        # movil via progress.report -- antes esto era silencio total hasta el
        # resultado final, que en un build de varios minutos parecia un cuelgue.
        stream_progress=True,
    )

    estado = "OK" if code == 0 else f"FALLO (codigo {code})"
    resumen = f"build_gradle {proyecto} :: {tarea} -> {estado}\n\n{tail(out)}"
    if aviso:
        resumen += "\n\n" + aviso

    if code == 0:
        reciente = paths.latest_apk(p, tarea)
        if reciente:
            mb = reciente.stat().st_size / 1024 / 1024
            resumen += f"\n\nAPK generado: {reciente} ({mb:.1f} MB)"

    return resumen
