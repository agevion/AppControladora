"""Ejecutar una tool y contar por donde va, en un sitio solo.

Esto vivia dentro de LocalBrain como metodo privado, y por eso los botones del
movil (pestana de Acciones rapidas) no podian usarlo: una accion directa NO pasa
por ningun cerebro, asi que "compilar y mandarme el APK" desde un boton se
quedaba en silencio absoluto durante minutos y luego escupia el resultado de
golpe -- mientras que pedir exactamente lo mismo por el chat si iba narrando el
build. La diferencia no tenia ningun motivo: es la misma tool corriendo.

Ahora los dos caminos (chat de la IA local y boton directo) entran por aqui, asi
que se comportan igual y solo hay un sitio donde arreglar esto si vuelve a
romperse.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator

from . import artifacts, progress
from .registry import Registry, ToolError

# Minimo entre dos eventos tool_progress seguidos hacia el movil. Un build puede
# soltar cientos de lineas por segundo en algunos tramos (resolucion de
# dependencias); esto no es un log, es un "en que va ahora mismo", asi que
# coalescer a la ultima linea vista en cada ventana es mejor que mandarlas todas
# -- menos trafico por el WS y una tarjeta que se lee, no que parpadea.
PROGRESS_THROTTLE = 0.35


async def run_with_progress(
    registry: Registry, name: str, args: dict[str, Any]
) -> AsyncIterator[tuple[str, Any]]:
    """Ejecuta una tool y va soltando ("progress", texto) segun llega, ("artifact",
    artifacts.Ready) si hay un fichero listo para el movil, y al final UNO de estos
    dos: ("result", texto) si la tool termino, o ("error", texto) si reviento.

    Los dos ultimos llevan texto para el humano y para el modelo, y se distinguen
    porque un boton del movil necesita saber si la accion salio bien para pintarlo
    (a un cerebro le da igual: para el son dos textos que leer).

    La tool corre en un hilo aparte (asyncio.to_thread), y `progress.report()` /
    `artifacts.ready()` se llaman DESDE ese hilo -- por eso hace falta
    `call_soon_threadsafe` para meter cada aviso en una cola que este generador,
    que vive en el hilo del event loop, pueda leer sin carreras.
    """
    loop = asyncio.get_running_loop()
    cola: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    def _on_progress(texto: str) -> None:
        loop.call_soon_threadsafe(cola.put_nowait, ("progress", texto))

    def _on_artifact(aviso: artifacts.Ready) -> None:
        loop.call_soon_threadsafe(cola.put_nowait, ("artifact", aviso))

    resultado_caja: list[tuple[str, str]] = []

    async def _ejecutar() -> None:
        with progress.listen(_on_progress), artifacts.listen(_on_artifact):
            try:
                resultado_caja.append(("result", await asyncio.to_thread(registry.call, name, args)))
            except ToolError as e:
                resultado_caja.append(("error", str(e)))

    tarea = asyncio.ensure_future(_ejecutar())
    ultimo_envio = 0.0
    # Persisten FUERA del bucle a proposito: si la ultima linea de todas (ej.
    # "paso 5" justo antes de que la tool termine) se lee dentro de la ultima
    # vuelta del bucle pero cae en la ventana de throttle, no se envia ahi -- y
    # si "ultima" viviera solo dentro del bucle, se perderia sin mas: al salir la
    # cola ya esta vacia y no queda nada que volcar despues. Guardando el valor
    # aqui, el volcado final de mas abajo siempre puede recuperarla y mandarla.
    ultima_vista: str | None = None
    ultima_enviada: str | None = None

    async def _drenar() -> AsyncIterator[tuple[str, Any]]:
        # Un "artifact" no es un "por donde va": es un aviso puntual (solo hay uno
        # por build, normalmente), asi que sale YA, sin pasar por el throttle ni
        # por "ultima_vista" -- eso es solo para las lineas de progreso, que si
        # pueden llegar a cientos por segundo.
        nonlocal ultima_vista
        while not cola.empty():
            tipo, valor = cola.get_nowait()
            if tipo == "artifact":
                yield ("artifact", valor)
            else:
                ultima_vista = valor

    while not tarea.done():
        await asyncio.sleep(0.2)
        async for evento in _drenar():
            yield evento
        if ultima_vista is not None and ultima_vista != ultima_enviada:
            ahora = time.monotonic()
            if ahora - ultimo_envio >= PROGRESS_THROTTLE:
                yield ("progress", ultima_vista)
                ultima_enviada = ultima_vista
                ultimo_envio = ahora

    await tarea

    async for evento in _drenar():
        yield evento
    if ultima_vista is not None and ultima_vista != ultima_enviada:
        # Sin throttle aqui: es lo ultimo que se sabra antes del resultado, no
        # tiene sentido tragarsela por llegar demasiado seguida.
        yield ("progress", ultima_vista)

    yield resultado_caja[0]
