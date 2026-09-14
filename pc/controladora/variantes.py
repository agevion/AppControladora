"""Que tarea de Gradle hay que lanzar para cada proyecto, sin adivinar.

El motivo de existir: durante meses TODO lo que salia de aqui era `assembleDebug`
-- las dos tools lo tenian como valor por defecto y los botones de Acciones
rapidas ni siquiera mandaban el parametro. Un APK de debug lleva el flag
`debuggable`, que apaga optimizaciones de ART y hace la app notablemente mas
lenta que la misma app en release. O sea: se estaban instalando en el movil
builds peores que las reales, siempre, sin que nadie lo pidiera.

Lo obvio seria cambiar el defecto a `assembleRelease` y ya, pero no vale: un
release SIN signingConfig sale sin firmar, y un APK sin firmar el movil lo
rechaza con "parece que el paquete no es valido" (ver apk.py). Cambiar el
defecto a ciegas convertiria "va lento" en "no se instala", que es peor.

Asi que aqui se mira el build.gradle del modulo de aplicacion ANTES de compilar
y se decide con lo que hay escrito:

  - modulo Android con `signingConfig` dentro de `buildTypes { release { ... } }`
    -> assembleRelease. (Da igual que firme con la clave de debug, como hace la
    plantilla de Flutter: lo que importa es que el APK salga firmado y que el
    codigo se compile en modo release.)
  - modulo Android sin eso -> assembleDebug, y se explica por que, porque el
    usuario merece saber que esa app va en modo lento y como arreglarlo.
  - no es un modulo Android (los mods de Java: no hay assembleDebug ni
    assembleRelease) -> `build`, que es la tarea que esos proyectos si tienen.

Esto es una lectura de texto, no un parser de Gradle, asi que puede equivocarse
por optimismo. Por eso no es la ultima palabra: quien decide de verdad si un APK
se puede mandar al movil es apk.is_signed(), que mira el fichero ya compilado.
Aqui se decide que compilar; alli se comprueba que ha salido.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, NamedTuple

from controladora import paths

# El plugin que convierte un modulo en una app instalable. Un modulo de libreria
# (`com.android.library`) genera un .aar y no tiene assembleDebug que mandar.
APP_PLUGIN = re.compile(r"com\.android\.application|alias\(libs\.plugins\.android\.application\)")

# Un `signingConfig ... ` a secas basta: si esta ahi, el release sale firmado.
SIGNING = re.compile(r"\bsigningConfig\b")


class Variante(NamedTuple):
    """Que compilar y por que. `motivo` va tal cual a la respuesta de la tool."""

    tarea: str
    motivo: str


def _modulo_app(root: Path) -> Path | None:
    """El build.gradle del modulo que genera el APK.

    `app/` primero porque es la convencion y evita recorrer el disco. Si no esta
    (algun proyecto con el modulo llamado de otra forma), se buscan los
    build.gradle de primer nivel y se coge el que declare el plugin de
    aplicacion. No se baja mas: un modulo de app anidado tres niveles no existe
    en ningun proyecto de paths.json y recorrer un build/ entero cuesta caro.
    """
    candidatos = [root / "app" / "build.gradle.kts", root / "app" / "build.gradle"]
    candidatos += sorted(root.glob("*/build.gradle.kts")) + sorted(root.glob("*/build.gradle"))
    for f in candidatos:
        try:
            if f.is_file() and APP_PLUGIN.search(f.read_text(encoding="utf-8", errors="ignore")):
                return f
        except OSError:
            continue
    return None


def _bloque_release(texto: str) -> str | None:
    """El contenido de `release { ... }` dentro de `buildTypes`, contando llaves.

    Con una regex sola no se puede: el bloque tiene llaves anidadas dentro
    (`optimization { }`, `proguardFiles(...)`) y `.*?` cortaria en la primera
    llave de cierre, justo antes de la linea del signingConfig.
    """
    bt = re.search(r"\bbuildTypes\s*\{", texto)
    if not bt:
        return None

    # Fin del bloque buildTypes, para no cazar un `release {` de otro sitio
    # (por ejemplo `compileSdk { version = release(36) { ... } }` mas arriba).
    i, nivel = bt.end(), 1
    while i < len(texto) and nivel:
        nivel += (texto[i] == "{") - (texto[i] == "}")
        i += 1
    dentro = texto[bt.end() : i - 1]

    rel = re.search(r"\brelease\s*\{", dentro) or re.search(r"getByName\(\s*[\"']release[\"']\s*\)\s*\{", dentro)
    if not rel:
        return None

    j, nivel = rel.end(), 1
    while j < len(texto) and nivel:
        nivel += (dentro[j] == "{") - (dentro[j] == "}")
        j += 1
    return dentro[rel.end() : j - 1]


def para(project_entry: dict[str, Any]) -> Variante:
    """La tarea que hay que lanzar para este proyecto, y por que esa."""
    root = Path(project_entry.get("path", ""))
    modulo = _modulo_app(root) if root.is_dir() else None

    if modulo is None:
        return Variante(
            "build",
            "no es un modulo de aplicacion Android (no genera APK): se usa la tarea 'build'.",
        )

    try:
        texto = modulo.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        texto = ""

    bloque = _bloque_release(texto)
    if bloque is not None and SIGNING.search(bloque):
        return Variante("assembleRelease", "")

    return Variante(
        "assembleDebug",
        f"OJO: build de DEBUG (va mas lenta que la real). {modulo.parent.name}/"
        f"{modulo.name} no tiene signingConfig en buildTypes.release, asi que su "
        "assembleRelease saldria sin firmar y el movil lo rechazaria. Para poder "
        "mandarte releases de este proyecto hay que darle un keystore.",
    )


def por_nombre(proyecto: str) -> Variante | None:
    p = paths.project(proyecto)
    return para(p) if p else None
