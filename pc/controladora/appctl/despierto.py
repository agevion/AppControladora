"""Que Windows no apague la pantalla mientras el movil esta mirando.

**El problema, que es menos obvio de lo que parece.** Los toques del movil
viajan con `PostMessage` (ver `input.py`, y la decision es correcta), pero
PostMessage **no cuenta como actividad del usuario**: no toca el contador que
lee `GetLastInputInfo`, que es el mismo que decide cuando apagar la pantalla.
O sea que puedes estar manejando el PC desde el sofa durante media hora y
Windows creerse que lleva media hora abandonado.

Cuando la pantalla se apaga, DWM deja de componer y **las ventanas dejan de
dibujar**. `capture.PrintWindow` no genera imagen: copia lo ultimo que la
ventana pinto. Asi que lo que llega al movil es el ultimo fotograma bueno,
repetido para siempre, sin un solo error por ningun lado -- se ve exactamente
igual que una pantalla que no cambia. Y los toques siguen llegando, porque esos
no dependen de que nadie pinte nada. De ahi el sintoma: "puedo clicar pero no
veo".

`SetThreadExecutionState` es la via correcta y la que usan los reproductores de
video: dice "mientras yo este aqui, esto cuenta como en uso". No cambia el plan
de energia del PC ni deja nada tocado si el proceso muere.

**El flag es POR HILO**, y ahi esta la trampa: se limpia solo cuando ese hilo
termina, y soltarlo desde otro hilo no hace nada -- el peticion original seguiria
viva. Por eso esto se llama desde el hilo del bucle de eventos (que vive lo que
vive el servidor) y NUNCA desde un `asyncio.to_thread`, cuyo hilo del pool puede
morir en cualquier momento y llevarse la peticion por delante sin avisar.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes

log = logging.getLogger("controladora.appctl.despierto")

ES_CONTINUOUS = 0x80000000        # "esto vale hasta que yo diga lo contrario"
ES_SYSTEM_REQUIRED = 0x00000001   # que no se suspenda el PC
ES_DISPLAY_REQUIRED = 0x00000002  # que no se apague la pantalla

# Cuantos motivos vivos hay para estar despierto. Es un contador y no un
# booleano porque puede haber mas de una conexion de movil a la vez: si la
# segunda se va, la primera sigue mirando y apagar la pantalla ahi seria
# reintroducir el fallo.
_cuantos = 0
_hilo: int | None = None


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def inactividad() -> float:
    """Segundos desde la ultima entrada REAL de teclado o raton. -1 si no se sabe.

    Es el reloj que gobierna el apagado de pantalla, y solo lo mueve la entrada
    fisica (o la que inyecta algo como AnyDesk, que por eso "arregla" el video).
    Los gestos del movil no lo tocan. Se expone para poder DECIRLO en el log
    cuando algo se congela: si el video se quedo quieto con este numero rondando
    el tiempo de apagado configurado, ya sabemos por que fue.
    """
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return -1.0
    return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0


def _aplicar(flags: int) -> bool:
    # Devuelve el estado anterior, o 0 si fallo. No se lanza excepcion: quedarse
    # sin video por no poder pedir que la pantalla siga encendida seria cambiar
    # un fallo molesto por uno peor.
    anterior = ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(flags))
    if anterior == 0:
        log.warning("SetThreadExecutionState(0x%08X) fallo", flags)
        return False
    return True


def pedir() -> None:
    """Un motivo mas para mantener la pantalla encendida. Llamar DESDE EL BUCLE."""
    global _cuantos, _hilo

    actual = threading.get_ident()
    if _cuantos and _hilo != actual:
        # Ya hay una peticion viva puesta por otro hilo. Sumar aqui dejaria dos
        # peticiones en dos hilos distintos y `soltar` solo podria retirar una.
        log.warning(
            "la peticion de pantalla encendida la puso el hilo %s y ahora pide "
            "el %s: se ignora para no dejar uno de los dos colgado",
            _hilo, actual,
        )
        return

    _cuantos += 1
    if _cuantos > 1:
        return

    _hilo = actual
    if _aplicar(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED):
        log.info("pantalla mantenida encendida mientras dure el video")


def soltar() -> None:
    """Un motivo menos. Al llegar a cero, el PC vuelve a poder apagar la pantalla."""
    global _cuantos, _hilo

    if _cuantos <= 0:
        return

    actual = threading.get_ident()
    if _hilo is not None and _hilo != actual:
        # Retirar el flag desde otro hilo no retira nada: el flag vive en el
        # hilo que lo puso. Decirlo es mejor que hacerlo y creerse que se hizo.
        log.warning(
            "se intenta soltar la pantalla desde el hilo %s pero la puso el %s: "
            "no se retira nada", actual, _hilo,
        )
        return

    _cuantos -= 1
    if _cuantos:
        return

    _hilo = None
    if _aplicar(ES_CONTINUOUS):
        log.info("pantalla libre otra vez: el PC ya puede apagarla")
