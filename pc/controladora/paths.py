"""Acceso a paths.json: rutas absolutas de apps, binarios y proyectos.

El PATH de Windows aqui no tiene java, adb, gradle ni node, asi que TODO se
resuelve por ruta absoluta. Nunca dependas del PATH en una tool.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PC_DIR = Path(__file__).resolve().parent.parent
PATHS_FILE = PC_DIR / "paths.json"


def _load() -> dict[str, Any]:
    return json.loads(PATHS_FILE.read_text(encoding="utf-8"))


def all_paths() -> dict[str, Any]:
    """Se relee en cada llamada: asi editar paths.json surte efecto sin reiniciar."""
    return _load()


def app(name: str) -> str | None:
    entry = _load().get("apps", {}).get(name)
    return entry.get("exe") if entry else None


def apps() -> dict[str, Any]:
    return _load().get("apps", {})


def binary(name: str) -> str | None:
    return _load().get("bin", {}).get(name)


def projects() -> dict[str, Any]:
    return _load().get("projects", {})


def project(name: str) -> dict[str, Any] | None:
    return _load().get("projects", {}).get(name)


def apk_search_root(project_entry: dict[str, Any]) -> Path:
    """Donde buscar el APK generado.

    Normalmente es la propia carpeta del proyecto. Pero en un modulo android de
    un proyecto Flutter, Flutter redirige el buildDir de Gradle a la raiz del
    proyecto Flutter (fuera de android/), asi que ahi hace falta el override
    explicito `apk_root` en paths.json en vez de adivinar por convencion.
    """
    override = project_entry.get("apk_root")
    return Path(override) if override else Path(project_entry["path"])


def _variant_from_tarea(tarea: str | None) -> str | None:
    """'assembleDebug' -> 'debug', 'assembleRelease' -> 'release'. None si no se puede saber."""
    if not tarea or not tarea.lower().startswith("assemble"):
        return None
    return tarea[len("assemble"):].lower() or None


def latest_apk(project_entry: dict[str, Any], tarea: str | None = None) -> Path | None:
    """El APK ya compilado mas reciente para este proyecto, o None si no hay ninguno.

    Busca solo dentro de la variante (debug/release) que corresponde a `tarea`, nunca
    mezclando por fecha de archivo: un `assembleRelease` de prueba no debe poder colarse
    como "el mas reciente" y mandarse al movil en vez del debug que realmente se pidio.

    Ojo: esto NO garantiza que el APK sea instalable, solo que es de la variante que
    se pidio. Si la tarea es un `assembleRelease` explicito y el proyecto no tiene
    signingConfig, lo que sale de aqui va sin firmar. Quien decide si se puede mandar
    es controladora/apk.py, que mira la firma del fichero en vez de fiarse del nombre.
    """
    root = apk_search_root(project_entry)
    variant = _variant_from_tarea(tarea)
    pattern = f"**/outputs/apk/{variant}/**/*.apk" if variant else "**/outputs/apk/**/*.apk"
    apks = sorted(root.glob(pattern))
    return max(apks, key=lambda f: f.stat().st_mtime) if apks else None


def unity_editor(version: str) -> str | None:
    return _load().get("unity_editors", {}).get(version)


def ollama() -> dict[str, Any]:
    return _load().get("ollama", {})


def sensores() -> dict[str, Any]:
    """LibreHardwareMonitor: quien lee la temperatura de la CPU.

    Vive aqui y no como constante en un .py porque la ruta la pone winget y lleva
    dentro un hash del paquete: se rompe sola en cuanto LHM se actualice, y
    entonces esto es lo unico que hay que tocar. Ver controladora/sensores.py.
    """
    return _load().get("sensores", {})


def phone() -> dict[str, Any]:
    """IP de Tailscale del movil para adb inalambrico (ver adb_connect.py).

    Vive aqui y no como constante en el .py de la tool a proposito: si el
    movil cambia (se reinstala, es otro telefono), esto es lo unico que hay
    que tocar, sin tocar codigo. Mismo principio que projects/apps/bin.
    """
    return _load().get("phone", {})


def recibidos() -> str | None:
    """Carpeta donde se guardan los ficheros que manda el movil (ver recibidos.py).

    Vive en paths.json y no como constante en el .py por lo de siempre: es una
    ruta de esta maquina y de este usuario. Si no esta, recibidos.py usa
    la carpeta Documentos/ControlaPics.
    """
    valor = _load().get("recibidos")
    return valor if isinstance(valor, str) and valor.strip() else None
