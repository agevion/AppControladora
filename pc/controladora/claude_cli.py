"""Localiza el CLI de Claude Code, que el Agent SDK lanza como subproceso.

Aqui el CLI no esta en el PATH: lo trae empaquetado la app de escritorio en

    %APPDATA%\\Claude\\claude-code\\<version>\\claude.exe

y esa ruta lleva la version dentro, asi que fijarla a mano se rompe en cuanto
Claude Code se actualiza solo. Por eso se busca y se ordena por version de
verdad (2.1.209 > 2.1.99, cosa que un sort de texto se comeria al reves).

No se depende de una sola pista para encontrarlo. La primera version de esto
resolvia la carpeta unicamente con la variable de entorno %APPDATA%, y eso dio
un fallo real y desconcertante: el CLI estaba en su sitio, `find_cli()` lo
encontraba al ejecutarlo a mano, y sin embargo el servidor decia que no existia.
Motivo: el servidor se habia arrancado desde un entorno donde %APPDATA% no
llegaba con el valor de la sesion del usuario, asi que miraba en otro sitio. Una
variable de entorno es una pista, no un hecho: %USERPROFILE%\\AppData\\Roaming y
Path.home() dicen lo mismo por otras vias, y aqui se prueban todas.

Y cuando de verdad no aparece, `describe_search()` cuenta donde ha mirado. Un
"no lo encuentro" sin la lista de sitios es exactamente lo que convirtio esto
en media hora de depuracion a ciegas.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from . import paths


def _version_key(nombre: str) -> tuple[int, ...]:
    """'2.1.209' -> (2, 1, 209). Lo que no sea numero cuenta como 0."""
    partes = re.split(r"[.\-+]", nombre)
    return tuple(int(p) if p.isdigit() else 0 for p in partes)


def _roaming_dirs() -> list[Path]:
    """Candidatas a %APPDATA%, por si la variable no llega o llega mal.

    Las tres vias suelen dar lo mismo; se conservan las tres justamente para los
    casos en que no lo dan. Se deduplica preservando el orden: la variable de
    entorno primero, porque cuando es correcta es la mas fiable de las tres.
    """
    candidatas: list[Path] = []

    appdata = os.environ.get("APPDATA")
    if appdata:
        candidatas.append(Path(appdata))

    perfil = os.environ.get("USERPROFILE")
    if perfil:
        candidatas.append(Path(perfil) / "AppData" / "Roaming")

    try:
        candidatas.append(Path.home() / "AppData" / "Roaming")
    except RuntimeError:
        # Path.home() revienta si no hay ni HOME ni USERPROFILE. No es motivo
        # para tirar la busqueda entera: las otras pistas pueden bastar.
        pass

    vistas: set[str] = set()
    unicas: list[Path] = []
    for c in candidatas:
        clave = str(c).rstrip("\\/").lower()
        if clave not in vistas:
            vistas.add(clave)
            unicas.append(c)
    return unicas


def _packaged_roaming_dirs() -> list[Path]:
    """La app de escritorio como paquete de Windows (MSIX/Store) no escribe en
    %APPDATA%\\Claude directamente: Windows redirige esa escritura a una carpeta
    de paquete aparte, y solo el propio proceso empaquetado ve la ruta normal
    como si existiera de verdad. Un proceso suelto (este servicio) ve la ruta
    sin redirigir, que esta vacia -- por eso hay que mirar aqui tambien.

    Real, no hipotetico: asi es exactamente como se encontro el CLI la primera
    vez que esto fallo con una instalacion via Microsoft Store. La carpeta del
    paquete (algo como "Claude_pzs8sxrjxfjjc") lleva un sufijo que varia por
    instalacion, asi que se buscan todas las que empiecen por "Claude_".
    """
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return []

    packages = Path(local) / "Packages"
    if not packages.is_dir():
        return []

    return [
        d / "LocalCache" / "Roaming"
        for d in packages.iterdir()
        if d.is_dir() and d.name.startswith("Claude_")
    ]


def _bases() -> list[Path]:
    """Carpetas donde puede vivir el CLI, en orden de preferencia."""
    bases = [d / "Claude" / "claude-code" for d in _roaming_dirs()]
    bases += [d / "Claude" / "claude-code" for d in _packaged_roaming_dirs()]

    # El instalador nativo (fuera de la app de escritorio) lo deja aqui, sin
    # carpeta de version. Hoy no esta en este PC, pero si algun dia se instala
    # asi, esto lo encuentra sin tener que volver a tocar el codigo.
    try:
        bases.append(Path.home() / ".local" / "bin")
    except RuntimeError:
        pass

    return bases


def _buscar_en(base: Path) -> str | None:
    if not base.is_dir():
        return None

    # Instalacion sin carpeta de version (instalador nativo).
    directo = base / "claude.exe"
    if directo.exists():
        return str(directo)

    candidatos = [d for d in base.iterdir() if d.is_dir() and (d / "claude.exe").exists()]
    if not candidatos:
        return None

    mas_nueva = max(candidatos, key=lambda d: _version_key(d.name))
    return str(mas_nueva / "claude.exe")


def find_cli() -> str | None:
    """Devuelve la ruta del CLI, o None si no aparece.

    Orden: override explicito en paths.json > PATH > carpetas conocidas.
    """
    override = paths.all_paths().get("bin", {}).get("claude_cli")
    if override and Path(override).exists():
        return override

    en_path = shutil.which("claude")
    if en_path:
        return en_path

    for base in _bases():
        encontrado = _buscar_en(base)
        if encontrado:
            return encontrado

    return None


def describe_search() -> str:
    """Donde se ha mirado y que habia. Para el mensaje de error, no para el flujo normal.

    Se recalcula en vez de recordar lo que hizo find_cli(): esto solo se llama
    cuando algo ya ha fallado, y ahi lo que importa es poder mirar el estado real
    del disco, no un resumen de hace un rato.
    """
    lineas: list[str] = []

    override = paths.all_paths().get("bin", {}).get("claude_cli")
    if override:
        existe = "existe" if Path(override).exists() else "NO existe"
        lineas.append(f"paths.json bin.claude_cli = {override} ({existe})")
    else:
        lineas.append("paths.json bin.claude_cli: sin definir")

    lineas.append(f"PATH: {shutil.which('claude') or 'no hay ningun claude en el PATH'}")
    lineas.append(f"APPDATA = {os.environ.get('APPDATA') or '(sin definir)'}")

    for base in _bases():
        if not base.is_dir():
            lineas.append(f"{base}: no existe")
            continue
        hijos = sorted(d.name for d in base.iterdir() if d.is_dir())
        lineas.append(f"{base}: existe, subcarpetas = {hijos or '(ninguna)'}")

    return "\n".join(lineas)
