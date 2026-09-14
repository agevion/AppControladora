"""Todo lo que toca UIA ocurre en UN unico hilo. No es una optimizacion.

Dos razones, y las dos muerden si se ignoran:

1. **COM.** Un puntero a una interfaz COM pertenece al apartamento del hilo que
   lo creo. Usarlo desde otro hilo sin marshalling es comportamiento indefinido:
   a veces va, a veces devuelve basura, a veces revienta el proceso entero. El
   servidor es asyncio y `asyncio.to_thread` reparte el trabajo entre hilos
   cualesquiera del pool, asi que "el hilo que toco" cambiaria de una llamada a
   la siguiente. Aqui se fuerza a que sea siempre el mismo.

2. **El arbol de accesibilidad se apaga.** Chromium solo lo mantiene encendido
   mientras hay un cliente UIA vivo. Si el cliente se creara y se tirara en cada
   consulta, la siguiente volveria a ver la ventana pelada (14 nodos en vez de
   ~990) y habria que esperar otra vez a que se llene. El cliente vive en este
   hilo y dura lo que dure el proceso.

Se inicializa COM como MTA (`COINIT_MULTITHREADED`) y no como STA a proposito:
un apartamento STA exige una bomba de mensajes en el hilo, y este hilo no tiene
ninguna -- se pasa la vida bloqueado esperando trabajo en la cola. UIA funciona
en MTA sin bomba.

REGLA: ningun objeto COM sale de aqui. Las funciones publicas de `uia.py`
devuelven datos planos (cadenas, numeros, dataclasses), nunca elementos. Un
elemento devuelto al hilo del servidor seria justo el bug del punto 1.
"""

from __future__ import annotations

import asyncio
import ctypes
import functools
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

log = logging.getLogger("controladora.appctl.hilo")

COINIT_MULTITHREADED = 0x0

# `comtypes` inicializa COM EN EL MOMENTO DE IMPORTARSE, y por defecto lo hace
# en STA. Como este hilo ya se ha inicializado en MTA, ese import revienta con
# RPC_E_CHANGED_MODE ("no se puede cambiar el modo de subproceso despues de
# establecerlo") y el fallo aparece a tres niveles de distancia, dentro de la
# primera consulta a UIA -- que es donde menos se busca.
#
# `sys.coinit_flags` es la unica forma de decirselo, y tiene que estar puesto
# ANTES del primer import de comtypes en todo el proceso. Por eso va aqui, al
# cargar el modulo (en el hilo principal), y no dentro del hilo trabajador.
if "comtypes" in sys.modules:
    log.warning(
        "comtypes ya estaba importado antes que appctl.hilo: si UIA falla con "
        "RPC_E_CHANGED_MODE, es por esto"
    )
sys.coinit_flags = COINIT_MULTITHREADED

T = TypeVar("T")

# Marca el hilo trabajador para poder detectar reentradas (ver `en_hilo`).
_local = threading.local()


def _arrancar() -> None:
    _local.es_el_hilo = True
    hr = ctypes.windll.ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
    # S_OK (0) y S_FALSE (1) son los dos buenos: el segundo solo dice que este
    # hilo ya estaba inicializado en el mismo apartamento.
    if hr not in (0, 1):
        log.error("CoInitializeEx fallo con hr=0x%08X", hr & 0xFFFFFFFF)


_ejecutor = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="appctl-uia", initializer=_arrancar
)


def en_hilo(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Ejecuta `fn` en el hilo de UIA y espera el resultado (version sincrona).

    Si ya se esta dentro del hilo, se llama directamente: encolar aqui seria un
    interbloqueo garantizado (el unico trabajador estaria esperandose a si
    mismo). Pasa en cuanto una funcion publica de uia.py llama a otra.
    """
    if getattr(_local, "es_el_hilo", False):
        return fn(*args, **kwargs)
    return _ejecutor.submit(functools.partial(fn, *args, **kwargs)).result()


async def en_hilo_async(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Igual, pero sin bloquear el bucle de eventos del servidor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _ejecutor, functools.partial(fn, *args, **kwargs)
    )
