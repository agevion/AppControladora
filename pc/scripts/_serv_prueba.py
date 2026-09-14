"""Instancia de prueba del servicio en otro puerto (solo para los tests).

    python scripts/_serv_prueba.py [puerto]

Existe para poder probar cambios del servidor sin tumbar la instancia que este
atendiendo al movil en ese momento. Empieza por "_" para que el registry de
tools no lo mire: no es una tool ni una prueba, es un arrancador.
"""

from __future__ import annotations

import ssl
import sys
from pathlib import Path

import uvicorn

PC_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PC_DIR))

CERTS = PC_DIR / "certs"

if __name__ == "__main__":
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else 8444
    uvicorn.run(
        "controladora.server:app",
        host="127.0.0.1",
        port=puerto,
        ssl_certfile=str(CERTS / "server.crt"),
        ssl_keyfile=str(CERTS / "server.key"),
        ssl_ca_certs=str(CERTS / "ca.crt"),
        ssl_cert_reqs=ssl.CERT_REQUIRED,
        log_level="warning",
    )
