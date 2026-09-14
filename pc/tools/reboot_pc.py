"""Reinicia el PC, dejando el arranque de AppControladora listo para volver solo.

CONFIRM = True: el movil pide Permitir/Denegar antes de que corra nada (igual
que run_shell, ARQUITECTURA.md seccion 9). Esta es de las pocas tools que de
verdad puede dejarte sin poder hablarle al PC durante un rato: por eso da
margen antes de reiniciar (por defecto 15s) y existe `cancel_shutdown` para
arrepentirse dentro de ese margen.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

SPEC = {
    "name": "reboot_pc",
    "description": (
        "Reinicia el ordenador. Antes de reiniciar, asegura una tarea programada que "
        "vuelve a lanzar arrancar.bat en cuanto se inicie sesion en Windows, para que "
        "el servicio quede en pie solo. Pide confirmacion en el movil antes de ejecutarse."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "segundos": {
                "type": "integer",
                "description": "Margen antes de reiniciar de verdad, para poder cancelar con cancel_shutdown. 15 por defecto.",
            },
        },
        "required": [],
    },
}

CONFIRM = True

ARRANCAR_BAT = Path(__file__).resolve().parent.parent / "arrancar.bat"
TASK_NAME = "AppControladoraArranque"


def _asegurar_tarea_arranque() -> str:
    """Tarea 'al iniciar sesion' que relanza arrancar.bat. /RL LIMITED: no pide admin.

    Ojo: se dispara cuando alguien inicia sesion en Windows, no en el instante
    del POST. Sin sesion automatica (autologin) tras el reinicio, el PC se
    queda esperando en la pantalla de login hasta que alguien la abra -- misma
    limitacion que ya tiene Tailscale sin el modo "Ejecutar sin supervision"
    (ARQUITECTURA.md seccion 4.1 / README "Pendiente de configurar a mano").
    """
    if not ARRANCAR_BAT.is_file():
        return f"aviso: no encuentro {ARRANCAR_BAT}, no arme el arranque automatico"

    cmd = [
        "schtasks", "/Create", "/F",
        "/SC", "ONLOGON",
        "/TN", TASK_NAME,
        "/TR", f'"{ARRANCAR_BAT}"',
        "/RL", "LIMITED",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except Exception as e:
        return f"aviso: no pude asegurar el arranque automatico ({type(e).__name__}: {e})"

    if proc.returncode != 0:
        detalle = proc.stderr.strip() or proc.stdout.strip()
        return f"aviso: no pude asegurar el arranque automatico ({detalle})"
    return "arranque automatico al iniciar sesion: listo"


def run(segundos: int = 15) -> str:
    aviso = _asegurar_tarea_arranque()
    subprocess.run(
        ["shutdown", "/r", "/t", str(segundos), "/c", "AppControladora: reinicio pedido desde el movil"],
        timeout=10,
    )
    return f"{aviso}\nReiniciando en {segundos}s. Para cancelar ahora mismo: cancel_shutdown."
