"""Decirle a Windows que sabemos de escalado. Se importa por su efecto, no por su API.

Este PC tiene la pantalla al 150%. A un proceso que NO declara ser consciente del
escalado, Windows le miente en todo lo que sean coordenadas: `GetWindowRect`
devuelve pixeles "logicos" y las capturas salen escaladas por el sistema, borrosas
y con el tamano cambiado. Osea que un clic calculado sobre el centro de un boton
caeria desplazado, y el video del movil no cuadraria con la ventana de verdad.

Solo se puede fijar UNA vez por proceso y tiene que ser ANTES de la primera
llamada que pregunte por una ventana. Por eso vive en su propio modulo, sin
dependencias, y lo importan `window.py` y `uia.py` los primeros: da igual por cual
de los dos se entre en el paquete, el efecto ya esta hecho.

Si falla no se aborta nada: se cae al modo antiguo (consciente del sistema, no de
cada monitor), que es peor pero funciona mientras no muevas la ventana entre
monitores con escalados distintos.
"""

from __future__ import annotations

import ctypes
import logging

log = logging.getLogger("controladora.appctl.dpi")

PER_MONITOR_AWARE_V2 = 2

_hecho = False


def asegurar() -> None:
    global _hecho
    if _hecho:
        return
    _hecho = True
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(PER_MONITOR_AWARE_V2)
        return
    except Exception as e:
        # E_ACCESSDENIED significa que ya estaba puesto (por el manifiesto del
        # ejecutable o por otra parte del proceso). No es un fallo.
        log.debug("SetProcessDpiAwareness no aplico: %s", e)
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception as e:
        log.warning("sin conciencia de DPI: las coordenadas pueden salir desplazadas (%s)", e)


asegurar()
