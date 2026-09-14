"""Escribir en la app de escritorio: teclado por mensajes, con verificacion.

Se usa PostMessage y no SendInput a proposito, y la diferencia importa:

- `SendInput` inyecta en la cola GLOBAL del sistema. O sea que compite con lo
  que estes tecleando tu en ese momento, y si el foco cambia a mitad de frase el
  resto de la frase se va a la ventana que haya quedado delante. Desde el movil
  no hay forma de saber que ha pasado eso.
- `PostMessage` va dirigido a ESTA ventana y a ninguna otra. Ademas no toca el
  estado del teclado fisico (no deja una tecla "pulsada" si algo falla a medias)
  ni el portapapeles.

Un WM_CHAR por unidad de codigo UTF-16, que es justo lo que espera Windows: asi
entran acentos, enies y simbolos sin depender de la distribucion del teclado.
Comprobado con "áéñ€".

LO QUE NO SE PUEDE EVITAR: la ventana tiene que estar en primer plano. Medido a
la contra -- con otra ventana delante y sin tocar el foco, los WM_CHAR se
descartan en silencio, sin error. Por eso aqui todo empieza por enfocar y, si no
se consigue, se ABORTA en vez de teclear a ciegas.
"""

from __future__ import annotations

import logging
import time

import win32api
import win32con
import win32gui

from . import uia
from .window import Ventana, traer_al_frente

log = logging.getLogger("controladora.appctl.input")

WM_KEYDOWN, WM_KEYUP, WM_CHAR = 0x100, 0x101, 0x102
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x200, 0x201, 0x202
MK_LBUTTON = 0x0001

# Cuanto se espera a que el texto tecleado aparezca en el compositor antes de
# darlo por perdido. Es generoso: la app puede estar ocupada pintando una
# respuesta larga cuando llega el mensaje del movil.
ESPERA_ECO = 3.0


class NoSePudoEscribir(Exception):
    """No se escribio nada, y se sabe por que. Nunca se lanza a medias."""


def _teclear(render: int, texto: str) -> None:
    for ch in texto:
        win32api.PostMessage(render, WM_CHAR, ord(ch), 1)


def tecla(v: Ventana, vk: int) -> None:
    win32api.PostMessage(v.render, WM_KEYDOWN, vk, 1)
    win32api.PostMessage(v.render, WM_KEYUP, vk, 1)


def enfocar(v: Ventana) -> None:
    """Deja el compositor listo para recibir texto, o lanza NoSePudoEscribir."""
    if uia.enfocar_compositor(v.hwnd):
        return
    # Segunda via, por si la primera no pudo: no sustituye a la de UIA (contra
    # una app a pantalla completa esta falla), pero cuesta poco intentarlo.
    if traer_al_frente(v.hwnd) and uia.enfocar_compositor(v.hwnd):
        return
    raise NoSePudoEscribir(
        "No pude traer la ventana de Claude al primer plano. Sin eso, lo que se "
        "teclee se pierde. Suele pasar si hay algo a pantalla completa delante."
    )


# Tope de retrocesos de `limpiar`. Un borrador larguisimo se queda a medio
# borrar antes que colgar el servicio mandando cien mil mensajes.
MAX_BORRADO = 4000


def limpiar(v: Ventana) -> None:
    """Vacia el compositor. Para no enviar mezclado con un borrador a medias.

    El compositor vacio no lee como vacio: pinta un texto de sugerencia
    ("Escribe / para comandos") que TextPattern devuelve como si fuera
    contenido. No se intenta distinguirlo por su texto -- esta traducido, y
    reconocer idiomas a base de subcadenas es justo lo que este modulo evita.
    Se manda un retroceso por caracter y ya esta: el texto de sugerencia no es
    contenido real, asi que los retrocesos de sobra no borran nada.
    """
    actual = uia.texto_compositor(v.hwnd)
    if not actual.strip():
        return
    for _ in range(min(len(actual), MAX_BORRADO) + 4):
        tecla(v, win32con.VK_BACK)
    time.sleep(0.2)


def escribir(v: Ventana, texto: str) -> str:
    """Teclea `texto` y devuelve lo que quedo en el compositor.

    Lanza NoSePudoEscribir si no se pudo enfocar o si el texto no llego entero.
    Lo segundo importa: enviar media frase es peor que no enviar nada.
    """
    if not texto.strip():
        raise NoSePudoEscribir("No hay nada que escribir.")

    enfocar(v)
    time.sleep(0.15)
    _teclear(v.render, texto)

    limite = time.time() + ESPERA_ECO
    escrito = ""
    while time.time() < limite:
        escrito = uia.texto_compositor(v.hwnd)
        if texto in escrito:
            return escrito
        time.sleep(0.15)

    raise NoSePudoEscribir(
        f"Teclee el texto pero no aparece entero en el compositor. "
        f"Lo que hay ahora: {escrito[:200]!r}"
    )


