"""Registro de ficheros (APKs) listos para bajar al movil, y aviso en vivo.

Hermano de progress.py -- mismo patron de contextvars, para el mismo motivo:
una tool puede llamar a `ready(path)` en mitad de su `run()` para avisar YA de
que hay un fichero listo, sin esperar al resultado final. La diferencia con
progress.report() es que aqui no viaja texto libre: viaja un id de descarga,
y la ruta real del fichero en disco nunca sale de este proceso ni del propio
protocolo -- el movil solo ve `artifact.ready {artifact_id, name, size}` y baja
el contenido por un endpoint HTTPS autenticado aparte (ver server.py), no por
el WebSocket.

Por que por HTTPS y no por el WS: un APK son varios MB, y el WS ya lleva el
chat en streaming -- meterlo tambien ahi como base64 lo infla un 33% y compite
por el mismo socket. El servicio ya escucha en el mismo puerto con mTLS
(run.py); un GET autenticado con el mismo token reusa esa infraestructura
tal cual, sin abrir nada nuevo.
"""

from __future__ import annotations

import contextvars
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, NamedTuple

# Cuanto vive un id de descarga sin que se pida. Un build tarda minutos; nadie
# tarda horas en pulsar "Instalar" con el aviso delante en el chat, y esto evita
# que el diccionario crezca sin limite en una sesion larga.
TTL_SECONDS = 3600.0


class Ready(NamedTuple):
    artifact_id: str
    name: str
    size: int


_reporter: contextvars.ContextVar[Callable[["Ready"], None] | None] = contextvars.ContextVar(
    "artifact_reporter", default=None
)

_store: dict[str, tuple[Path, float]] = {}


def _prune() -> None:
    limite = time.monotonic() - TTL_SECONDS
    vencidos = [aid for aid, (_, ts) in _store.items() if ts < limite]
    for aid in vencidos:
        _store.pop(aid, None)


def register(path: Path) -> str:
    """Registra un fichero para descarga y devuelve su id.

    Se puede llamar sin estar dentro de un `listen()`: queda registrado igual
    para que `resolve()` lo encuentre desde el endpoint HTTP, solo que nadie
    se entera en el chat hasta el resultado final de la tool.
    """
    _prune()
    artifact_id = uuid.uuid4().hex
    _store[artifact_id] = (path, time.monotonic())
    return artifact_id


def resolve(artifact_id: str) -> Path | None:
    """La ruta real para ese id, o None si no existe o ya caduco."""
    entry = _store.get(artifact_id)
    return entry[0] if entry else None


def ready(path: Path) -> Ready:
    """Registra `path` Y avisa YA a quien este escuchando (ver `listen()`).

    Devuelve el aviso para que la propia tool pueda describirlo en el texto
    que devuelve al final -- no hace falta llamar a `register()` aparte.
    """
    artifact_id = register(path)
    aviso = Ready(artifact_id, path.name, path.stat().st_size)
    fn = _reporter.get()
    if fn is not None:
        fn(aviso)
    return aviso


@contextmanager
def listen(fn: Callable[["Ready"], None]) -> Iterator[None]:
    """Todo `ready()` que ocurra dentro de este bloque -- en este hilo, o en uno
    lanzado desde aqui con `asyncio.to_thread` -- llega a `fn`."""
    token = _reporter.set(fn)
    try:
        yield
    finally:
        _reporter.reset(token)
