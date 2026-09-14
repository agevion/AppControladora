"""Se asegura de que Tailscale este levantado antes de arrancar el servidor.

En Windows, el estado de sesion de Tailscale queda atado a la sesion de
escritorio interactiva salvo que actives "Ejecutar sin supervision" en la
bandeja del sistema. Esto es una red de seguridad complementaria a eso: si
alguna vez el PC arranca y Tailscale no se ha reconectado solo, este chequeo
lo reactiva sin que haya que ir a la bandeja a mano.

Nunca debe impedir que el servidor arranque: en LAN el servicio funciona
igual sin Tailscale, asi que cualquier fallo aqui es solo un aviso.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

_CANDIDATES = [
    r"C:\Program Files\Tailscale\tailscale.exe",
    r"C:\Program Files (x86)\Tailscale\tailscale.exe",
]


def _find_exe() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    for c in _CANDIDATES:
        if Path(c).exists():
            return c
    return None


def ensure_up(timeout: float = 8.0) -> str:
    exe = _find_exe()
    if not exe:
        return "tailscale: no instalado (omitido)"

    try:
        status = subprocess.run(
            [exe, "status", "--json"], capture_output=True, text=True, timeout=timeout
        )
        data = json.loads(status.stdout or "{}")
        state = data.get("BackendState", "?")
    except Exception as e:
        return f"tailscale: no se pudo consultar el estado ({e})"

    if state == "Running":
        ips = data.get("Self", {}).get("TailscaleIPs") or ["?"]
        return f"tailscale: activo ({ips[0]})"

    if state == "NeedsLogin":
        return (
            "tailscale: requiere iniciar sesion. "
            "Bandeja del sistema -> Tailscale -> Preferencias -> Ejecutar sin supervision."
        )

    try:
        subprocess.run([exe, "up"], capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        return f"tailscale: estado '{state}', fallo al reactivar ({e})"

    return f"tailscale: estado era '{state}', se ha intentado reactivar"
