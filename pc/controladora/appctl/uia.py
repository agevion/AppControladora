"""Leer y accionar la app de escritorio por la accesibilidad de Windows.

**Este es el UNICO fichero que sabe como esta hecha la interfaz de la app.** Si
una actualizacion mueve algo, se arregla aqui y no en quince sitios. Todo lo
demas (`brain_app`, el servidor, el movil) habla de "el compositor" o "el boton
de esta sesion", no de arboles ni de patrones.

Por que UIA y no el depurador remoto: la app lo bloquea a proposito. En
`app.asar`:

    if (rae(process.argv) && !_9()) process.exit(1)

`rae` busca `--remote-debugging-port` / `--remote-debugging-pipe` y `_9` exige
un `CLAUDE_CDP_AUTH` firmado con Ed25519 que caduca a los 300 s. Sin la clave
privada de Anthropic no hay CDP, y parchear el asar romperia la firma MSIX
ademas de saltarse un control del fabricante. UIA es una API de Windows pensada
exactamente para esto y no requiere saltarse nada.

REGLA DE ORO: de aqui no sale ningun objeto COM. Las funciones publicas
devuelven dataclasses de cadenas y numeros. Ver `hilo.py` para el porque.

SELECTORES: se prefiere siempre lo estructural (rol, patrones soportados,
posicion) sobre el texto, porque el texto esta traducido -- en este PC la app
esta en espanol. Donde no queda mas remedio que mirar texto, la tabla de
palabras esta en un solo sitio (ESTADOS) y lo que no se reconoce se devuelve en
crudo en vez de inventarse un valor.
"""

from __future__ import annotations

import ctypes
import logging
import re
from dataclasses import dataclass
from typing import Any

from . import _dpi  # noqa: F401  se importa por su efecto: ver _dpi.py
from .hilo import en_hilo

log = logging.getLogger("controladora.appctl.uia")

# Ids crudos de UIA: numeros fijos de la API de Windows. Van a mano en vez de
# usar un wrapper (`uiautomation`, `pywinauto`) porque no cambian nunca y una
# dependencia menos es un sitio menos donde romperse.
TS_DESCENDANTS = 4

PROP_BOUNDING_RECT = 30001
PROP_CONTROL_TYPE = 30003
PROP_NAME = 30005
PROP_IS_KEYBOARD_FOCUSABLE = 30009
PROP_IS_OFFSCREEN = 30022
PROP_INVOKE_AVAILABLE = 30031
PROP_TEXT_AVAILABLE = 30040
# El ClassName del nodo. Es lo que identifica al compositor sin depender del
# tipo de control que la app decida exponer (ver _buscar_compositor).
PROP_CLASS_NAME = 30012
# El rol ARIA que Chromium expone del DOM. Vale oro: es la unica propiedad que
# NO esta traducida. "menuitemradio" se llama igual con la app en español que en
# japones, mientras que el nombre del boton cambia entero.
PROP_ARIA_ROLE = 30101

PAT_INVOKE = 10000
PAT_TEXT = 10014

CT_BUTTON = 50000
CT_CHECKBOX = 50002
CT_LISTITEM = 50007
CT_MENUITEM = 50011
CT_RADIOBUTTON = 50013
CT_TEXT = 50020
CT_GROUP = 50026
CT_DOCUMENT = 50030
CT_STATUSBAR = 50017

# Lo que se puede pulsar. No solo Button: cuando la app abre un menu (el selector
# de modelo, el de esfuerzo, el de permisos), sus opciones NO son botones -- son
# RadioButton y MenuItem. Buscar solo botones era lo que hacia que desde el movil
# se pudiera ABRIR el menu pero no elegir nada dentro.
CT_ACCIONABLES = (CT_BUTTON, CT_CHECKBOX, CT_LISTITEM, CT_MENUITEM, CT_RADIOBUTTON)

# El estado de cada sesion viaja DENTRO del nombre del boton de la barra lateral
# ("En ejecución Control Claude app sin terminal"). Esta traducido, asi que la
# tabla vive aqui y solo aqui; anadir un idioma es una linea. Lo que no aparezca
# en la tabla no se adivina: se devuelve el prefijo en crudo y `trabajando` queda
# en None, que significa "no lo se", no "no".
ESTADOS: dict[str, bool] = {
    "en ejecución": True,
    "en ejecucion": True,
    "running": True,
    "inactivo": False,
    "inactive": False,
    "idle": False,
}

# Los nombres de modelo son de producto, no texto traducible: valen igual en
# cualquier idioma de la app.
RE_MODELO = re.compile(r"\b(Opus|Sonnet|Haiku)\b[\w .]*", re.IGNORECASE)

