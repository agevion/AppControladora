"""Lista los proyectos conocidos."""

from __future__ import annotations

from pathlib import Path

from controladora import paths

SPEC = {
    "name": "list_projects",
    "description": (
        "Lista los proyectos de desarrollo conocidos, con su tipo (gradle o unity) "
        "y su ruta. Usalo si no sabes que nombre de proyecto usar en otras tools."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

CONFIRM = False


def run() -> str:
    projects = paths.projects()
    if not projects:
        return "No hay proyectos configurados en paths.json"

    lineas = []
    for nombre, p in sorted(projects.items()):
        existe = "" if Path(p["path"]).is_dir() else "  [RUTA NO EXISTE]"
        extra = f" {p['unity_version']}" if p.get("unity_version") else ""
        lineas.append(f"{nombre}  ({p['type']}{extra})  {p.get('descripcion', '')}{existe}")

    return "\n".join(lineas)
