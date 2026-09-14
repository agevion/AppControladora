"""Capturar un monitor entero, con BitBlt.

Hasta v15 esto capturaba la ventana de Claude con `PrintWindow` (aunque
estuviera tapada). Desde v16 el video es de pantalla completa: ya no hace
falta esa capacidad (nada tapa a un monitor entero salvo otro monitor, y eso
no es un problema de captura) y `BitBlt` desde el DC del escritorio es mas
simple y mas barato.

Los recursos de GDI (los DC y el bitmap) se crean una vez y se reutilizan en
cada fotograma. Crearlos y destruirlos 30 veces por segundo no solo es lento:
GDI tiene un tope de objetos por proceso y una fuga ahi tumba la aplicacion
entera sin decir por que. Mismo patron que tenia la captura de ventana.
"""

from __future__ import annotations

import logging

import numpy as np
import win32gui
import win32ui

from . import _dpi  # noqa: F401  antes de preguntar por ningun rectangulo
from .pantallas import Pantalla

log = logging.getLogger("controladora.appctl.capture")

SRCCOPY = 0x00CC0020


class CapturaPantalla:
    """Fotogramas de UN monitor. No es segura entre hilos: usala desde uno solo."""

    def __init__(self, p: Pantalla) -> None:
        self.p = p
        self._dc_pantalla = None
        self._dc = None
        self._dc_mem = None
        self._bmp = None

    def _preparar(self) -> None:
        self._soltar()
        # `GetDC(None)` da el DC del escritorio VIRTUAL entero (todos los
        # monitores a la vez, en las mismas coordenadas que devuelve
        # `pantallas.listar`), asi que capturar UN monitor es un BitBlt con
        # origen desplazado a `p.x, p.y` -- funciona igual con monitores a la
        # izquierda o encima del principal, cuyas coordenadas son negativas.
        self._dc_pantalla = win32gui.GetDC(0)
        self._dc = win32ui.CreateDCFromHandle(self._dc_pantalla)
        self._dc_mem = self._dc.CreateCompatibleDC()
        self._bmp = win32ui.CreateBitmap()
        self._bmp.CreateCompatibleBitmap(self._dc, self.p.ancho, self.p.alto)
        self._dc_mem.SelectObject(self._bmp)
        log.info("captura preparada para %s a %dx%d", self.p.id, self.p.ancho, self.p.alto)

    def _soltar(self) -> None:
        try:
            if self._bmp is not None:
                win32gui.DeleteObject(self._bmp.GetHandle())
            if self._dc_mem is not None:
                self._dc_mem.DeleteDC()
            if self._dc is not None:
                self._dc.DeleteDC()
            if self._dc_pantalla is not None:
                win32gui.ReleaseDC(0, self._dc_pantalla)
        except Exception as e:
            log.debug("soltando recursos de GDI: %s", e)
        finally:
            self._bmp = self._dc_mem = self._dc = self._dc_pantalla = None

    def cerrar(self) -> None:
        self._soltar()

    def frame(self) -> np.ndarray | None:
        """Un fotograma en BGRA (alto, ancho, 4), o None si no se pudo.

        **BGRA y no BGR**, medido igual que en la captura de ventana que esto
        sustituye: recortar el canal de relleno deja el array NO CONTIGUO y
        `VideoFrame.from_ndarray` se va por el camino lento (28 ms en vez de
        menos de 1). El precio es un canal que no se usa; el ahorro es pasar
        de 20 a 40 fps. Ver appctl/webrtc.py.
        """
        if self._dc_mem is None or self._bmp is None:
            try:
                self._preparar()
            except Exception as e:
                log.warning("no pude preparar la captura de %s: %s: %s", self.p.id, type(e).__name__, e)
                self._soltar()
                return None

        assert self._dc_mem is not None and self._bmp is not None
        # `PyCDC.BitBlt` no devuelve un booleano de exito -- devuelve None y
        # LANZA en vez de fallar en silencio (a diferencia de la API C que
        # envuelve). Medido: comprobar el valor de vuelta como si fuera un
        # bool descartaba TODOS los fotogramas, exito incluido.
        try:
            self._dc_mem.BitBlt(
                (0, 0), (self.p.ancho, self.p.alto), self._dc, (self.p.x, self.p.y), SRCCOPY
            )
        except Exception as e:
            log.warning("BitBlt fallo capturando %s: %s: %s", self.p.id, type(e).__name__, e)
            return None

        info = self._bmp.GetInfo()
        crudo = self._bmp.GetBitmapBits(True)
        arr = np.frombuffer(crudo, dtype=np.uint8)
        return arr.reshape((info["bmHeight"], info["bmWidth"], 4))


def abrir(p: Pantalla) -> CapturaPantalla:
    return CapturaPantalla(p)