# Los pocos botones que hay que nombrar porque no se pueden localizar por
# estructura (no tienen forma ni sitio fijo que los distinga de sus vecinos).
# Estan TODOS aqui, con sus traducciones, y en ningun otro fichero: esa es la
# regla. Anadir un idioma es anadir una palabra a la tupla que toque.
ETIQUETAS: dict[str, tuple[str, ...]] = {
    "nuevo": ("Nuevo", "New"),
    "inicio": ("Inicio", "Home"),
    "code": ("Code", "Código"),
    "artefactos": ("Artefactos", "Artifacts"),
    "detener": ("Detener", "Stop"),
    "enviar": ("Enviar", "Send"),
}


class SinVentana(Exception):
    """El arbol de accesibilidad no responde para esa ventana."""


@dataclass(frozen=True)
class Mando:
    """Un boton que se puede pulsar, con donde esta en la pantalla.

    El rectangulo va porque el movil lo necesita para dos cosas: dibujar el
    boton nativo en el sitio correcto sobre el video, y poder pulsarlo con un
    clic si algun dia el InvokePattern no funcionase.
    """

    nombre: str
    rect: tuple[int, int, int, int]  # izquierda, arriba, ancho, alto (pantalla)


@dataclass(frozen=True)
class SesionUI:
    """Una sesion tal como se ve en la barra lateral."""

    titulo: str
    estado_crudo: str          # el prefijo tal cual lo pinta la app
    trabajando: bool | None    # None = el prefijo no esta en ESTADOS
    rect: tuple[int, int, int, int]


@dataclass(frozen=True)
class Vista:
    """Todo lo que el movil necesita saber de la app en un instante."""

    texto: str                      # el texto completo de la pantalla
    compositor: str                 # lo que hay escrito en el compositor
    titulo_abierto: str | None      # la sesion que se esta viendo ahora mismo
    modelo: str | None
    uso: str | None                 # "context 216.9k, plan 38%"
    barra: tuple[Mando, ...]        # los mandos que rodean al compositor
    mandos: tuple[Mando, ...]       # todos los botones visibles
    sesiones: tuple[SesionUI, ...]
    # Las opciones de un menu ABIERTO ahora mismo en la app (el selector de
    # modelo, el de esfuerzo...). Vacio casi siempre. Cuando no lo esta, es lo
    # que el movil tiene que enseñar delante de todo: significa que la app esta
    # esperando a que elijas algo y hasta que no elijas no hace nada mas.
    opciones: tuple[Mando, ...] = ()


# --------------------------------------------------------------------------
# fontaneria (solo dentro del hilo de UIA)


_cliente: Any = None


def _c() -> Any:
    global _cliente
    if _cliente is None:
        import comtypes.client

        mod = comtypes.client.GetModule("UIAutomationCore.dll")
        _cliente = comtypes.client.CreateObject(
            mod.CUIAutomation, interface=mod.IUIAutomation
        )
        _cliente._mod = mod
        log.info("cliente UIA creado (mantiene encendido el arbol de Chromium)")
    return _cliente


def _prop(el: Any, pid: int) -> Any:
    try:
        return el.GetCurrentPropertyValue(pid)
    except Exception:
        return None


def _nombre(el: Any) -> str:
    return _prop(el, PROP_NAME) or ""


def _clase(el: Any) -> str:
    return _prop(el, PROP_CLASS_NAME) or ""


def _rect(el: Any) -> tuple[int, int, int, int]:
    r = _prop(el, PROP_BOUNDING_RECT) or (0, 0, 0, 0)
    return int(r[0]), int(r[1]), int(r[2]), int(r[3])


def _texto(el: Any) -> str:
    try:
        tp = el.GetCurrentPattern(PAT_TEXT).QueryInterface(
            _c()._mod.IUIAutomationTextPattern
        )
        return tp.DocumentRange.GetText(-1) or ""
    except Exception:
        return ""


def _elementos(hwnd: int) -> list[Any]:
    raiz = _c().ElementFromHandle(ctypes.c_void_p(hwnd))
    arr = raiz.FindAll(TS_DESCENDANTS, _c().CreateTrueCondition())
    return [arr.GetElement(i) for i in range(arr.Length)]


