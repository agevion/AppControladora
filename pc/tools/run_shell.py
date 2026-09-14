"""Ejecuta un comando arbitrario. LA VIA DE ESCAPE.

CONFIRM = True es lo unico que separa esto de "un 8B con shell libre en tu PC".
Un modelo de 8B se deja convencer de cualquier cosa y es justo el que esta detras
de una caja de chat expuesta. Que el Si/No lo des tu en el movil es la frontera
de seguridad entera (ARQUITECTURA.md seccion 9).

NO quites CONFIRM de aqui. Si algo se hace a menudo, merece su propia tool con
parametros fijos, que es mas seguro Y mas comodo que confirmar cada vez -- y por
eso la tarjeta del movil tiene un tercer boton, "Guardar", que hace justo eso sin
gastar tokens de Claude Code (ver controladora/toolgen.py).

Ojo con el formato de salida: `toolgen.command_succeeded` busca el "-> OK" de
abajo para no guardar como tool un comando que fallo. Si cambias el formato,
cambia tambien toolgen.OK_MARK.
"""

from __future__ import annotations

import subprocess

from _util import tail
from controladora import elevate

# Un comando normal no deberia tardar tanto, pero 120s se quedaba corto de verdad:
# copiar una carpeta gorda o descomprimir algo se pasaba y moria a medias, sin que
# el usuario tuviera forma de saber que habia sido el reloj y no el comando.
TIMEOUT = 300

# Los administrativos van aparte porque son otra cosa: un `winget install` con
# descarga incluida se come los 300 sin despeinarse.
TIMEOUT_ADMIN = 900

SPEC = {
    "name": "run_shell",
    "description": (
        "Ejecuta un comando de PowerShell en el PC. Usalo cuando no haya una tool "
        "especifica para lo que te piden PERO sepas hacerlo con un comando de PowerShell "
        "(ver procesos, espacio en disco, servicios, red, ficheros, abrir programas...). "
        "Si ya existe una tool que lo hace, usa esa. El usuario aprueba el comando en el "
        "movil antes de que corra, y puede guardarlo como tool permanente."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "comando": {"type": "string", "description": "El comando de PowerShell a ejecutar"},
            "motivo": {
                "type": "string",
                "description": "Que consigue el comando, en una linea. Lo lee el usuario para decidir si aprueba.",
            },
            "admin": {
                "type": "boolean",
                "description": (
                    "Ponlo a true SOLO si el comando necesita permisos de administrador: "
                    "instalar o desinstalar programas, servicios de Windows, HKLM del "
                    "registro, drivers, cambiar la configuracion del sistema, o tocar "
                    "ficheros de Archivos de programa o Windows. Por defecto false. "
                    "Al usuario le sale una tarjeta roja avisando de que va como "
                    "administrador. Si un comando normal falla con 'Access denied' o "
                    "'Acceso denegado', reintentalo con admin=true."
                ),
            },
            "nombre_tool": {
                "type": "string",
                "description": (
                    "Nombre en snake_case por si el usuario quiere guardar esto como tool "
                    "permanente y reutilizable (ej: 'listar_procesos'). Proponlo siempre que "
                    "el comando sea util mas de una vez tal cual, sin cambiarle nada. "
                    "NO lo propongas si admin es true: eso no se puede guardar."
                ),
            },
        },
        "required": ["comando", "motivo"],
    },
}

CONFIRM = True


def _normal(comando: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", comando],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return 124, f"TIMEOUT: el comando no termino en {TIMEOUT}s"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def run(comando: str, motivo: str = "", nombre_tool: str = "", admin: bool = False) -> str:
    # nombre_tool no se usa aqui: solo viaja al movil como sugerencia para el
    # boton "Guardar". Se acepta para que el registry no lo rechace por firma.
    if admin:
        try:
            codigo, salida, elevado = elevate.run(comando, timeout=TIMEOUT_ADMIN)
        except elevate.NoInstalado as e:
            return str(e)
        # Si la tarea existiera pero corriera sin privilegios, el comando fallaria
        # por permisos y el motivo real quedaria escondido detras de un "Access
        # denied" indistinguible de cualquier otro. Mejor decirlo a la cara.
        aviso = "" if elevado else "\n(OJO: el ayudante NO iba elevado. Revisa la tarea ControladoraAdmin.)"
        estado = "OK" if codigo == 0 else f"codigo {codigo}"
        return f"$ [ADMIN] {comando}\n-> {estado}{aviso}\n\n{tail(salida)}"

    codigo, salida = _normal(comando)
    estado = "OK" if codigo == 0 else f"codigo {codigo}"
    return f"$ {comando}\n-> {estado}\n\n{tail(salida)}"
