"""Convierte un run_shell que aprobaste en una tool permanente de pc/tools/.

Es la via barata del bucle de auto-ampliacion (ARQUITECTURA.md seccion 8): para
"ver los procesos" no hace falta gastar tokens de Claude Code escribiendo una
tool. La IA local propone el comando, tu lo lees en el movil, y si le das a
"Guardar" el comando queda congelado en un fichero que el registry ya sabe cargar.

Por que esto NO rompe la frontera de seguridad de la seccion 9:

- El modelo no escribe Python. La plantilla de abajo es fija; el comando entra
  como DATO (repr()), nunca interpolado como codigo. Lo unico que el modelo
  decide es el texto del comando, que es exactamente lo que ya decidia con
  run_shell, y que tu lees antes de aprobar.
- Lo que se guarda es el comando LITERAL que aprobaste, sin parametros. Una tool
  guardada no puede hacer nada distinto de lo que hizo delante de tus ojos.
- Por eso mismo las tools guardadas nacen con CONFIRM = False: ya las aprobaste
  una vez y no pueden variar. Si quieres que vuelva a preguntar, borra el fichero.
"""

from __future__ import annotations

import importlib.util
import re
import unicodedata
from datetime import date
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"

# Un nombre de tool es tambien un nombre de fichero y una clave del registry.
NOMBRE_VALIDO = re.compile(r"^[a-z][a-z0-9_]{2,39}$")

# run_shell marca el exito asi en su salida. No guardamos una tool a partir de un
# comando que fallo: seria congelar un error. Si cambias el formato de salida de
# run_shell, este marcador se rompe (esta anotado alli tambien).
OK_MARK = "-> OK"


class ToolGenError(Exception):
    """No se pudo guardar la tool. El mensaje se le ensena al usuario tal cual."""


_PLANTILLA = '''"""Tool autogenerada el {fecha} a partir de un run_shell aprobado en el movil.

No la escribio un humano ni la escribio un modelo: la plantilla es fija y el
comando de abajo es, literalmente, el que aprobaste. Ver controladora/toolgen.py.

Motivo que dio la IA local: {motivo_doc}

Para quitarla: borra este fichero y dale a "Recargar tools" en el movil.
"""

from __future__ import annotations

import subprocess

from _util import tail

# Marca de "esto lo genero el sistema, no se edito a mano". Sirve para
# distinguirlas de las tools escritas a proposito.
AUTOGEN = True

COMANDO = {comando!r}

SPEC = {{
    "name": {nombre!r},
    "description": {descripcion!r},
    "parameters": {{"type": "object", "properties": {{}}}},
}}

CONFIRM = False


def run() -> str:
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", COMANDO],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return "TIMEOUT: el comando no termino en 120s"

    salida = (proc.stdout or "") + (proc.stderr or "")
    estado = "OK" if proc.returncode == 0 else f"codigo {{proc.returncode}}"
    return f"$ {{COMANDO}}\\n-> {{estado}}\\n\\n{{tail(salida)}}"
'''


def command_succeeded(resultado: str) -> bool:
    """Si el run_shell que se acaba de ejecutar termino bien.

    Lee el formato de salida de run_shell. Es acoplamiento, pero explicito y en
    un solo sitio: preferible a guardar tools que no funcionan.
    """
    return OK_MARK in resultado


def suggest_name(comando: str) -> str:
    """Un nombre razonable a partir del comando, para cuando el modelo no propone.

    `Get-Process | Sort-Object CPU` -> `get_process`. No pretende ser bonito:
    pretende ser valido y reconocible. El usuario puede reescribirlo en el movil.
    """
    primero = comando.strip().split()[0] if comando.strip() else ""
    slug = _slug(primero)
    return slug or "comando_guardado"


def _slug(texto: str) -> str:
    plano = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", plano).strip("_").lower()
    slug = re.sub(r"_+", "_", slug)
    if slug and slug[0].isdigit():
        slug = f"t_{slug}"
    return slug[:40]


def _shadows_import(nombre: str) -> bool:
    """Si `nombre` es un modulo que ya se puede importar, guardarlo lo eclipsaria.

    El registry mete pc/ y pc/tools/ en sys.path (para que las tools importen
    `_util` sin ceremonia), asi que un fichero tools/subprocess.py se convertiria
    en EL `subprocess` de todo lo que se importe despues. Y lo peor es que no
    fallaria aqui: fallaria raro y lejos, la proxima vez que alguien compile algo.
    """
    try:
        return importlib.util.find_spec(nombre) is not None
    except (ImportError, ValueError):
        # find_spec revienta con algunos nombres raros; si no lo sabemos, no lo
        # damos por seguro.
        return True


def _motivo_doc(motivo: str) -> str:
    """Deja el motivo apto para vivir dentro de un docstring de una linea."""
    limpio = " ".join(motivo.split()).replace('"""', "'''").replace("\\", "/")
    return limpio[:200] or "(no dio motivo)"


def save_shell_tool(
    nombre: str,
    comando: str,
    motivo: str = "",
    tools_dir: Path = TOOLS_DIR,
) -> Path:
    """Escribe pc/tools/<nombre>.py. Devuelve la ruta. Lanza ToolGenError si no.

    No recarga el registry: eso lo hace quien llama (el servidor), porque tambien
    tiene que avisar al movil de la lista nueva de tools.
    """
    nombre = _slug(nombre)
    if not NOMBRE_VALIDO.match(nombre):
        raise ToolGenError(
            f"'{nombre}' no vale como nombre: usa minusculas, numeros y _, entre 3 y 40 caracteres."
        )

    if not comando.strip():
        raise ToolGenError("no hay comando que guardar.")

    destino = tools_dir / f"{nombre}.py"
    if destino.exists():
        raise ToolGenError(f"ya existe una tool llamada '{nombre}'. Elige otro nombre.")

    if _shadows_import(nombre):
        raise ToolGenError(
            f"'{nombre}' es el nombre de un modulo de Python y taparia al de verdad. Elige otro."
        )

    motivo_limpio = " ".join(motivo.split())
    descripcion = (
        f"{motivo_limpio} Ejecuta siempre este comando fijo de PowerShell: {comando}"
        if motivo_limpio
        else f"Ejecuta siempre este comando fijo de PowerShell: {comando}"
    )

    codigo = _PLANTILLA.format(
        fecha=date.today().isoformat(),
        motivo_doc=_motivo_doc(motivo),
        comando=comando,
        nombre=nombre,
        descripcion=descripcion[:500],
    )

    tools_dir.mkdir(parents=True, exist_ok=True)
    destino.write_text(codigo, encoding="utf-8")
    return destino