def _buscar_compositor(els: list[Any]) -> Any | None:
    """El sitio donde se escribe.

    Sin una sola palabra traducible, que es la regla de este modulo. Pero **el
    tipo de control no sirve para identificarlo**, y eso costo caro: durante
    meses esto exigia un `Group` enfocable con TextPattern, y una actualizacion
    de la app lo cambio a un `Edit`. El selector paso a devolver CERO candidatos
    y lo unico que se veia desde fuera era que escribir desde el movil dejaba de
    funcionar, con un "no encuentro el compositor" que no decia por que.

    Lo que SI es estable es de que esta hecho: un editor ProseMirror (ahora
    envuelto en tiptap), y eso sale en el ClassName. No se traduce, no depende
    del tipo de control que la app decida exponer, y distingue el compositor de
    los dos RootWebArea que cubren la ventana entera (ver `_buscar_documento`).

    Se deja el criterio viejo como respaldo: si algun dia el ClassName cambia,
    una version anterior de la app seguira funcionando en vez de morir del todo.
    """
    escribibles = [
        e
        for e in els
        if _prop(e, PROP_IS_KEYBOARD_FOCUSABLE) and _prop(e, PROP_TEXT_AVAILABLE)
    ]

    por_clase = [e for e in escribibles if "prosemirror" in _clase(e).lower()]
    if por_clase:
        if len(por_clase) > 1:
            log.warning("compositor: %d candidatos por clase, se esperaba 1", len(por_clase))
        return por_clase[0]

    # Respaldo: como se buscaba antes de que la app cambiara el tipo de control.
    viejos = [e for e in escribibles if _prop(e, PROP_CONTROL_TYPE) == CT_GROUP]
    if viejos:
        log.info("compositor encontrado por el criterio antiguo (Group), no por ProseMirror")
        return viejos[0]

    return None


def _compositor(hwnd: int, intentos: int = 3) -> Any | None:
    """El compositor, reintentando si el arbol pilla la UI a medio cambiar.

    Visto en la practica: justo despues de abrir una sesion nueva o de enviar,
    hay un instante en que la busqueda devuelve CERO candidatos porque el
    compositor se esta reconstruyendo. Es transitorio y se pasa en decimas, pero
    sin reintento se convierte en un "no encuentro donde escribir" que parece
    grave y no lo es.
    """
    import time

    for i in range(intentos):
        comp = _buscar_compositor(_elementos(hwnd))
        if comp is not None:
            return comp
        if i + 1 < intentos:
            time.sleep(0.4)
    log.error("no aparece el compositor tras %d intentos", intentos)
    return None


def _buscar_documento(els: list[Any]) -> Any | None:
    """El documento con el texto de la pantalla.

    Hay DOS RootWebArea y uno esta vacio (es un marco). Se coge el que mas texto
    tiene: coger el primero da "1 caracter" y parece que la lectura no funciona.
    """
    mejor, mejor_len = None, 0
    for e in els:
        if _prop(e, PROP_CONTROL_TYPE) != CT_DOCUMENT:
            continue
        n = len(_texto(e))
        if n > mejor_len:
            mejor, mejor_len = e, n
    return mejor


# --------------------------------------------------------------------------
# API publica (cada una salta al hilo de UIA por su cuenta)


def despertar(hwnd: int, intentos: int = 10) -> int:
    """Enciende el arbol de accesibilidad y devuelve cuantos nodos hay.

    Chromium no lo construye hasta que un cliente UIA pregunta, y el encendido
    es asincrono: la primera pasada devuelve la ventana pelada (marco y botones
    de la barra de titulo) y el contenido web aparece un momento despues. Medido
    en este PC: 14 nodos -> ~990.
    """

    def _trabajo() -> int:
        import time

        n = 0
        for _ in range(intentos):
            try:
                n = len(_elementos(hwnd))
            except Exception as e:
                raise SinVentana(f"{type(e).__name__}: {e}") from e
            if n > 50:
                return n
            time.sleep(0.6)
        return n

    return en_hilo(_trabajo)


