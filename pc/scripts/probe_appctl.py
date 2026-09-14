"""Sondas de la Fase A: se puede pilotar la app de escritorio de Claude?

    python scripts/probe_appctl.py                     # solo mira, no toca nada
    python scripts/probe_appctl.py --enviar "hola"     # ADEMAS escribe y envia

Esto NO es parte del servicio: es el banco de pruebas que decide si la capa
`controladora/appctl/` se puede construir sobre suposiciones ciertas. Cada sonda
comprueba UNA cosa y dice OK o FALLO por separado, porque el modo de fallar
importa: que no aparezca el compositor y que no se pueda traer la ventana al
frente son dos problemas distintos con dos arreglos distintos, y un "no funciona"
global no distingue cual de los dos ha pasado.

Por que hace falta esto y no se ataca por la via comoda: la app BLOQUEA el
depurador remoto a proposito. En `app.asar` hay literalmente

    if (rae(process.argv) && !_9()) process.exit(1)

donde `rae` busca `--remote-debugging-port` / `--remote-debugging-pipe` en la
linea de comandos y `_9` exige un token `CLAUDE_CDP_AUTH` firmado con Ed25519
(clave publica incrustada, caduca a los 300 s). No hay CDP sin la clave privada
de Anthropic, y parchear el asar no es una opcion: rompe la firma MSIX y es
saltarse un control del fabricante. Queda la accesibilidad de Windows, que es
una API pensada exactamente para esto.

LO QUE YA SE SABE, medido con estas sondas (no supuesto):

- El arbol de accesibilidad de Chromium esta apagado hasta que un cliente UIA
  pregunta. Al encenderlo pasa de 14 nodos a ~900.
- El compositor es un contenteditable, asi que NO tiene ValuePattern: no se le
  puede asignar el texto, hay que teclearlo.
- Teclear con PostMessage(WM_CHAR) funciona, respeta acentos y simbolos, y no
  toca ni el portapapeles ni el teclado fisico... **pero solo si la ventana esta
  en primer plano**. Comprobado a la contra: con otra ventana delante y sin
  tocar el foco, los WM_CHAR se pierden en silencio. O sea que traer la ventana
  al frente NO es opcional.
- Para traerla al frente, `elemento.SetFocus()` de UIA es mas fiable que
  `SetForegroundWindow`: la peticion sale de la propia app, asi que Windows no
  la bloquea. La sonda 4 prueba las dos y dice cual funciona aqui.

Las sondas 1-6 son de solo lectura salvo la 4, que trae la ventana al frente y
devuelve el foco. La 7 solo corre con --enviar, y es la unica que escribe.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Antes de tocar UIA o de leer un solo rectangulo. Sin esto Windows miente en las
# coordenadas de un PC con escalado: devuelve pixeles "logicos" y los clics
# acaban desplazados respecto a lo que se ve. Solo se puede fijar una vez por
# proceso, y tiene que ser antes de que nadie pregunte nada.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE_V2
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import win32api  # noqa: E402
import win32con  # noqa: E402
import win32gui  # noqa: E402
import win32process  # noqa: E402

import comtypes.client  # noqa: E402

# Ids crudos de UIA. Van a mano y no por un wrapper (`uiautomation`, `pywinauto`)
# a proposito: son numeros fijos de la API de Windows, no cambian nunca, y una
# dependencia menos es un sitio menos donde romperse cuando esto acabe dentro
# del servicio.
TS_DESCENDANTS = 4

PROP_BOUNDING_RECT = 30001
PROP_CONTROL_TYPE = 30003
PROP_NAME = 30005
PROP_IS_KEYBOARD_FOCUSABLE = 30009
PROP_AUTOMATION_ID = 30011
PROP_IS_OFFSCREEN = 30022
PROP_TEXT_AVAILABLE = 30040

PAT_TEXT = 10014

CT_BUTTON = 50000
CT_TEXT = 50020
CT_GROUP = 50026
CT_DOCUMENT = 50030
CT_STATUSBAR = 50017

CT = {
    CT_BUTTON: "Button",
    50004: "Edit",
    50006: "Image",
    50007: "ListItem",
    50008: "List",
    CT_STATUSBAR: "StatusBar",
    CT_TEXT: "Text",
    50021: "ToolBar",
    CT_GROUP: "Group",
    CT_DOCUMENT: "Document",
    50032: "Window",
    50033: "Pane",
}

WM_KEYDOWN, WM_KEYUP, WM_CHAR = 0x100, 0x101, 0x102

# Carpeta del paquete MSIX. El nombre lleva el hash del publicador, que es
# estable para una misma firma: sirve para distinguir la app de escritorio de
# cualquier otra ventana de Chromium (Chrome, Edge, otro Electron) sin depender
# del titulo, que esta traducido y cambia con la sesion abierta.
PAQUETE = "windowsapps\\claude_"
CLASE_VENTANA = "Chrome_WidgetWin_1"
CLASE_RENDER = "Chrome_RenderWidgetHostHWND"

APPDATA = Path(win32api.GetEnvironmentVariable("APPDATA") or "")
INDICE_SESIONES = APPDATA / "Claude" / "claude-code-sessions"
PROYECTOS = Path.home() / ".claude" / "projects"


# --------------------------------------------------------------------------
# utilidades


class Resultado:
    """Marcador de OK/FALLO por sonda. Se imprime al final todo junto.

    Existe para que una sonda que falla no impida ejecutar las siguientes: lo
    que se quiere saber de una tacada es QUE funciona y que no, no el primer
    error y a casa.
    """

    def __init__(self) -> None:
        self.filas: list[tuple[str, bool, str]] = []

    def ok(self, sonda: str, detalle: str = "") -> None:
        self.filas.append((sonda, True, detalle))
        print(f"  OK    {detalle}" if detalle else "  OK")

    def fallo(self, sonda: str, detalle: str) -> None:
        self.filas.append((sonda, False, detalle))
        print(f"  FALLO {detalle}")

    def resumen(self) -> int:
        print("\n" + "=" * 78)
        for sonda, ok, detalle in self.filas:
            print(f"{'OK   ' if ok else 'FALLO'}  {sonda:<22} {detalle}")
        malas = [f for f in self.filas if not f[1]]
        print("=" * 78)
        if malas:
            print(f"{len(malas)} de {len(self.filas)} sondas han fallado.")
            return 1
        print(f"Las {len(self.filas)} sondas pasan.")
        return 0


_uia: Any = None


def uia() -> Any:
    """El cliente de UI Automation, creado una sola vez.

    Se cachea porque no es solo eficiencia: mientras haya un cliente UIA vivo,
    Chromium mantiene encendido su arbol de accesibilidad. Si se crea y se tira
    en cada consulta, el arbol se apaga y la siguiente vuelve a ver la ventana
    pelada. En el servicio, este objeto tendra que vivir tanto como el proceso.
    """
    global _uia
    if _uia is None:
        mod = comtypes.client.GetModule("UIAutomationCore.dll")
        _uia = comtypes.client.CreateObject(mod.CUIAutomation, interface=mod.IUIAutomation)
        _uia._mod = mod
    return _uia


def prop(el: Any, pid: int) -> Any:
    try:
        return el.GetCurrentPropertyValue(pid)
    except Exception:
        return None


def tipo(el: Any) -> str:
    return CT.get(prop(el, PROP_CONTROL_TYPE), str(prop(el, PROP_CONTROL_TYPE)))


def nombre(el: Any) -> str:
    return prop(el, PROP_NAME) or ""


def descendientes(el: Any) -> list[Any]:
    arr = el.FindAll(TS_DESCENDANTS, uia().CreateTrueCondition())
    return [arr.GetElement(i) for i in range(arr.Length)]


def texto_de(el: Any) -> str:
    """El texto de un elemento via TextPattern, o "" si no lo soporta."""
    try:
        tp = el.GetCurrentPattern(PAT_TEXT).QueryInterface(
            uia()._mod.IUIAutomationTextPattern
        )
        return tp.DocumentRange.GetText(-1) or ""
    except Exception:
        return ""


# --------------------------------------------------------------------------
# sonda 1 — la ventana


def sonda_ventana(r: Resultado) -> tuple[int, int] | None:
    print("\n[1] Localizar la ventana de la app de escritorio")

    encontradas: list[tuple[int, str, int]] = []

    def visita(hwnd: int, _: Any) -> bool:
        if win32gui.GetClassName(hwnd) != CLASE_VENTANA:
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            h = win32api.OpenProcess(
                win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            ruta = win32process.GetModuleFileNameEx(h, 0)
            win32api.CloseHandle(h)
        except Exception:
            return True
        if PAQUETE in ruta.lower():
            encontradas.append((hwnd, win32gui.GetWindowText(hwnd), pid))
        return True

    win32gui.EnumWindows(visita, None)

    if not encontradas:
        r.fallo("1 ventana", "la app no esta abierta (o no tiene ventana)")
        return None

    for hwnd, titulo, pid in encontradas:
        estado = "visible" if win32gui.IsWindowVisible(hwnd) else "oculta"
        if win32gui.IsIconic(hwnd):
            estado += " MINIMIZADA"
        print(f"      hwnd={hwnd} pid={pid} titulo={titulo!r} {estado}")

    # La buena es la que tiene titulo: las otras Chrome_WidgetWin_1 del proceso
    # son ventanas auxiliares de Chromium (menus, tooltips) sin contenido.
    con_titulo = [e for e in encontradas if e[1]]
    if not con_titulo:
        r.fallo("1 ventana", "hay ventanas del paquete pero ninguna con titulo")
        return None

    hwnd = con_titulo[0][0]

    # El hijo que recibe teclado y raton. Es al que hay que mandarle los
    # mensajes: la ventana de arriba es solo el marco.
    hijos: list[tuple[int, str]] = []
    win32gui.EnumChildWindows(
        hwnd, lambda h, _: hijos.append((h, win32gui.GetClassName(h))) or True, None
    )
    render = next((h for h, c in hijos if c == CLASE_RENDER), 0)
    if not render:
        r.fallo("1 ventana", f"hwnd={hwnd} pero sin {CLASE_RENDER}: no hay donde teclear")
        return None

    r.ok("1 ventana", f"hwnd={hwnd} render={render} {con_titulo[0][1]!r}")
    return hwnd, render


# --------------------------------------------------------------------------
# sonda 2 — despertar el arbol de accesibilidad


def sonda_uia(r: Resultado, hwnd: int) -> Any | None:
    print("\n[2] Despertar el arbol de accesibilidad de Chromium")
    print("      (no lo construye hasta que alguien pregunta: la primera consulta")
    print("       lo enciende y tarda un momento en llenarse)")

    try:
        win = uia().ElementFromHandle(ctypes.c_void_p(hwnd))
    except Exception as e:
        r.fallo("2 arbol UIA", f"ElementFromHandle reviento: {type(e).__name__}: {e}")
        return None

    n = 0
    for intento in range(10):
        n = len(descendientes(win))
        print(f"      intento {intento + 1}: {n} nodos")
        if n > 50:
            break
        time.sleep(0.6)

    if n <= 50:
        r.fallo("2 arbol UIA", f"solo {n} nodos: el contenido web no se expone")
        return None

    r.ok("2 arbol UIA", f"{n} nodos")
    return win


# --------------------------------------------------------------------------
# sonda 3 — las piezas que hacen falta para pilotar


def sonda_piezas(r: Resultado, win: Any) -> dict[str, Any]:
    print("\n[3] Localizar las piezas: documento, compositor, mandos, estado")

    piezas: dict[str, Any] = {}
    todos = descendientes(win)
    piezas["todos"] = todos

    # --- el documento del que sale el texto de toda la pantalla.
    #
    # Hay DOS RootWebArea y uno esta vacio (es un marco). Se coge el que mas
    # texto tiene, no el primero: coger el primero fue el bug de la primera
    # version de esta sonda, que informaba alegremente de "1 caracter legible".
    docs = [e for e in todos if prop(e, PROP_CONTROL_TYPE) == CT_DOCUMENT]
    mejor, mejor_len = None, 0
    for d in docs:
        n = len(texto_de(d))
        print(f"      Document autoid={prop(d, PROP_AUTOMATION_ID)!r} texto={n} chars")
        if n > mejor_len:
            mejor, mejor_len = d, n
    if mejor is None or mejor_len < 100:
        r.fallo("3 documento", f"ningun Document con texto util (mejor={mejor_len})")
    else:
        piezas["doc"] = mejor
        r.ok("3 documento", f"{mejor_len} caracteres legibles")

    # --- el compositor: el sitio donde se escribe.
    #
    # No es un <input>, es un contenteditable, asi que UIA lo expone como Group
    # y NO tiene ValuePattern: no se le puede asignar el texto, hay que teclear.
    # El selector es estructural y no depende del idioma: Group + enfocable por
    # teclado + con TextPattern. En esta app da exactamente un candidato. El
    # nombre ("Instrucciones") se imprime como pista, pero no se usa para elegir:
    # esta traducido y cambiaria con el idioma de la app.
    candidatos = [
        e
        for e in todos
        if prop(e, PROP_CONTROL_TYPE) == CT_GROUP
        and prop(e, PROP_IS_KEYBOARD_FOCUSABLE)
        and prop(e, PROP_TEXT_AVAILABLE)
    ]
    print(f"      candidatos a compositor: {[nombre(e) for e in candidatos]}")
    if len(candidatos) != 1:
        r.fallo("3 compositor", f"{len(candidatos)} candidatos, se esperaba 1")
    else:
        piezas["compositor"] = candidatos[0]
        r.ok("3 compositor", f"{nombre(candidatos[0])!r} texto={texto_de(candidatos[0])!r}")

    # --- los mandos: de aqui sale la botonera nativa del movil.
    #
    # Se listan los que estan EN PANTALLA: la barra lateral tiene decenas de
    # sesiones fuera de vista, y un boton que no se ve no se puede pulsar.
    botones = [
        (nombre(e), e)
        for e in todos
        if prop(e, PROP_CONTROL_TYPE) == CT_BUTTON
        and nombre(e)
        and not prop(e, PROP_IS_OFFSCREEN)
    ]
    piezas["botones"] = botones
    if not botones:
        r.fallo("3 mandos", "no hay botones visibles con nombre")
    else:
        # Los interesantes para el movil, buscados por lo que son y no por como
        # se llaman: el modelo y el esfuerzo estan junto al compositor.
        cerca = [n for n, _ in botones if any(
            p in n for p in ("Opus", "Sonnet", "Haiku", "Esfuerzo", "Usage", "Detener")
        )]
        r.ok("3 mandos", f"{len(botones)} visibles; de sesion: {cerca}")

    # --- estado del turno: para que el movil sepa si Claude esta trabajando
    estados = [
        nombre(e)
        for e in todos
        if prop(e, PROP_CONTROL_TYPE) in (CT_TEXT, CT_STATUSBAR) and nombre(e)
    ]
    vivos = [t for t in estados if "respond" in t.lower() or "ejecu" in t.lower()]
    # No es un fallo que no haya nada: si Claude esta parado, no hay turno que
    # leer. Se dice cual de los dos casos es, para no confundirlo con un fallo.
    r.ok("3 estado", f"turno en curso: {vivos[:2]}" if vivos else "sin turno ahora mismo")

    return piezas


def sonda_sidebar(r: Resultado, piezas: dict[str, Any], sesiones: list[dict[str, Any]]) -> None:
    """Casar las sesiones del disco con los botones de la barra lateral.

    Esto es lo que permite que tocar una sesion en el movil pulse la de verdad en
    el PC. El nombre del boton es "<estado traducido> <titulo>" ("En ejecucion
    Control Claude app sin terminal"), asi que se casa por el FINAL: el titulo
    viene del indice en disco y no esta traducido, el prefijo si.
    """
    print("\n[3b] Casar las sesiones del disco con los botones de la barra lateral")

    botones = piezas.get("botones") or []
    if not botones or not sesiones:
        r.fallo("3b sidebar", "faltan botones o sesiones para casar")
        return

    casadas = 0
    for s in sesiones[:8]:
        titulo = (s.get("title") or "").strip()
        if not titulo:
            continue
        b = next((n for n, _ in botones if n.endswith(titulo)), None)
        if b:
            casadas += 1
            prefijo = b[: -len(titulo)].strip()
            print(f"      OK  {titulo!r} -> boton con estado {prefijo!r}")
        else:
            print(f"      --  {titulo!r} no esta en pantalla (barra lateral desplazada)")

    if casadas:
        r.ok("3b sidebar", f"{casadas} sesiones casadas con su boton")
    else:
        r.fallo("3b sidebar", "ninguna sesion del disco aparece en la barra lateral")


# --------------------------------------------------------------------------
# sonda 4 — traer la ventana al frente


def _al_frente_win32(hwnd: int) -> bool:
    """SetForegroundWindow con el apanio de AttachThreadInput.

    Windows no deja que un proceso cualquiera robe el foco: SetForegroundWindow
    falla en silencio si el que llama no es ya el proceso en primer plano. El
    apanio conocido es engancharse a la cola de entrada del hilo que SI lo tiene.
    Se desengancha siempre, pase lo que pase.
    """
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    if win32gui.GetForegroundWindow() == hwnd:
        return True

    delante = win32gui.GetForegroundWindow()
    suyo = win32process.GetWindowThreadProcessId(delante)[0] if delante else 0
    nuestro = win32api.GetCurrentThreadId()

    enganchado = False
    try:
        if suyo and suyo != nuestro:
            enganchado = bool(
                ctypes.windll.user32.AttachThreadInput(nuestro, suyo, True)
            )
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    finally:
        if enganchado:
            ctypes.windll.user32.AttachThreadInput(nuestro, suyo, False)

    for _ in range(20):
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.05)
    return False


def _al_frente_uia(hwnd: int, compositor: Any) -> bool:
    """Traer la ventana al frente pidiendoselo a la propia app, via UIA.

    Mas fiable que SetForegroundWindow: la peticion la ejecuta el proceso de
    Claude sobre si mismo, asi que no cae en la proteccion de Windows contra
    robos de foco entre procesos. Ademas deja el foco DENTRO del compositor, que
    es lo que de verdad hace falta para que los WM_CHAR lleguen a su sitio.
    """
    try:
        compositor.SetFocus()
    except Exception:
        return False
    for _ in range(20):
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.05)
    return False


def sonda_foco(r: Resultado, hwnd: int, piezas: dict[str, Any]) -> None:
    print("\n[4] Traer la ventana al frente (las dos vias) y devolver el foco")

    antes = win32gui.GetForegroundWindow()
    print(f"      estaba delante: {antes} {win32gui.GetWindowText(antes)!r}")

    via_win32 = _al_frente_win32(hwnd)
    print(f"      SetForegroundWindow: {'OK' if via_win32 else 'NO'}")

    # Se devuelve el foco entre las dos pruebas para que la segunda parta de la
    # misma situacion que la primera: si no, la via UIA lo tendria regalado.
    if antes and antes != hwnd and via_win32:
        _al_frente_win32(antes)
        time.sleep(0.3)

    compositor = piezas.get("compositor")
    via_uia = _al_frente_uia(hwnd, compositor) if compositor is not None else False
    print(f"      UIA SetFocus():      {'OK' if via_uia else 'NO'}")

    if antes and antes != hwnd:
        _al_frente_win32(antes)
        vuelto = win32gui.GetForegroundWindow() == antes
        print(f"      foco devuelto a la ventana anterior: {'OK' if vuelto else 'NO'}")

    if via_uia or via_win32:
        cual = "UIA" if via_uia else "SetForegroundWindow"
        r.ok("4 primer plano", f"funciona por {cual} (win32={via_win32}, uia={via_uia})")
    else:
        r.fallo(
            "4 primer plano",
            "ninguna via funciona: con esto NO se puede teclear "
            "(hay una app a pantalla completa delante?)",
        )


# --------------------------------------------------------------------------
# sonda 5 — las sesiones y su transcripcion en disco


def _indice_sesiones() -> list[dict[str, Any]]:
    """Las sesiones del escritorio, leidas de su propio indice en disco.

    `%APPDATA%\\Claude\\claude-code-sessions\\<cuenta>\\<dispositivo>\\local_*.json`
    mapea la sesion que se ve en la barra lateral con el `cliSessionId`, que es
    el nombre del fichero de transcripcion. Sin este indice habria que adivinar
    cual de los .jsonl corresponde a lo que tienes abierto.
    """
    if not INDICE_SESIONES.is_dir():
        return []
    out = []
    for f in INDICE_SESIONES.rglob("local_*.json"):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return sorted(out, key=lambda s: s.get("lastActivityAt", 0), reverse=True)


def _transcripcion(cli_session_id: str, cwd: str) -> Path | None:
    """El .jsonl de una sesion.

    El nombre de la carpeta es el cwd con los dos puntos y las barras convertidos
    en guiones ("E:\\App" -> "E--App"). Se construye el esperado, pero si no
    aparece se busca por todo el arbol: esa regla es de Claude Code, no nuestra,
    y no conviene depender de haberla deducido bien.
    """
    esperado = PROYECTOS / cwd.replace(":", "-").replace("\\", "-").replace("/", "-")
    directo = esperado / f"{cli_session_id}.jsonl"
    if directo.exists():
        return directo
    for f in PROYECTOS.rglob(f"{cli_session_id}.jsonl"):
        return f
    return None


def _mensajes(jsonl: Path, desde: int = 0, n: int | None = None) -> list[str]:
    """Los mensajes del transcript, como los pintaria el movil.

    [desde] es un desplazamiento en bytes: leer solo lo nuevo es exactamente lo
    que hara el servicio para el streaming, asi que se prueba asi desde ya.
    """
    with jsonl.open("r", encoding="utf-8", errors="replace") as f:
        f.seek(desde)
        lineas = f.read().splitlines()

    out: list[str] = []
    for linea in lineas:
        try:
            o = json.loads(linea)
        except Exception:
            continue
        if o.get("type") not in ("user", "assistant") or o.get("isSidechain"):
            continue  # los subagentes no van al chat principal

        contenido = (o.get("message") or {}).get("content") or []
        # Un mensaje del usuario puede traer el texto pelado en vez de la lista
        # de bloques. Los dos formatos conviven en el mismo fichero, asi que hay
        # que aceptar los dos: dar por hecho que siempre es una lista fue lo que
        # reviento la primera version de esta funcion.
        if isinstance(contenido, str):
            contenido = [{"type": "text", "text": contenido}]

        for b in contenido:
            if isinstance(b, str):
                b = {"type": "text", "text": b}
            t = b.get("type")
            if t == "text" and b.get("text", "").strip():
                out.append(f"{o['type']}: {b['text'].strip()}")
            elif t == "tool_use":
                out.append(f"{o['type']}: [tool {b.get('name')}]")
            elif t == "thinking":
                out.append(f"{o['type']}: [pensando]")
    return out[-n:] if n else out


def sonda_sesiones(r: Resultado) -> dict[str, Any] | None:
    print("\n[5] Leer las sesiones y su transcripcion desde disco")

    sesiones = _indice_sesiones()
    if not sesiones:
        r.fallo("5 sesiones", f"no hay indice en {INDICE_SESIONES}")
        return None

    print(f"      {len(sesiones)} sesiones en el indice. Las 3 mas recientes:")
    for s in sesiones[:3]:
        print(
            f"        {s.get('title')!r} cwd={s.get('cwd')} "
            f"modelo={s.get('model')} esfuerzo={s.get('effort')} "
            f"modo={s.get('permissionMode')}"
        )

    activa = sesiones[0]
    jsonl = _transcripcion(activa.get("cliSessionId", ""), activa.get("cwd", ""))
    if jsonl is None:
        r.fallo("5 sesiones", f"no aparece el .jsonl de {activa.get('cliSessionId')}")
        return None

    tam = jsonl.stat().st_size
    print(f"      transcripcion: {jsonl.name} ({tam} bytes)")
    print("      ultimos mensajes tal como los pintaria el movil:")
    for m in _mensajes(jsonl, n=5):
        print(f"        {m[:100]}")

    r.ok("5 sesiones", f"{len(sesiones)} sesiones, transcript de {tam} bytes")
    return {"sesiones": sesiones, "activa": activa, "jsonl": jsonl}


# --------------------------------------------------------------------------
# sonda 6 — capturar la ventana, y a que velocidad


def _capturar(hwnd: int) -> Any:
    """Una captura de la ventana con PrintWindow. Devuelve una imagen PIL."""
    import win32ui
    from PIL import Image

    izq, arriba, der, abajo = win32gui.GetWindowRect(hwnd)
    ancho, alto = der - izq, abajo - arriba

    dc_ventana = win32gui.GetWindowDC(hwnd)
    dc = win32ui.CreateDCFromHandle(dc_ventana)
    dc_mem = dc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(dc, ancho, alto)
    dc_mem.SelectObject(bmp)
    try:
        # PW_RENDERFULLCONTENT (2): sin esto, una ventana compuesta por GPU como
        # Chromium sale en negro.
        ok = ctypes.windll.user32.PrintWindow(hwnd, dc_mem.GetSafeHdc(), 2)
        info = bmp.GetInfo()
        img = Image.frombuffer(
            "RGB",
            (info["bmWidth"], info["bmHeight"]),
            bmp.GetBitmapBits(True),
            "raw",
            "BGRX",
            0,
            1,
        )
        return ok, img
    finally:
        dc_mem.DeleteDC()
        dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, dc_ventana)
        win32gui.DeleteObject(bmp.GetHandle())


def sonda_captura(r: Resultado, hwnd: int) -> None:
    print("\n[6] Capturar la ventana, y medir a cuantos fps se puede")

    try:
        ok, img = _capturar(hwnd)
    except Exception as e:
        r.fallo("6 captura", f"{type(e).__name__}: {e}")
        return

    print(f"      ventana {img.width}x{img.height}, PrintWindow devolvio {ok}")

    # Cuanto de la imagen NO es negro. Una captura fallida de Chromium sale negra
    # entera: la unica forma honesta de saber si "funciono" es mirarla.
    pequena = img.resize((160, 100))
    pixeles = list(pequena.getdata())
    pct = 100 * sum(1 for p in pixeles if sum(p) > 24) / len(pixeles)

    destino = Path(__file__).resolve().parent.parent / "artifacts"
    destino.mkdir(exist_ok=True)
    salida = destino / "probe_captura.png"
    img.save(salida)
    print(f"      guardada en {salida}; contenido no negro: {pct:.1f}%")

    if not (ok and pct > 5):
        r.fallo(
            "6 captura",
            f"PrintWindow no sirve ({pct:.0f}% con contenido): hara falta "
            "Windows Graphics Capture",
        )
        return

    # El plan pide 30 fps. Medirlo ahora evita construir la Fase D encima de una
    # via de captura que no da la talla: si esto sale a 8 fps, hace falta WGC.
    n = 20
    t0 = time.perf_counter()
    for _ in range(n):
        _capturar(hwnd)
    fps = n / (time.perf_counter() - t0)
    print(f"      velocidad: {fps:.1f} fps a {img.width}x{img.height}")

    if fps >= 30:
        r.ok("6 captura", f"PrintWindow vale: {fps:.0f} fps a {img.width}x{img.height}")
    else:
        r.fallo(
            "6 captura",
            f"solo {fps:.0f} fps (hacen falta 30): la Fase D necesita "
            "Windows Graphics Capture",
        )


# --------------------------------------------------------------------------
# sonda 7 — escribir y enviar de verdad


def _teclear(render: int, texto: str) -> None:
    """Teclea por mensajes, sin tocar el teclado fisico ni el portapapeles.

    Un WM_CHAR por unidad de codigo UTF-16, que es justo lo que espera Windows:
    asi entran acentos, enies y simbolos sin depender de la distribucion del
    teclado. Comprobado con "áéñ€".

    Se usa PostMessage y no SendInput a proposito: SendInput inyecta en la cola
    global, o sea que compite con lo que estes tecleando tu en ese momento y
    puede acabar en otra ventana si el foco cambia a mitad. PostMessage va
    dirigido a ESTA ventana y a ninguna otra.
    """
    for ch in texto:
        win32api.PostMessage(render, WM_CHAR, ord(ch), 1)


def _tecla(render: int, vk: int) -> None:
    win32api.PostMessage(render, WM_KEYDOWN, vk, 1)
    win32api.PostMessage(render, WM_KEYUP, vk, 1)


def sonda_enviar(r: Resultado, hwnd: int, render: int, piezas: dict[str, Any], texto: str) -> None:
    print(f"\n[7] Escribir y enviar: {texto!r}")

    compositor = piezas.get("compositor")
    if compositor is None:
        r.fallo("7 enviar", "no hay compositor localizado (fallo la sonda 3)")
        return

    antes_foco = win32gui.GetForegroundWindow()

    # Traer al frente NO es opcional: comprobado que con otra ventana delante los
    # WM_CHAR se pierden en silencio. Si no se consigue, se aborta -- teclear a
    # ciegas mandaria el texto a la ventana que tengas delante.
    if not (_al_frente_uia(hwnd, compositor) or _al_frente_win32(hwnd)):
        r.fallo("7 enviar", "no se pudo traer la ventana al frente: no se escribe")
        return
    time.sleep(0.2)

    _teclear(render, texto)
    time.sleep(0.4)

    escrito = texto_de(compositor)
    if texto not in escrito:
        print(f"      lo que hay en el compositor: {escrito!r}")
        r.fallo("7 enviar", "el texto no aparece entero en el compositor: no se envia")
        return
    print(f"      texto verificado en el compositor: {escrito!r}")

    # Ultima comprobacion antes del Enter: si el foco se hubiera ido, el Enter
    # se iria con el.
    if win32gui.GetForegroundWindow() != hwnd:
        r.fallo("7 enviar", "la ventana perdio el primer plano antes de enviar")
        return

    _tecla(render, win32con.VK_RETURN)
    time.sleep(0.5)

    # Que el compositor se haya vaciado es la prueba de que se envio de verdad:
    # si el Enter no hubiera hecho nada, el texto seguiria ahi.
    quedo = texto_de(compositor)
    enviado = texto not in quedo
    print(f"      compositor tras Enter: {quedo!r}")

    if antes_foco and antes_foco != hwnd:
        _al_frente_win32(antes_foco)

    if enviado:
        r.ok("7 enviar", "escrito, verificado y enviado")
    else:
        r.fallo("7 enviar", "el Enter no vacio el compositor: puede que no se enviara")


def sonda_respuesta(r: Resultado, jsonl: Path, desde: int, espera: float = 120.0) -> None:
    """Sigue el .jsonl y espera a que aparezca la respuesta.

    [desde] es el tamanio del fichero justo antes de enviar: se lee solo lo
    nuevo, igual que hara el servicio. Esto es lo que sustituye a scrapear la
    pantalla: el texto llega estructurado, completo y sin depender de la UI.
    """
    print(f"\n[7b] Esperar la respuesta leyendo {jsonl.name} desde el byte {desde}")

    limite = time.time() + espera
    vistos: list[str] = []
    while time.time() < limite:
        for m in _mensajes(jsonl, desde=desde):
            if m.startswith("assistant:") and m not in vistos:
                vistos.append(m)
                print(f"      >> {m[:120]}")
        if any(v.startswith("assistant:") and "[tool" not in v and "[pensando]" not in v
               for v in vistos):
            r.ok("7b respuesta", f"{len(vistos)} bloques leidos del transcript")
            return
        time.sleep(1.0)

    if vistos:
        r.ok("7b respuesta", f"{len(vistos)} bloques (aun sin texto final)")
    else:
        r.fallo("7b respuesta", f"nada nuevo del asistente en {espera:.0f} s")


# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Sondas de la Fase A de appctl")
    ap.add_argument(
        "--enviar",
        metavar="TEXTO",
        help="ademas de mirar, escribe TEXTO en la app y lo envia de verdad",
    )
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    r = Resultado()

    ventana = sonda_ventana(r)
    if ventana is None:
        return r.resumen()
    hwnd, render = ventana

    win = sonda_uia(r, hwnd)
    piezas = sonda_piezas(r, win) if win is not None else {}

    ses = sonda_sesiones(r)
    sonda_sidebar(r, piezas, ses["sesiones"] if ses else [])
    sonda_foco(r, hwnd, piezas)
    sonda_captura(r, hwnd)

    if args.enviar:
        antes = ses["jsonl"].stat().st_size if ses else 0
        sonda_enviar(r, hwnd, render, piezas, args.enviar)
        if ses:
            sonda_respuesta(r, ses["jsonl"], antes)
    else:
        print('\n[7] Escribir y enviar: SALTADA (pasa --enviar "texto" para probarla)')

    return r.resumen()


if __name__ == "__main__":
    sys.exit(main())