def enviar(v: Ventana, texto: str, devolver_foco: bool = True) -> None:
    """Escribe y pulsa Enter. Verifica antes de enviar y despues de enviar.

    Las dos comprobaciones existen por motivos distintos:
    - Antes: que el texto este ENTERO en el compositor (si no, se envia media
      frase) y que la ventana siga delante (si no, el Enter se lo come otra app).
    - Despues: que el compositor se haya vaciado. Si el Enter no hubiera hecho
      nada, el texto seguiria ahi, y decir "enviado" seria mentira.

    [devolver_foco]: dejar el primer plano donde estaba. Es cortesia, no
    garantia: Windows puede negarse a devolverlo (ver window.traer_al_frente), y
    en ese caso no se hace ruido -- el mensaje ya se envio, que es lo que
    importaba.
    """
    antes = win32gui.GetForegroundWindow()

    escribir(v, texto)

    if win32gui.GetForegroundWindow() != v.hwnd:
        raise NoSePudoEscribir(
            "La ventana perdio el primer plano justo antes de enviar. No pulso "
            "Enter: se iria a otra aplicacion."
        )

    tecla(v, win32con.VK_RETURN)

    limite = time.time() + 3.0
    enviado = False
    while time.time() < limite:
        if texto not in uia.texto_compositor(v.hwnd):
            enviado = True
            break
        time.sleep(0.15)

    if devolver_foco and antes and antes != v.hwnd:
        traer_al_frente(antes)

    if not enviado:
        raise NoSePudoEscribir(
            "Pulse Enter pero el texto sigue en el compositor: puede que no se "
            "enviara. No lo reintento solo, para no mandarlo dos veces."
        )
    log.info("enviado a la app: %s", texto[:120])


def _lparam(x: int, y: int) -> int:
    """Empaqueta un punto como lo espera un mensaje de raton: y arriba, x abajo.

    Las DOS mitades se enmascaran. Con `(y << 16) | (x & 0xFFFF)` una `y`
    negativa se lleva por delante el numero entero (sale un lparam negativo que
    PostMessage rechaza o interpreta al reves), y una `y` negativa la produce
    cualquier punto por encima del area de cliente -- que es donde esta la barra
    de titulo de la ventana, o sea, algo que el movil puede tocar.
    """
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


def _cliente(v: Ventana, x: int, y: int) -> int:
    """(x, y) de PANTALLA -> lparam en coordenadas de cliente de `v.render`."""
    lx, ly = win32gui.ScreenToClient(v.render, (x, y))
    return _lparam(lx, ly)


def clic(v: Ventana, x: int, y: int) -> None:
    """Un clic en (x, y) de la PANTALLA, mandado como mensaje a la ventana.

    No mueve el cursor del usuario ni toca la cola global del sistema: se manda
    a la ventana de Claude y a ninguna otra. Eso si, Chromium activa su ventana
    al recibirlo, o sea que esto trae la app al primer plano igual que un clic
    de verdad -- comprobado; no hay forma de pulsar en segundo plano.
    """
    lp = _cliente(v, x, y)
    win32api.PostMessage(v.render, WM_MOUSEMOVE, 0, lp)
    win32api.PostMessage(v.render, WM_LBUTTONDOWN, MK_LBUTTON, lp)
    time.sleep(0.05)
    win32api.PostMessage(v.render, WM_LBUTTONUP, 0, lp)


def pulsar(v: Ventana, nombre: str, por_el_final: bool = False) -> bool:
    """Pulsa un boton de la app, por el camino que funcione.

    Primero por UIA, que es limpio y no roba el foco. Si ese boton no soporta
    InvokePattern -- pasa de verdad, el de uso de tokens no lo soporta -- se
    hace clic en su centro. El respaldo existe porque sin el, el movil pinta un
    boton que al tocarlo no hace nada y no hay forma de saber por que.
    """
    if uia.pulsar(v.hwnd, nombre, por_el_final):
        return True

    m = uia.buscar_mando(v.hwnd, nombre, por_el_final)
    if m is None:
        return False

    izq, arriba, ancho, alto = m.rect
    if ancho <= 0 or alto <= 0:
        log.warning("%r no tiene tamaño en pantalla: no se puede clicar", m.nombre)
        return False

    clic(v, izq + ancho // 2, arriba + alto // 2)
    log.info("pulsado %r con un clic (no tenia InvokePattern)", m.nombre)
    return True


def pulsar_conocido(v: Ventana, clave: str) -> bool:
    """Pulsa uno de los botones de `uia.ETIQUETAS`, probando sus idiomas.

    Igual que `uia.pulsar_conocido` pero con el respaldo de clic. Se usa esta y
    no aquella desde fuera del paquete: ningun boton deberia quedarse sin pulsar
    solo porque su nodo no expone InvokePattern.
    """
    nombres = uia.ETIQUETAS.get(clave)
    if not nombres:
        raise KeyError(f"etiqueta desconocida: {clave!r}. Conocidas: {sorted(uia.ETIQUETAS)}")
    for n in nombres:
        if pulsar(v, n):
            return True
    log.warning("no encontre el boton %r (probe %s)", clave, list(nombres))
    return False


def parar(v: Ventana) -> None:
    """Corta el turno en curso, como pulsar Escape en la app."""
    enfocar(v)
    tecla(v, win32con.VK_ESCAPE)
