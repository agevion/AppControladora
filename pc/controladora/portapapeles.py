"""El portapapeles de Windows: leerlo, escribirlo y enterarse de que cambio.

Es la mitad de texto del traspaso PC <-> movil: copias algo en el PC (Ctrl+C
sobre lo que sea, en cualquier aplicacion) y aparece en el portapapeles del
telefono; y al reves, lo que tengas copiado en el movil se puede pegar aqui.

Dos cosas explican por que esto no es un par de lineas:

- **El portapapeles es un recurso EXCLUSIVO de todo Windows.** Solo un proceso
  puede tenerlo abierto a la vez, asi que OpenClipboard falla de verdad y a
  menudo -- justo mientras otra aplicacion esta copiando. Por eso se reintenta
  en lugar de dar por hecho que se pudo abrir, y por eso se cierra SIEMPRE
  (finally): dejarlo abierto le cuelga el Ctrl+C a todas las demas aplicaciones
  del sistema, no solo a la nuestra.

- **Se vigila por numero de secuencia, no leyendo el contenido.**
  GetClipboardSequenceNumber es un contador que Windows sube cada vez que
  alguien escribe en el portapapeles, y consultarlo NO abre el portapapeles: no
  le estorba a nadie. Preguntar por el CONTENIDO cada segundo si lo abriria cada
  segundo, y eso es justo lo que hace que "falle el Ctrl+C" con un gestor de
  portapapeles mal hecho de por medio.

  El contador vale 0 cuando el proceso no tiene acceso a la estacion de ventanas
  (un servicio sin sesion interactiva, o esta misma funcion llamada desde una
  consola que no cuelga del escritorio). Ahi se cae al plan B -- comparar el
  texto -- que da el mismo resultado, solo que abriendo el portapapeles.
"""

from __future__ import annotations

import ctypes
import logging
import time

import win32clipboard as wc

log = logging.getLogger("controladora.portapapeles")

# Cuantas veces se reintenta abrir el portapapeles antes de rendirse, y cuanto
# se espera entre intentos. 5 x 50 ms = un cuarto de segundo como mucho: mas que
# de sobra para que otra aplicacion suelte el portapapeles tras un Ctrl+C, y
# poco como para no bloquear el hilo que llama.
INTENTOS = 5
ESPERA = 0.05


def _abrir() -> bool:
    """True si el portapapeles quedo abierto (y hay que cerrarlo). False si no se pudo."""
    for _ in range(INTENTOS):
        try:
            wc.OpenClipboard()
            return True
        except Exception:  # pywin32 lanza pywintypes.error, que no es OSError
            time.sleep(ESPERA)
    return False


def leer() -> str:
    """El texto del portapapeles del PC, o "" si no hay texto (una imagen, un
    fichero copiado, o nada) o no se pudo abrir.

    Nunca revienta a proposito: esto lo llama un vigilante cada pocas decimas y
    un fallo puntual del portapapeles no debe tumbar nada.
    """
    if not _abrir():
        return ""
    try:
        if not wc.IsClipboardFormatAvailable(wc.CF_UNICODETEXT):
            return ""
        datos = wc.GetClipboardData(wc.CF_UNICODETEXT)
    except Exception as e:
        log.debug("no se pudo leer el portapapeles: %s", e)
        return ""
    finally:
        wc.CloseClipboard()
    return datos or ""


def escribir(texto: str) -> bool:
    """Deja [texto] copiado en el PC, listo para pegar con Ctrl+V. True si se pudo.

    EmptyClipboard antes de escribir no es opcional: ademas de vaciar, es lo que
    le da a este proceso la PROPIEDAD del portapapeles. Sin eso, SetClipboardData
    falla contra el portapapeles de otro.
    """
    if not _abrir():
        return False
    try:
        wc.EmptyClipboard()
        wc.SetClipboardText(texto, wc.CF_UNICODETEXT)
        return True
    except Exception as e:
        log.warning("no se pudo escribir en el portapapeles: %s", e)
        return False
    finally:
        wc.CloseClipboard()


def secuencia() -> int:
    """El contador de cambios de Windows. 0 = no disponible (ver el docstring del modulo)."""
    try:
        return int(ctypes.windll.user32.GetClipboardSequenceNumber())
    except Exception:
        return 0


class Vigilante:
    """Contesta a "¿ha cambiado el portapapeles desde la ultima vez que preguntaste?".

    Se pregunta desde un hilo aparte (asyncio.to_thread) cada pocas decimas: ver
    Session._vigilar_portapapeles en server.py.

    La PRIMERA llamada devuelve lo que haya copiado ahora mismo, no None. Es
    deliberado: el caso normal es copiar algo en el PC y DESPUES coger el movil,
    asi que al conectar lo util es tener ya lo ultimo que se copio. El movil
    descarta el repetido si ya lo tenia (ver ChatStore.recibirPortapapeles), asi
    que reconectar no llena el historial de duplicados.
    """

    def __init__(self) -> None:
        self._seq = 0
        self._ultimo: str | None = None

    def cambio(self) -> str | None:
        """El texto nuevo, o None si no ha cambiado nada desde la ultima llamada."""
        seq = secuencia()
        if seq and seq == self._seq:
            return None  # el camino barato: ni se abre el portapapeles
        self._seq = seq

        texto = leer()
        # El texto vacio no se propaga: copiar una imagen o un fichero deja el
        # portapapeles sin CF_UNICODETEXT, y eso no es "el usuario copio nada",
        # es "aqui no hay texto que traspasar". Mandarlo borraria del movil lo
        # anterior, que si servia.
        if not texto or texto == self._ultimo:
            return None
        self._ultimo = texto
        return texto

    def recuerda(self, texto: str) -> None:
        """Da por visto [texto] sin mandarlo a ningun sitio.

        Es lo que evita el eco: cuando el movil manda su portapapeles y lo
        escribimos en el PC, el contador de Windows sube y el vigilante lo veria
        como "algo nuevo copiado en el PC" -- y se lo devolveria al movil, que
        acaba de mandarlo. Una vuelta entera para no cambiar nada.
        """
        self._seq = secuencia()
        self._ultimo = texto