def vista(hwnd: int, titulos: tuple[str, ...] = ()) -> Vista:
    """Una foto de la app: texto, mandos y estado de cada sesion.

    [titulos] son los titulos de sesion leidos del indice en disco
    (`sessions.titulos()`). Hacen falta para poder partir el nombre del boton de
    la barra lateral: se llama "<estado traducido> <titulo>" y el titulo del
    disco NO esta traducido, asi que casar por el final es la unica forma fiable
    de separar los dos trozos sin adivinar el idioma.
    """

    def _trabajo() -> Vista:
        els = _elementos(hwnd)

        doc = _buscar_documento(els)
        comp = _buscar_compositor(els)  # sin reintento: aqui vale devolver "" si no esta

        # Solo los botones en pantalla: la barra lateral tiene decenas de
        # sesiones fuera de vista, y un boton que no se ve no se puede pulsar.
        botones = [
            e
            for e in els
            if _prop(e, PROP_CONTROL_TYPE) == CT_BUTTON
            and _nombre(e)
            and not _prop(e, PROP_IS_OFFSCREEN)
        ]
        mandos = tuple(Mando(_nombre(e), _rect(e)) for e in botones)

        # Los mandos de la sesion (parar, modelo, esfuerzo, uso...) son los que
        # rodean al compositor: unos a su derecha, a la misma altura, y otros en
        # la fila de debajo. Se localizan por geometria y no por nombre, porque
        # "Esfuerzo: Alto" esta traducido y estar al lado no.
        #
        # Los margenes no son redondeos al tuntun: el boton de uso de tokens cae
        # unos pixeles POR FUERA del borde derecho del compositor, y con un
        # recorte ajustado al borde se quedaba fuera de la lista. Mas vale que
        # sobre un boton vecino que perder el unico sitio donde se ve cuanto
        # contexto queda.
        barra: tuple[Mando, ...] = ()
        if comp is not None:
            ci, ca, cw, ch = _rect(comp)
            barra = tuple(
                m
                for m in mandos
                if ca - 10 <= m.rect[1] <= ca + ch + 60
                and ci - 20 <= m.rect[0] <= ci + cw + 140
            )

        modelo = next(
            (m.nombre for m in barra if RE_MODELO.search(m.nombre)),
            None,
        )
        uso = next((m.nombre for m in barra if "%" in m.nombre), None)

        sesiones: list[SesionUI] = []
        for titulo in titulos:
            if not titulo:
                continue
            m = next((m for m in mandos if m.nombre.endswith(titulo)), None)
            if m is None:
                continue  # esa sesion esta fuera de la vista de la barra lateral
            prefijo = m.nombre[: -len(titulo)].strip()
            sesiones.append(
                SesionUI(
                    titulo=titulo,
                    estado_crudo=prefijo,
                    trabajando=ESTADOS.get(prefijo.lower()),
                    rect=m.rect,
                )
            )

        # Cual de todas es la que se esta VIENDO. Se distingue por una diferencia
        # limpia: el boton de la cabecera lleva el titulo pelado, mientras que los
        # de la barra lateral lo llevan con el estado delante ("En ejecución X").
        # Asi que el unico boton cuyo nombre coincide EXACTAMENTE con un titulo
        # del indice es el de la cabecera.
        #
        # Hace falta de verdad, no es un adorno: sin esto, "la sesion activa" se
        # deducia de cual se toco mas recientemente, y eso se equivoca justo
        # cuando importa -- al abrir una sesion nueva (que aun no existe en el
        # indice) o teniendo otra corriendo en segundo plano.
        conocidos = set(titulos)
        titulo_abierto = next((m.nombre for m in mandos if m.nombre in conocidos), None)

        # Un menu abierto. Se detecta por el ROL ARIA y no por el tipo de UIA ni
        # por el nombre: los tres sabores ("menuitem", "menuitemradio",
        # "menuitemcheckbox") vienen del DOM y NO estan traducidos, mientras que
        # el nombre del elemento si ("Activar el modo rápido"). Medido abriendo
        # el selector de modelo: salen cuatro `menuitemradio` con los modelos,
        # un `menuitem` de "Más modelos" y un `menuitemcheckbox` del modo rapido.
        opciones = tuple(
            Mando(_nombre(e), _rect(e))
            for e in els
            if str(_prop(e, PROP_ARIA_ROLE) or "").startswith("menuitem")
            and _nombre(e)
            and not _prop(e, PROP_IS_OFFSCREEN)
        )

        return Vista(
            texto=_texto(doc) if doc is not None else "",
            compositor=_texto(comp) if comp is not None else "",
            titulo_abierto=titulo_abierto,
            modelo=modelo,
            uso=uso,
            barra=barra,
            mandos=mandos,
            sesiones=tuple(sesiones),
            opciones=opciones,
        )

    return en_hilo(_trabajo)


def texto_compositor(hwnd: int) -> str:
    """Lo que hay escrito ahora mismo en el compositor.

    Se consulta suelto (y no por `vista`) porque es lo que se comprueba entre
    teclear y pulsar Enter, y ahi interesa que sea barato y rapido.
    """

    def _trabajo() -> str:
        comp = _compositor(hwnd)
        return _texto(comp) if comp is not None else ""

    return en_hilo(_trabajo)


