"""Arranca TODO lo que el sistema necesita, en orden, con un solo comando.

    python run.py          (o doble clic en arrancar.bat)

Levanta Tailscale si hace falta, levanta Ollama si hace falta, carga el registry
de tools y arranca el servicio con mTLS. Nada de esto hay que hacerlo a mano ni
en un orden concreto: si ya esta levantado, se detecta y se omite.

`ssl_cert_reqs=CERT_REQUIRED` + `ssl_ca_certs=ca.crt` es lo que hace que el puerto
no responda a nadie que no presente un certificado firmado por nuestra CA: el
handshake TLS se corta antes de que exista una peticion HTTP que atacar.

Principio: los preparativos avisan, no bloquean. Lo unico que impide arrancar es
que falte algo sin lo cual el servicio no puede existir (certificados, o el puerto
ya ocupado). Que Ollama no este es un aviso: el chat de Claude Code funciona igual.

Sin rastro al cerrar (ver controladora/winjob.py): este proceso se mete en un Job
de Windows con KILL_ON_JOB_CLOSE nada mas arrancar, ANTES de lanzar nada. Todo lo
que se lance despues -- Ollama, un `claude.exe` del Agent SDK, un `gradlew.bat` a
medias -- hereda ese job. Si este proceso muere, sea como sea (Ctrl+C, la X, un
crash, un taskkill), el kernel mata a todos sus hijos en el mismo instante. No es
opcional ni depende de que nuestro codigo de limpieza llegue a ejecutarse.

Tailscale es la excepcion a proposito: NO se apaga al cerrar. Es un servicio de
VPN de todo el sistema, pensado para estar siempre activo (ARQUITECTURA.md
seccion 4.1) y usado por otros proyectos ademas de este (la impresora 3D).
Apagarlo aqui tendria efectos fuera de esta app.
"""

from __future__ import annotations

import logging
import socket
import ssl

import uvicorn

from controladora import ollama, sensores, tailscale, winjob
from controladora.config import load
from controladora.registry import Registry


def _puerto_ocupado(port: int, host: str = "127.0.0.1") -> bool:
    """Si ya hay algo escuchando ahi, casi siempre eres tu mismo arrancando dos veces.

    Sin esto, uvicorn muere con un WinError 10048 que no dice nada de eso.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def di(texto: str) -> None:
    """print con flush.

    Sin el flush, redirigir la salida a un fichero (`run.py > server.out.log`)
    esconde TODO este resumen hasta que el proceso muera: Python pasa a buffer de
    bloque cuando la salida no es una consola, y un servidor no termina nunca.
    Justo el log que quieres leer cuando algo no arranca seria el que no verias.
    """
    print(texto, flush=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s")

    di("== Controladora ==")
    cfg = load()  # revienta con un mensaje claro si faltan certificados

    if _puerto_ocupado(cfg.port):
        # Dos trampas evitadas en este mensaje:
        # - Nada de sugerir un curl al /health: el curl de Windows usa schannel y
        #   no sabe leer certificados PEM de cliente, asi que el mTLS le corta el
        #   handshake SIEMPRE. Pareceria el servidor caido sin estarlo.
        # - Nada de $_ : esto se pega en PowerShell, y PowerShell se lo comeria.
        raise SystemExit(
            f"El puerto {cfg.port} ya esta ocupado: seguramente el servidor ya esta arrancado.\n"
            f"Mira quien lo tiene (en PowerShell):\n"
            f"  Get-Process -Id (Get-NetTCPConnection -LocalPort {cfg.port} -State Listen).OwningProcess"
        )

    # Antes de lanzar NADA: si esto falla, seguimos igual (avisos no bloquean),
    # pero entonces nada de lo que arranque despues tiene la garantia de morir
    # solo. Se intenta lo antes posible para que la ventana sin proteccion sea
    # la minima.
    job = winjob.KillOnCloseJob()
    try:
        job.protect_self()
        di("limpieza: este proceso y todo lo que lance moriran juntos, pase lo que pase")
    except winjob.JobError as e:
        di(f"AVISO: no se pudo garantizar la limpieza automatica ({e}). Puede quedar rastro si esto se cierra a la fuerza.")

    # Los dos preparativos son lentos (segundos) y ninguno bloquea el arranque.
    di(tailscale.ensure_up())

    mensaje_ollama, ollama_pid = ollama.ensure_up()
    di(mensaje_ollama)
    if ollama_pid is not None:
        # Red de seguridad extra (ver winjob.py): si protect_self() de arriba
        # fallo, esto es un segundo intento, esta vez solo para Ollama.
        try:
            job.protect_pid(ollama_pid)
        except winjob.JobError as e:
            di(f"AVISO: Ollama (pid {ollama_pid}) puede quedar huerfano si esto se cierra a la fuerza ({e})")

    # Los sensores van despues de meterse en el job aunque NO puedan usarlo: LHM
    # necesita ir elevado y un proceso elevado no es hijo nuestro, asi que no
    # hereda el job (ver controladora/sensores.py). De su muerte se encarga un
    # supervisor que vigila el PID de este proceso.
    di(sensores.ensure_up())

    # Se carga aqui solo para poder avisar de tools rotas ANTES de que las pidas
    # desde el gym. El servidor carga su propio registry al importarse.
    registro = Registry()
    registro.load()
    di(f"tools: {len(registro.names())} cargadas")
    for fichero, error in registro.errors().items():
        di(f"  AVISO: {fichero} no carga -> {error}")

    di(f"escuchando en https://{cfg.host}:{cfg.port}  (mTLS obligatorio)")
    di(f"SAN del certificado: {', '.join(cfg.san)}")
    di(
        "Ctrl+C, cerrar esta ventana, o matar el proceso: Ollama y LibreHardwareMonitor se apagan con el. "
        "Tailscale sigue (es un servicio del sistema, no de esta app)."
    )

    uvicorn.run(
        "controladora.server:app",
        host=cfg.host,
        port=cfg.port,
        ssl_certfile=str(cfg.server_crt),
        ssl_keyfile=str(cfg.server_key),
        ssl_ca_certs=str(cfg.ca_crt),
        ssl_cert_reqs=ssl.CERT_REQUIRED,
        log_level="info",
    )


if __name__ == "__main__":
    main()
