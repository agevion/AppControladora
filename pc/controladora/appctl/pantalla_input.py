"""Ratón y teclado sobre la pantalla entera, no sobre una ventana.

`input.py` manda `PostMessage`/`keybd_event` dirigidos a la ventana de Claude
a propósito: no mueve el cursor real ni compite con lo que el usuario del PC
esté haciendo (ver ARQUITECTURA.md 5.1 y la Fase E). Este módulo hace justo lo
contrario, también a propósito: mueve el cursor de Windows de VERDAD y escribe
en la cola de entrada GLOBAL, porque esto ya no es "pilotar una app concreta
sin que se note" sino "controlar la pantalla como un AnyDesk", que es lo que
Ale pidió explícitamente (v16). Si alguien está delante del PC lo ve moverse.

**Ratón: `SetCursorPos` + `mouse_event`.** Son la API vieja (no `SendInput`),
pero para coordenadas absolutas alcanza y de sobra, y es la misma familia que
ya usaba `input.copiar()` para el Ctrl+C. Funcionan en cualquier ventana, la
tenga o no en primer plano el foco -- que es justo lo que no se podía decir de
`PostMessage` a una ventana concreta.

**Teclado imprimible: `SendInput` con `KEYEVENTF_UNICODE`.** Aquí sí hace
falta la API nueva: es la única forma de inyectar un carácter arbitrario (una
ñ, un emoji) sin conocer la distribución de teclado activa ni depender de que
haya una tecla física que lo represente. `keybd_event` no soporta unicode.

**Teclas especiales (Intro, Retroceso...): `keybd_event`.** No necesitan
unicode -- tienen VK propio -- así que se quedan con la API más simple, la
misma que `input.copiar()`.
"""

from __future__ import annotations

import ctypes
import logging
import time

import win32api
import win32con

log = logging.getLogger("controladora.appctl.pantalla_input")

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120
MAX_MUESCAS = 30  # ver input.py: tope contra un calculo que se ha ido

PASOS_ARRASTRE = 12
PAUSA_ARRASTRE = 0.012


def clic(x: int, y: int) -> None:
    """Un clic izquierdo en (x, y) de PANTALLA, con el cursor real."""
    win32api.SetCursorPos((x, y))
    win32api.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    win32api.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def arrastrar(x1: int, y1: int, x2: int, y2: int) -> None:
    """Arrastra de (x1, y1) a (x2, y2), los dos en pixeles de PANTALLA.

    Mismo patron que `input.arrastrar`: el boton baja, el cursor se mueve en
    varios pasos CON el boton pulsado (una aplicacion que mira el movimiento
    del raton para decidir si hay seleccion, como Chromium, necesita verlo
    moverse -- un salto directo de un extremo a otro no basta), y el `finally`
    garantiza que el boton siempre se suelta aunque algo falle a mitad.
    """
    win32api.SetCursorPos((x1, y1))
    win32api.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    try:
        for i in range(1, PASOS_ARRASTRE + 1):
            t = i / PASOS_ARRASTRE
            win32api.SetCursorPos((round(x1 + (x2 - x1) * t), round(y1 + (y2 - y1) * t)))
            time.sleep(PAUSA_ARRASTRE)
    finally:
        win32api.SetCursorPos((x2, y2))
        win32api.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def rueda(x: int, y: int, muescas: int) -> None:
    """Gira la rueda `muescas` veces sobre (x, y) de PANTALLA.

    Positivo = alejandose de ti = hacia el principio del documento, igual que
    la rueda de un raton de verdad. Ver `input.rueda`, mismo signo y mismo
    tope de muescas por mensaje.
    """
    if not muescas:
        return
    win32api.SetCursorPos((x, y))
    signo = 1 if muescas > 0 else -1
    for _ in range(min(abs(muescas), MAX_MUESCAS)):
        win32api.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, signo * WHEEL_DELTA, 0)
        time.sleep(0.01)


def copiar() -> None:
    """Ctrl+C global: copia lo que este seleccionado ahora mismo en el PC.

    A diferencia de `input.copiar()` no hace falta traer ninguna ventana al
    frente primero -- es un atajo del sistema, va a quien tenga el foco ya,
    sea lo que sea.
    """
    win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
    try:
        _vk_c = 0x43
        win32api.keybd_event(_vk_c, 0, 0, 0)
        win32api.keybd_event(_vk_c, 0, win32con.KEYEVENTF_KEYUP, 0)
    finally:
        # El finally es el que de verdad importa: si algo revienta a mitad,
        # Ctrl no puede quedarse "pulsado" para el resto del sistema.
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.15)
    log.info("pantalla: Ctrl+C enviado")