def enfocar_compositor(hwnd: int) -> bool:
    """Pone el foco en el compositor, trayendo la ventana al frente.

    Traer la ventana al frente NO es opcional: esta medido a la contra que con
    otra ventana delante los WM_CHAR que manda `input.py` se pierden en silencio,
    sin error ninguno. Y `SetFocus()` de UIA es mejor via que
    `SetForegroundWindow` porque la peticion la ejecuta el proceso de Claude
    sobre si mismo, asi que no cae en la proteccion de Windows contra robos de
    foco entre procesos (medido: contra un juego a pantalla completa, la de
    Win32 falla y esta no).

    Devuelve si de verdad quedo enfocado, no si la llamada no reviento.
    """

    def _trabajo() -> bool:
        import time

        import win32gui

        comp = _compositor(hwnd)
        if comp is None:
            log.error("no encuentro el compositor: no se puede enfocar")
            return False
        try:
            comp.SetFocus()
        except Exception as e:
            log.warning("SetFocus fallo: %s: %s", type(e).__name__, e)
            return False

        for _ in range(20):
            if win32gui.GetForegroundWindow() == hwnd:
                return True
            time.sleep(0.05)
        return False

    return en_hilo(_trabajo)


def buscar_mando(hwnd: int, nombre: str, por_el_final: bool = False) -> Mando | None:
    """El boton que se llame asi, si esta EN PANTALLA. Datos planos, no COM.

    [por_el_final]: casar por el final del nombre en vez de exacto. Es lo que
    hace falta para las sesiones, cuyo boton se llama "<estado> <titulo>".
    """

    def _trabajo() -> Mando | None:
        for e in _elementos(hwnd):
            if _prop(e, PROP_CONTROL_TYPE) not in CT_ACCIONABLES:
                continue
            n = _nombre(e)
            if not (n.endswith(nombre) if por_el_final else n == nombre):
                continue
            if _prop(e, PROP_IS_OFFSCREEN):
                log.warning("el boton %r esta fuera de la vista", n)
                return None
            return Mando(n, _rect(e))
        return None

    return en_hilo(_trabajo)


def pulsar(hwnd: int, nombre: str, por_el_final: bool = False) -> bool:
    """Activa el boton por su patron de UIA. Devuelve si de verdad se pulso.

    Se prefiere InvokePattern a un clic con el raton: es lo que la propia app
    expone como "activar esto", no depende de que el boton este tapado por otra
    ventana ni de mover el cursor del usuario, y no necesita traer la ventana al
    primer plano.

    Pero NO todos los botones lo tienen. Medido: el de uso de tokens ("Usage:
    context 42%, plan 75%") no lo soporta, y `GetCurrentPattern` devuelve un
    puntero COM nulo en vez de fallar limpiamente -- el error que sale entonces
    es "NULL COM pointer access", que no dice absolutamente nada de lo que pasa.
    Por eso se pregunta ANTES si el patron esta disponible: asi se distingue "no
    se puede invocar, habra que hacer clic" de "se ha roto algo". El clic de
    respaldo lo pone `input.pulsar`, que es quien sabe mandar eventos a la
    ventana.
    """

    def _trabajo() -> bool:
        for e in _elementos(hwnd):
            if _prop(e, PROP_CONTROL_TYPE) not in CT_ACCIONABLES:
                continue
            n = _nombre(e)
            if not (n.endswith(nombre) if por_el_final else n == nombre):
                continue
            if _prop(e, PROP_IS_OFFSCREEN):
                log.warning("el boton %r esta fuera de la vista: no se pulsa", n)
                return False
            if not _prop(e, PROP_INVOKE_AVAILABLE):
                log.info("%r no soporta InvokePattern: tendra que ir por clic", n)
                return False
            try:
                pat = e.GetCurrentPattern(PAT_INVOKE).QueryInterface(
                    _c()._mod.IUIAutomationInvokePattern
                )
                pat.Invoke()
                log.info("pulsado %r", n)
                return True
            except Exception as ex:
                log.error("no pude pulsar %r: %s: %s", n, type(ex).__name__, ex)
                return False
        return False

    return en_hilo(_trabajo)


def pulsar_conocido(hwnd: int, clave: str) -> bool:
    """Pulsa uno de los botones de ETIQUETAS, probando todos sus idiomas.

    Existe para que ningun otro fichero tenga que escribir "Nuevo" a mano: si
    manana la app aparece en ingles, se anade la palabra a la tabla y todo lo
    demas sigue funcionando sin tocarse.
    """
    nombres = ETIQUETAS.get(clave)
    if not nombres:
        raise KeyError(f"etiqueta desconocida: {clave!r}. Conocidas: {sorted(ETIQUETAS)}")
    for n in nombres:
        if pulsar(hwnd, n):
            return True
    log.warning("no encontre el boton %r (probe %s)", clave, list(nombres))
    return False
