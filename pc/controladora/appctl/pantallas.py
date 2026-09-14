"""Los monitores del PC: listarlos y resolver un punto sobre uno de ellos.

Hasta v15 el video y los gestos se apuntaban a la ventana de Claude
(`window.py`, `GetWindowRect`). Desde v16 se apuntan al monitor que el movil
este mirando -- este modulo es el equivalente de `window.py` pero para un
monitor entero en vez de una ventana: no hay que "encontrarlo" ni "abrirlo", ya
esta ahi siempre que el PC este encendido, asi que es mucho mas simple.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import win32api

from . import _dpi  # noqa: F401  se importa por su efecto: ver _dpi.py

log = logging.getLogger("controladora.appctl.pantallas")


@dataclass(frozen=True)
class Pantalla:
    # El nombre de dispositivo de Windows, p.ej. `\\.\DISPLAY1`. Es estable
    # entre peticiones (a diferencia de un indice de lista, que cambiaria si
    # se conecta o desconecta un monitor) y es lo que el movil manda de vuelta
    # como `monitor` en RTC_OFFER y cada SCREEN_*.
    id: str
    x: int
    y: int
    ancho: int
    alto: int
    nombre: str
    principal: bool


def listar() -> list[Pantalla]:
    """Todos los monitores conectados, con el principal primero.

    `EnumDisplayMonitors` sin argumentos da uno por cada monitor del sistema,
    en coordenadas del escritorio VIRTUAL -- o sea que un monitor a la
    izquierda o encima del principal sale con `x`/`y` NEGATIVOS, y eso es
    correcto: `capture.CapturaPantalla` y `pantalla_input` los usan tal cual
    contra `GetDC(0)` / `SetCursorPos`, que aceptan negativos igual.
    """
    pantallas: list[Pantalla] = []
    for hmon, _hdc, _rect in win32api.EnumDisplayMonitors():
        info = win32api.GetMonitorInfo(hmon)
        izq, arriba, der, abajo = info["Monitor"]
        principal = bool(info["Flags"] & 1)  # MONITORINFOF_PRIMARY
        pantallas.append(
            Pantalla(
                id=info["Device"],
                x=izq,
                y=arriba,
                ancho=der - izq,
                alto=abajo - arriba,
                nombre=info["Device"],
                principal=principal,
            )
        )
    pantallas.sort(key=lambda p: not p.principal)
    return pantallas


def buscar(id_: str | None) -> Pantalla | None:
    """La pantalla con ese `id`, o la principal si `id_` es None/no existe ya.

    Que el `id` pedido ya no exista (se desconecto un monitor entre que el
    movil pidio la lista y mando la oferta) no es un error: se cae al
    principal en vez de fallar, igual que `window.asegurar` no se rinde a la
    primera.
    """
    todas = listar()
    if id_:
        for p in todas:
            if p.id == id_:
                return p
        log.warning("la pantalla %r ya no existe; uso la principal", id_)
    return next((p for p in todas if p.principal), todas[0] if todas else None)


def punto(p: Pantalla, fx: float, fy: float) -> tuple[int, int]:
    """Fraccion de la pantalla (0 a 1) -> pixel de PANTALLA, recortado a [0, 1].

    Es lo mismo que hacia `brain_app.AppBrain._desde` con el rectangulo de una
    ventana: el `-1` no es un despiste, con la pantalla en x=0 y 1000 de ancho
    los pixeles validos son del 0 al 999 (sin el, fx=1.0 caeria justo fuera).
    """
    fx = min(max(fx, 0.0), 1.0)
    fy = min(max(fy, 0.0), 1.0)
    return (
        p.x + round(fx * max(p.ancho - 1, 0)),
        p.y + round(fy * max(p.alto - 1, 0)),
    )
