"""Encontrar (y si hace falta abrir) la ventana de la app de escritorio.

Nada de UIA aqui: esto es solo Win32, asi que se puede llamar desde cualquier
hilo. Todo lo que necesite el arbol de accesibilidad vive en `uia.py`.

Dos ventanas, no una: la de arriba (`Chrome_WidgetWin_1`) es el marco, y dentro
tiene una hija (`Chrome_RenderWidgetHostHWND`) que es la que recibe teclado y
raton. Mandarle un WM_CHAR al marco no hace nada -- comprobado. Por eso
`Ventana` lleva las dos.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import win32api
import win32con
import win32gui
import win32process

from . import _dpi  # noqa: F401  se importa por su efecto: ver _dpi.py

log = logging.getLogger("controladora.appctl.window")

# El nombre de la carpeta del paquete MSIX lleva el hash del publicador, que es
# estable para una misma firma. Sirve para distinguir la app de Claude de
# cualquier otra ventana de Chromium (Chrome, Edge, otro Electron) sin mirar el
# titulo, que esta traducido y cambia con la sesion que tengas abierta.
PAQUETE = "windowsapps\\claude_"
CLASE_MARCO = "Chrome_WidgetWin_1"
CLASE_RENDER = "Chrome_RenderWidgetHostHWND"

# Id de la aplicacion dentro del paquete (AppxManifest: <Application Id="Claude">).
APP_ID = "Claude"


class NoEstaLaApp(Exception):
    """La app de escritorio no esta abierta y no se ha podido abrir."""


@dataclass(frozen=True)
class Ventana:
    hwnd: int      # el marco: para primer plano, rectangulo y captura
    render: int    # la hija: para teclado y raton
    pid: int
    titulo: str


def _ruta_de(pid: int) -> str:
    try:
        h = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        try:
            return win32process.GetModuleFileNameEx(h, 0)
        finally:
            win32api.CloseHandle(h)
    except Exception:
        return ""


def _render_de(hwnd: int) -> int:
    hijos: list[int] = []

    def visita(h: int, _: object) -> bool:
        if win32gui.GetClassName(h) == CLASE_RENDER:
            hijos.append(h)
        return True

    win32gui.EnumChildWindows(hwnd, visita, None)
    return hijos[0] if hijos else 0


def buscar() -> Ventana | None:
    """La ventana principal de la app, o None si no esta abierta.

    De todas las `Chrome_WidgetWin_1` del proceso solo vale la que tiene titulo:
    las demas son auxiliares de Chromium (menus emergentes, tooltips) y no
    tienen contenido ni reciben teclado.
    """
    candidatas: list[Ventana] = []

    def visita(hwnd: int, _: object) -> bool:
        if win32gui.GetClassName(hwnd) != CLASE_MARCO:
            return True
        titulo = win32gui.GetWindowText(hwnd)
        if not titulo:
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if PAQUETE not in _ruta_de(pid).lower():
            return True
        render = _render_de(hwnd)
        if render:
            candidatas.append(Ventana(hwnd=hwnd, render=render, pid=pid, titulo=titulo))
        return True

    win32gui.EnumWindows(visita, None)
    return candidatas[0] if candidatas else None


def _familia_de_paquete() -> str | None:
    """El "package family name", deducido del nombre de la carpeta instalada.

    La carpeta se llama `Claude_1.26832.0.0_x64__pzs8sxrjxfjjc` y la familia es
    `Claude_pzs8sxrjxfjjc`: el nombre y el hash del publicador, sin version ni
    arquitectura. Se deduce en vez de fijarla a mano porque la version cambia en
    cada actualizacion y dejarla escrita seria romperse a la siguiente.
    """
    base = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WindowsApps"
    try:
        carpetas = sorted(d.name for d in base.iterdir() if d.name.startswith("Claude_"))
    except Exception:
        return None
    for nombre in carpetas:
        partes = nombre.split("_")
        if len(partes) >= 2 and partes[-1]:
            return f"{partes[0]}_{partes[-1]}"
    return None


def abrir() -> bool:
    """Lanza la app de escritorio. Devuelve si se pudo lanzar (no si ya arranco).

    Se activa por el shell y no ejecutando el .exe directamente: un paquete MSIX
    tiene que arrancar CON identidad de paquete, porque si no Windows no le aplica
    las redirecciones de almacenamiento y la app se encuentra un perfil vacio (ni
    sesion iniciada, ni sesiones, ni nada). Ejecutar el .exe a pelo "funciona" en
    el sentido de que abre una ventana, y por eso es una trampa.
    """
    familia = _familia_de_paquete()
    if not familia:
        log.error("no encuentro el paquete de Claude en WindowsApps")
        return False
    destino = f"shell:AppsFolder\\{familia}!{APP_ID}"
    log.info("abriendo la app de escritorio: %s", destino)
    try:
        subprocess.Popen(
            ["explorer.exe", destino],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception as e:
        log.error("no pude lanzar la app: %s: %s", type(e).__name__, e)
        return False


def asegurar(espera: float = 30.0) -> Ventana:
    """La ventana, abriendo la app si hace falta. Lanza NoEstaLaApp si no aparece."""
    v = buscar()
    if v is not None:
        return v

    if not abrir():
        raise NoEstaLaApp(
            "La app de escritorio de Claude no esta abierta y no he podido abrirla."
        )

    limite = time.time() + espera
    while time.time() < limite:
        time.sleep(0.5)
        v = buscar()
        if v is not None:
            log.info("la app tardo %.1fs en aparecer", espera - (limite - time.time()))
            return v

    raise NoEstaLaApp(
        f"Lance la app de escritorio pero no aparecio ninguna ventana en {espera:.0f}s."
    )


def restaurar(v: Ventana) -> None:
    """Saca la ventana de minimizada. Importa para capturar: una ventana
    minimizada no dibuja nada y sale negra."""
    if win32gui.IsIconic(v.hwnd):
        win32gui.ShowWindow(v.hwnd, win32con.SW_RESTORE)
        time.sleep(0.3)


def rect(v: Ventana) -> tuple[int, int, int, int]:
    """(izquierda, arriba, ancho, alto) de la ventana, en pixeles de pantalla."""
    izq, arriba, der, abajo = win32gui.GetWindowRect(v.hwnd)
    return izq, arriba, der - izq, abajo - arriba


def en_primer_plano(v: Ventana) -> bool:
    return win32gui.GetForegroundWindow() == v.hwnd


# DWM puede OCULTAR una ventana sin minimizarla: otro escritorio virtual, una
# app que Windows manda a dormir, una ventana que aun no ha terminado de
# aparecer. El detalle que importa: `IsIconic` devuelve False en todos esos
# casos y la ventana no dibuja nada nuevo igualmente, asi que sin preguntar por
# esto no hay forma de distinguir "no ha cambiado nada" de "no puede cambiar".
DWMWA_CLOAKED = 14


def oculta(hwnd: int) -> int:
    """0 si la ventana es visible para DWM, !=0 si esta oculta. -1 si no se sabe.

    Los valores distintos de cero que documenta Windows son 1 (la propia app se
    escondio), 2 (lo hizo el shell: escritorio virtual) y 4 (herencia de la
    ventana padre). Se devuelve el numero tal cual en vez de un booleano porque
    en un log dice tres cosas distintas y cuesta lo mismo.
    """
    v = ctypes.c_int(0)
    hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        ctypes.wintypes.HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(v), ctypes.sizeof(v)
    )
    return v.value if hr == 0 else -1


RDW_INVALIDATE = 0x0001
RDW_ALLCHILDREN = 0x0080


def repintar(v: Ventana) -> None:
    """Pide a la ventana que se vuelva a dibujar.

    Es un empujon, no una garantia, y conviene tenerlo claro: Chromium pinta por
    su compositor y no por WM_PAINT, asi que puede ignorarlo. Cuesta
    microsegundos y no tiene efectos secundarios (no roba el foco ni mueve
    nada), asi que vale la pena intentarlo antes de rendirse cuando el video
    lleva rato sin un pixel nuevo -- ver `webrtc.PistaVentana._sacudir`.

    **Sin RDW_UPDATENOW a proposito.** Ese flag pinta SINCRONAMENTE: se queda
    esperando a que el hilo de la otra aplicacion atienda el WM_PAINT. Si la app
    esta colgada -- que es justamente uno de los motivos por los que el video se
    puede haber quedado quieto -- eso deja bloqueado para siempre al hilo que
    captura. Marcar la zona como invalida y dejar que la app repinte a su ritmo
    consigue lo mismo sin poder colgar nada.
    """
    for h in (v.hwnd, v.render):
        if h and win32gui.IsWindow(h):
            try:
                win32gui.RedrawWindow(h, None, None, RDW_INVALIDATE | RDW_ALLCHILDREN)
            except Exception as e:
                log.debug("RedrawWindow(%d) fallo: %s", h, e)


def ventana_al_frente() -> int:
    return win32gui.GetForegroundWindow()


def traer_al_frente(hwnd: int) -> bool:
    """SetForegroundWindow con el apanio de AttachThreadInput.

    Windows no deja que un proceso cualquiera robe el primer plano:
    SetForegroundWindow falla EN SILENCIO si el que llama no es ya el proceso
    que lo tiene. El apanio conocido es engancharse a la cola de entrada del
    hilo que si lo tiene; mientras dura el enganche Windows nos considera parte
    de esa cola y deja pasar el cambio. Se desengancha siempre.

    No es la via principal para la ventana de Claude -- para eso esta
    `uia.enfocar_compositor`, que se lo pide a la propia app y no depende de
    esta proteccion (medido: contra un juego a pantalla completa, esta falla y
    aquella no). Esto se usa para DEVOLVER el foco a donde estaba, que es la
    unica direccion en la que no hay alternativa.
    """
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    if win32gui.GetForegroundWindow() == hwnd:
        return True

    delante = win32gui.GetForegroundWindow()
    suyo = win32process.GetWindowThreadProcessId(delante)[0] if delante else 0
    nuestro = win32api.GetCurrentThreadId()
    destino = win32process.GetWindowThreadProcessId(hwnd)[0]

    enganches: list[int] = []
    try:
        for otro in (suyo, destino):
            if otro and otro != nuestro and otro not in enganches:
                if ctypes.windll.user32.AttachThreadInput(nuestro, otro, True):
                    enganches.append(otro)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    finally:
        for otro in enganches:
            ctypes.windll.user32.AttachThreadInput(nuestro, otro, False)

    for _ in range(20):
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.05)
    return False
