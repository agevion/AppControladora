"""Cerebro C: la Terminal. SIN LLM. NO es un chat con una IA.

Esto NO habla con ningun modelo. El texto que llega ES el comando, tal cual lo
escribio Ale en la ventana Terminal del movil, y se ejecuta en el PC con
PRIVILEGIOS DE ADMINISTRADOR (via controladora/elevate.py). Lo que se devuelve es
la salida cruda del comando, como en una consola -- ni resumen, ni "te explico",
ni la IA local de por medio.

Por que NO pasa por la tarjeta de permiso (a diferencia de run_shell): la tarjeta
existe para que TU apruebes lo que PROPONE un LLM, en quien no te fias. Aqui no
propone nadie: el comando lo tecleas tu, asi que darle a Enviar ya es ejecutarlo,
igual que pulsar Enter en una terminal. La frontera de seguridad sigue siendo
mTLS + token (ARQUITECTURA.md seccion 9).

Sesion con estado: se recuerda el directorio actual entre comandos, por shell, de
modo que un `cd` persiste para el siguiente comando -- como en una terminal real
y no como comandos sueltos. El helper elevado corre cada comando de una pasada
(elevate.py), asi que el cwd se lleva a mano: se entra en el directorio guardado,
se ejecuta, y se lee donde quedo para la proxima. (Variables de entorno de sesion
NO persisten: eso pediria un proceso vivo permanente y elevado, que es justo lo
que la elevacion de una-pasada evita a proposito.)
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, AsyncIterator

import asyncio

from . import elevate

log = logging.getLogger("controladora.terminal")

# Un comando de terminal puede tardar (una descarga, un build a mano...).
TIMEOUT = 900

SHELLS = {"powershell", "cmd"}

# El directorio actual de cada shell, recordado entre comandos. None = aun no se
# sabe (primer comando): se ejecuta donde arranque el helper y de ahi se aprende.
_cwd: dict[str, str | None] = {"powershell": None, "cmd": None}


def _etiqueta(shell: str) -> str:
    return "cmd" if shell == "cmd" else "PowerShell"


def _envolver(comando: str, shell: str, cwd: str | None, marca: str) -> str:
    """Envuelve el comando del usuario para (1) entrar en el cwd guardado y (2)
    imprimir al final una linea con la marca y el directorio en el que quedo, para
    poder recordarlo. Se parsea luego en _partir()."""
    if shell == "cmd":
        partes = []
        if cwd:
            partes.append(f'cd /d "{cwd}"')
        partes.append(comando)
        # `cd` sin args imprime el directorio actual en su propia linea: asi se
        # captura el cwd DESPUES de que el comando del usuario haya podido cambiarlo
        # (%CD% no vale: cmd lo expande al parsear, antes de ejecutar el cd).
        partes.append(f"echo {marca}")
        partes.append("cd")
        return " & ".join(partes)

    # PowerShell: -Command acepta varias sentencias separadas por saltos de linea.
    lineas = []
    if cwd:
        lineas.append(f"Set-Location -LiteralPath '{cwd}'")
    lineas.append(comando)
    lineas.append(f'Write-Output "{marca} $((Get-Location).Path)"')
    return "\n".join(lineas)


def _partir(salida: str, shell: str, marca: str) -> tuple[str, str | None]:
    """Separa la salida visible del comando del cwd que se aprendio al final.

    Devuelve (salida_limpia, nuevo_cwd|None). Si no aparece la marca (el comando
    reventó antes, o el shell abortó), se devuelve el cwd como None y no se
    actualiza: mejor conservar el directorio viejo que perderlo.
    """
    lineas = salida.splitlines()
    idx = next((i for i, l in enumerate(lineas) if marca in l), None)
    if idx is None:
        return salida.rstrip(), None

    if shell == "cmd":
        # marca en su linea; el cwd es la linea siguiente (la que imprimio `cd`).
        nuevo = lineas[idx + 1].strip() if idx + 1 < len(lineas) else None
        visibles = lineas[:idx]
    else:
        # "marca C:\ruta\actual" en la misma linea.
        resto = lineas[idx].split(marca, 1)[1].strip()
        nuevo = resto or None
        visibles = lineas[:idx]

    return "\n".join(visibles).rstrip(), (nuevo or None)


async def chat(text: str, shell: str = "powershell") -> AsyncIterator[dict[str, Any]]:
    """Ejecuta `text` como comando elevado y emite el resultado crudo.

    Mismo contrato de eventos que los otros cerebros (ver brain_local.chat), pero
    aqui solo se emite `text` (y `error` si el ayudante admin no esta instalado):
    no hay tools, ni permisos, ni streaming palabra a palabra.
    """
    comando = text.strip()
    if not comando:
        return

    shell = shell.lower() if shell.lower() in SHELLS else "powershell"
    cwd = _cwd[shell]
    log.warning("terminal [%s] ADMIN en %s: %s", shell, cwd or "(inicial)", comando[:120])

    marca = f"__CWD_{uuid.uuid4().hex}__"
    envuelto = _envolver(comando, shell, cwd, marca)

    try:
        codigo, salida, elevado = await asyncio.to_thread(
            elevate.run, envuelto, TIMEOUT, shell
        )
    except elevate.NoInstalado as e:
        yield {"kind": "error", "text": str(e)}
        return

    limpia, nuevo_cwd = _partir(salida, shell, marca)
    if nuevo_cwd:
        _cwd[shell] = nuevo_cwd

    # Prompt tipo consola: el directorio y el comando que se tecleo, y debajo su
    # salida cruda. Nada de "-> OK": una terminal no comenta lo que hace.
    prompt = f"{cwd or _cwd[shell] or ''}> {comando}".lstrip()
    aviso = "" if elevado else "\n(OJO: el ayudante NO iba elevado. Revisa la tarea ControladoraAdmin.)"
    cuerpo = f"\n{limpia}" if limpia else ""

    yield {"kind": "text", "text": f"{prompt}{cuerpo}{aviso}"}
