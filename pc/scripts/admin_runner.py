"""El lado elevado: lo lanza la tarea `ControladoraAdmin`, no lo llames tu.

Lee `pc/.admin/request.json`, ejecuta ese comando con PowerShell y deja la salida
en `pc/.admin/result.json`. Corre CON PRIVILEGIOS DE ADMINISTRADOR: todo lo que
llega aqui ya lo aprobo el usuario en el movil (ver controladora/elevate.py y
ARQUITECTURA.md seccion 9).

Es de una sola pasada a proposito -- una peticion, se ejecuta, se muere. No hay
ningun proceso elevado escuchando permanentemente: cuanto menos tiempo este vivo
algo con privilegios, mejor.
"""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
from pathlib import Path

SPOOL = Path(__file__).resolve().parent.parent / ".admin"
REQUEST = SPOOL / "request.json"
RESULT = SPOOL / "result.json"
TMP = SPOOL / "result.tmp"


def _elevado() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _responder(rid: str, code: int, salida: str) -> None:
    # Se escribe aparte y se renombra: un rename en el mismo volumen es atomico,
    # asi que quien lee al otro lado nunca puede pillar medio JSON.
    TMP.write_text(
        json.dumps({"id": rid, "code": code, "salida": salida, "elevado": _elevado()}),
        encoding="utf-8",
    )
    TMP.replace(RESULT)


def main() -> int:
    try:
        peticion = json.loads(REQUEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        # Sin peticion legible no hay a quien contestar (no se sabe ni el id).
        print(f"admin_runner: peticion ilegible: {e}", file=sys.stderr)
        return 1

    rid = str(peticion.get("id") or "")
    comando = str(peticion.get("comando") or "")
    timeout = float(peticion.get("timeout") or 600)
    # "powershell" (por defecto) o "cmd". Lo elige la ventana Terminal del movil;
    # run_shell y el resto no lo mandan y caen en PowerShell, como siempre.
    shell = str(peticion.get("shell") or "powershell").lower()

    if not rid or not comando:
        return 1

    # Se borra ya: si esto reventara a media ejecucion, un disparo posterior de la
    # tarea no debe volver a ejecutar el mismo comando administrativo por su cuenta.
    REQUEST.unlink(missing_ok=True)

    # cmd via fichero .bat, NO via ["cmd","/c",comando]: pasar un comando con
    # comillas por argv hace que Python (list2cmdline) las escape como \" y cmd.exe
    # las interpreta mal -- un `echo "hola"` sale como \"hola\" y un `cd /d "ruta"`
    # con comillas revienta. Un .bat lleva el comando TAL CUAL, sin que nadie lo
    # reescriba. `chcp 65001` deja la salida en UTF-8, que es lo que se decodifica
    # abajo. PowerShell no tiene este problema (parsea su propio -Command), asi que
    # sigue por argv como siempre.
    batfile = None
    if shell == "cmd":
        batfile = SPOOL / f"cmd_{rid}.bat"
        batfile.write_text(f"@echo off\r\nchcp 65001 >nul\r\n{comando}\r\n", encoding="utf-8")
        argv = ["cmd", "/c", str(batfile)]
    else:
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", comando]

    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        _responder(rid, 124, f"TIMEOUT: el comando no termino en {timeout:.0f}s")
        return 0
    except Exception as e:  # el ayudante NUNCA debe morir sin contestar
        _responder(rid, 1, f"El ayudante de administrador fallo: {type(e).__name__}: {e}")
        return 0
    finally:
        if batfile is not None:
            try:
                batfile.unlink(missing_ok=True)
            except OSError:
                pass

    _responder(rid, proc.returncode, (proc.stdout or "") + (proc.stderr or ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