# --- teclado imprimible: SendInput con KEYEVENTF_UNICODE --------------------
#
# pywin32 no envuelve SendInput, asi que hace falta declarar la struct a mano.
# Es la unica pieza de este modulo (y de todo appctl) que usa la API nueva, y
# solo porque no hay otra forma de inyectar un caracter arbitrario sin apuntar
# a una ventana ni depender del layout de teclado activo.

PUL = ctypes.POINTER(ctypes.c_ulong)
INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002


class _KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL),
    ]


# `MOUSEINPUT` y `HARDWAREINPUT` no se usan -- este modulo no manda ratón por
# `SendInput` -- pero TIENEN que estar declaradas en la union igual que en la
# `INPUT` real de Windows. El bug que esto arregla: con la union declarada
# solo con `ki` (24 bytes), `sizeof(_Input)` sale en 32 en vez de los 40 que
# vale `sizeof(INPUT)` de verdad en 64 bits (`MOUSEINPUT`, con su puntero de
# `dwExtraInfo`, es la mas grande de las tres y es la que decide el tamaño de
# la union). `SendInput` compara el `cbSize` que le pasas contra su propio
# `sizeof(INPUT)` y, si no coincide, NO HACE NADA -- ni error, ni excepcion,
# simplemente no teclea un solo caracter. Medido: `ctypes.sizeof(_Input)` daba
# 32 con la union recortada, y el teclado libre del movil no escribia nada en
# ningun sitio.
class _MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL),
    ]


class _HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_short),
        ("wParamH", ctypes.c_ushort),
    ]


class _InputUnion(ctypes.Union):
    _fields_ = [("mi", _MouseInput), ("ki", _KeyBdInput), ("hi", _HardwareInput)]


class _Input(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _InputUnion)]


def _enviar_tecla_unicode(unidad: int, subir: bool) -> None:
    """Un WM_KEYDOWN/WM_KEYUP unicode, para UNA unidad UTF-16 (ver `escribir`)."""
    extra = ctypes.c_ulong(0)
    flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if subir else 0)
    entrada = _Input(type=INPUT_KEYBOARD, ki=_KeyBdInput(0, unidad, flags, 0, ctypes.pointer(extra)))
    ctypes.windll.user32.SendInput(1, ctypes.pointer(entrada), ctypes.sizeof(_Input))


def escribir(texto: str) -> None:
    """Teclea `texto` donde este el foco ahora mismo, caracter a caracter.

    Se codifica a UTF-16 y se manda una unidad cada vez -- no `ord(ch)`
    directo -- porque un caracter fuera del plano basico (la mayoria de
    emojis) no cabe en los 16 bits de `wScan` y Windows lo espera como PAR
    subrogado, exactamente como ya viaja en UTF-16. Sin esto, esos caracteres
    saldrian truncados o mal.
    """
    for unidad in _unidades_utf16(texto):
        _enviar_tecla_unicode(unidad, subir=False)
        _enviar_tecla_unicode(unidad, subir=True)


def _unidades_utf16(texto: str) -> list[int]:
    crudo = texto.encode("utf-16-le")
    return [crudo[i] | (crudo[i + 1] << 8) for i in range(0, len(crudo), 2)]


# --- teclas especiales: keybd_event, con VK propio ---------------------------

TECLAS: dict[str, int] = {
    "intro": win32con.VK_RETURN,
    "enter": win32con.VK_RETURN,
    "retroceso": win32con.VK_BACK,
    "backspace": win32con.VK_BACK,
    "escape": win32con.VK_ESCAPE,
    "tab": win32con.VK_TAB,
    "supr": win32con.VK_DELETE,
    "delete": win32con.VK_DELETE,
    "inicio": win32con.VK_HOME,
    "home": win32con.VK_HOME,
    "fin": win32con.VK_END,
    "end": win32con.VK_END,
    "arriba": win32con.VK_UP,
    "abajo": win32con.VK_DOWN,
    "izquierda": win32con.VK_LEFT,
    "derecha": win32con.VK_RIGHT,
}


def tecla(nombre: str) -> bool:
    """Pulsa una tecla especial por su nombre (ver TECLAS). False si no se reconoce."""
    vk = TECLAS.get(nombre.strip().lower())
    if vk is None:
        log.warning("tecla desconocida: %r (conocidas: %s)", nombre, sorted(TECLAS))
        return False
    win32api.keybd_event(vk, 0, 0, 0)
    win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
    return True
