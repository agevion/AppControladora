"""Progreso en vivo de una tool en marcha, sin tocar el contrato del registry.

Un build de Gradle o una instalacion por adb pueden tardar minutos. Sin esto,
el movil ve la tarjeta "TOOL empezada" y luego silencio total hasta el
resultado final: ni una linea, ni una barra, nada.

Cualquier tool puede llamar a `report(texto)` en mitad de su `run()` para mandar
una linea de estado al movil AHORA MISMO, sin esperar a devolver el resultado.
No hace falta cambiar la firma de `run()` ni el contrato de SPEC/CONFIRM del
registry (ver registry.py): es opcional, y si nadie esta escuchando -- la tool
se ejecuta fuera de una conversacion, o quien la llama no entro en `listen()`
-- no hace nada. Llamar a `report()` es siempre seguro.

Como llega al movil: `LocalBrain.chat()` (brain_local.py) entra en `listen()`
justo antes de ejecutar la tool, en el hilo del event loop. `registry.call()`
corre la tool con `asyncio.to_thread`, que SI propaga los contextvars al hilo
nuevo (documentado en la stdlib) -- por eso esto funciona sin pasar nada por
parametro a traves de `registry.call` ni de cada `run()`. Cada `report()`
dentro de ese hilo llega al callback registrado, que lo mete en una cola
async, y `chat()` lo reenvia como un evento `tool_progress` por el WebSocket.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Callable, Iterator

_reporter: contextvars.ContextVar[Callable[[str], None] | None] = contextvars.ContextVar(
    "reporter", default=None
)


def report(texto: str) -> None:
    fn = _reporter.get()
    if fn is not None:
        fn(texto)


@contextmanager
def listen(fn: Callable[[str], None]) -> Iterator[None]:
    """Todo `report()` que ocurra dentro de este bloque -- en este hilo, o en uno
    lanzado desde aqui con `asyncio.to_thread` -- llega a `fn`."""
    token = _reporter.set(fn)
    try:
        yield
    finally:
        _reporter.reset(token)
