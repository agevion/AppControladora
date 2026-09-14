"""Sobre de mensajes entre movil y PC.

Este contrato lo comparten las fases siguientes, asi que conviene que aguante:
- Fase 2 anade  permission.* tambien para Claude Code
- Fase 3 anade  build.done / artifact.ready
- Fase 4 anade  rtc.offer / rtc.answer / rtc.ice
- Fase E anade  app.tap / app.drag / app.scroll  (el puntero sobre ese video)
- v14 anade     clip.* (portapapeles compartido) y el POST /upload de ficheros
- v15 anade     app.copy (Ctrl+C sobre la ventana, para despues de seleccionar)
- v16 cambia    el video pasa de la ventana de Claude a pantalla completa:
                screens.* / rtc.offer con `monitor` / screen.tap / screen.drag /
                screen.scroll / screen.copy / screen.type / screen.key,
                sustituyendo a app.tap / app.drag / app.scroll / app.copy

Todo mensaje es JSON con "type". Los de conversacion llevan "id" para poder
casar la respuesta en streaming con la pregunta.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

# "app" (v12) es el Cerebro D: NO habla con ningun modelo, maneja la aplicacion
# de escritorio de Claude que hay abierta en el PC (ver controladora/appctl/ y
# ARQUITECTURA.md 5.1). Escribe en su compositor y lee su conversacion del disco.
Brain = Literal["local", "claude", "terminal", "app"]

# Que contesta el movil a un permiso. "save" es "permitir Y ademas congelar este
# comando como tool permanente" (ver toolgen.py); solo lo ofrece run_shell.
Decision = Literal["allow", "deny", "save"]


@dataclass(frozen=True)
class Reply:
    """La respuesta del movil a un permiso, tal cual la ven los dos cerebros.

    Es un objeto y no un bool a proposito: cuando esto eran tres valores en vez
    de dos, cualquier `if permitido:` sobre una tupla o un string habria dado
    "permitido" para un "deny". Aqui hay que preguntar por `allowed` a la cara.
    """

    action: Decision = "deny"
    nombre: str = ""
    # Respuesta a un AskUserQuestion: {texto_de_la_pregunta: etiqueta_elegida}.
    # None en un permiso normal (allow/deny/save). El CLI de Claude lee esto de
    # `updated_input["answers"]` para resolver la tool (ver brain_claude.py). Va
    # aqui y no en un tipo aparte porque viaja por el MISMO camino que un permiso
    # (la future de Session.ask_permission), solo cambia que se responde con la
    # opcion elegida en vez de con un Si/No.
    answers: dict[str, str] | None = None

    @property
    def allowed(self) -> bool:
        return self.action in ("allow", "save")

    @property
    def save(self) -> bool:
        return self.action == "save"

# Movil -> PC
# {id, brain, text, project?, mode?, model?, effort?, shell?}. "mode", "model" y
# "effort" solo los mira el cerebro "claude" (v9); "shell" solo lo mira el cerebro
# "terminal" (v10): "powershell" (por defecto) o "cmd", el interprete con el que
# se ejecuta el comando que el usuario tecleo. La Terminal NO pasa por
# permission.request: el comando lo escribe el propio usuario, asi que teclearlo
# ya es la aprobacion (ver brain_terminal.py).
# - mode: "ask" (por defecto, cada tool arriesgada pasa por permission.request),
#   "auto" (bypassPermissions: Claude corre sin preguntar) o "plan" (Claude solo
#   lee y propone; salir del modo plan SI pide permiso). Ver brain_claude.MODE_MAP.
# - model: alias del SDK ("sonnet", "opus", "haiku") o vacio/ausente = el que
#   decida la CLI. Cambiarlo aplica en caliente sin perder la conversacion
#   (ClaudeSDKClient.set_model), a diferencia de effort.
# - effort: "low" | "medium" | "high" | "xhigh" | "max", o vacio/ausente = el
#   que decida la CLI. El SDK no permite cambiarlo en caliente (no hay
#   set_effort): cambiar de effort fuerza una reconexion y se pierde el hilo de
#   la conversacion, igual que cambiar de proyecto. Ver brain_claude.ClaudeBrain.
# - sesion: solo lo mira el cerebro "app" (v12). Titulo de la sesion de la app de
#   escritorio en la que hay que escribir; vacio = en la que este abierta. El
#   valor especial "" con `nueva=true` empieza una conversacion nueva.
# - nueva: idem, solo "app". Pulsa el boton de sesion nueva antes de escribir.
CHAT = "chat"
PING = "ping"
PERMISSION_REPLY = "permission.reply"  # {req_id, action, nombre?, answers?}
# `answers` (v11) solo lo manda el movil al contestar un AskUserQuestion: es
# {texto_de_la_pregunta: etiqueta_elegida}. En un permiso normal no viaja. El PC
# lo mete en el Reply y el cerebro de Claude lo inyecta en updated_input para que
# el CLI resuelva la tool con la opcion que tocaste (ver server.py y brain_claude.py).
AI_STATUS = "ai.status"  # pide estado de la IA local
AI_SLEEP = "ai.sleep"  # duerme la IA local
TOOLS_RELOAD = "tools.reload"  # recarga el registry en caliente
# {}  pide system_stats() directo, sin pasar por ningun cerebro: la pantalla de
# Monitor refresca cada pocos segundos y eso no debe gastar tokens ni esperar
# a un LLM (ver Session.run_stats en server.py).
STATS_REQUEST = "stats.request"
# {name, args?}  ejecuta una tool directa (reboot_pc, build_and_send...) sin
# pasar por ningun cerebro. Si la tool pide confirmacion (CONFIRM=True),
# reutiliza el mismo permission.request/reply de siempre (ver Session.run_action).
#
# `args` existe desde la v7 y es lo que hace que las Acciones rapidas sirvan
# para algo: antes solo se podian llamar tools sin parametros, asi que "compila
# tal proyecto" tenia que ir por el chat -- osea, pagar un LLM para que
# tradujese un boton que ya sabia exactamente lo que queria decir.
ACTION_REQUEST = "action.request"
# {}  pide la lista de proyectos de paths.json, leida por el PC de su propio
# disco. Sustituye a las Acciones rapidas que le pedian a Claude Code que
# buscase paths.json y lo leyera: eso costaba tokens para leer un JSON, y encima
# fallaba, porque Claude buscaba "pc/paths.json" relativo a su cwd (la carpeta
# del proyecto seleccionado) y contestaba que ese fichero no existe.
PROJECTS_REQUEST = "projects.request"
# {brain}  olvida el contexto de ESE cerebro y empieza de cero (v9). Para
# "claude" cierra el ClaudeSDKClient (ClaudeBrain.close(), ya existia); para
# "local" limpia el historial (LocalBrain.reset(), ya existia y no se usaba).
# Pensado para saltar de un proyecto a otro sin arrastrar contexto viejo, o
# simplemente para no seguir gastando tokens sobre un hilo que ya no importa.
SESSION_NEW = "session.new"

# --- la app de escritorio (v12, Cerebro D) --------------------------------
#
# Estos NO pasan por ningun cerebro ni gastan tokens: son el mando a distancia de
# la aplicacion. Escribir en ella si va por CHAT con brain="app", porque eso si
# es una conversacion y tiene que verse como las demas (mismos chat.delta, tool,
# chat.end, mismo indicador de turno en el movil).
APP_REQUEST = "app.request"  # {}  pide una foto del estado de la app -> APP_STATE
APP_OPEN = "app.open"  # {titulo}  abre esa sesion pulsandola en la barra lateral
APP_NEW = "app.new"  # {}  empieza una conversacion nueva en la app
# {nombre}  pulsa un boton de la app por su nombre exacto, el que vino en
# APP_STATE.mandos. Es generico a proposito: con esto el movil puede tocar el
# selector de modelo, el de esfuerzo, el modo de permisos y -- lo que de verdad
# importa -- los botones de una tarjeta de permiso que salga en la app, sin que
# haya que enseñarle al PC cada una de ellas por separado.
APP_PRESS = "app.press"
APP_STOP = "app.stop"  # {}  corta el turno en curso de la app (Escape)

# --- pantalla completa: vídeo, puntero y teclado (v16) --------------------
#
# Hasta la v15 el vídeo y los gestos (que entonces se llamaban `app.tap` /
# `app.drag` / `app.scroll` / `app.copy`) estaban atados a la ventana de la app
# de escritorio de Claude: se capturaba con PrintWindow y los gestos iban por
# PostMessage a ese HWND. La v16 lo sustituye por control de PANTALLA COMPLETA,
# como un AnyDesk de verdad -- cualquier monitor del PC, cualquier ventana que
# haya en él, con ratón real (mueve el cursor de Windows) y teclado libre. Ver
# appctl/pantallas.py y appctl/pantalla_input.py.
#
# El chat con la app de Claude (arriba, `app.request`/`app.press`/etc.) NO
# cambia: sigue siendo UIA/PostMessage a esa ventana concreta. Sólo el vídeo y
# los gestos SOBRE él pasan a ser genéricos.
#
# **Siguen viajando FRACCIONES, no píxeles**, y la razón es la misma que en la
# v13: `screens.result` es una foto que se pide una vez, no en cada gesto, así
# que un punto absoluto calculado en el móvil podría caer mal si algo cambiara
# entre medias. Con fracciones el PC las resuelve contra el rectángulo REAL del
# monitor en el instante del gesto y las recorta a [0, 1] (ver
# pantallas.punto()). A diferencia de una ventana, la geometría de un monitor
# no se mueve ni cambia de tamaño sola -- por eso `screens.result` no hace
# falta refrescarlo en bucle.
#
# Todo mensaje de esta familia lleva `monitor`: el `id` de la pantalla sobre la
# que se gesticula (el mismo que sale en SCREENS_RESULT). No hay "pantalla
# actual" guardada en el servidor -- cada mensaje se basta solo, igual que ya
# hacía app.tap con la ventana.
SCREENS_REQUEST = "screens.request"  # {}  pide la lista de monitores del PC
SCREEN_TAP = "screen.tap"  # {monitor, fx, fy}  un clic izquierdo ahi
SCREEN_DRAG = "screen.drag"  # {monitor, fx, fy, fx2, fy2}  arrastra de un punto al otro
# {monitor, fx, fy, muescas}  gira la rueda sobre ese punto. `muescas` es
# entero y con signo: positivo = alejandose de ti = hacia el principio del
# documento, igual que la rueda de un raton de verdad.
SCREEN_SCROLL = "screen.scroll"
# {monitor}  Ctrl+C global (portapapeles de lo que esté seleccionado ahora
# mismo en el PC). Ya no hace falta traer ninguna ventana al frente: es un
# atajo del sistema, no algo dirigido a una app. Pensado para despues de un
# screen.drag que ha seleccionado texto (el "manten y arrastra" del movil, ver
# GestosVideo.kt). El texto copiado viaja de vuelta como CLIP_TEXT (reusa el
# mismo camino que clip.get, funcione o no el interruptor de clip.watch: pedir
# "copia esto" es distinto de "avisame de lo que copies").
SCREEN_COPY = "screen.copy"
# {monitor, text}  teclea ese texto donde esté el foco ahora mismo (Fase E.2
# del ARQUITECTURA.md). `monitor` no se usa para resolver ningún punto -- viaja
# igual que en los demás SCREEN_* por si algún día hace falta, pero teclear no
# depende de dónde esté el dedo.
SCREEN_TYPE = "screen.type"
# {monitor, tecla}  una tecla especial (Intro, Retroceso, Escape, Tab...) que
# no es texto imprimible. Ver appctl.pantalla_input.TECLAS.
SCREEN_KEY = "screen.key"

# --- video de pantalla completa (v12, Fase 4; generalizado a pantalla en v16) --
#
# {sdp, tipo, monitor}  el movil ofrece; el PC contesta con RTC_ANSWER. NO hay
# trickle: los dos lados esperan a terminar de recolectar candidatos antes de
# mandar su SDP, asi que los candidatos viajan DENTRO del sdp y no hacen falta
# mensajes `rtc.ice` sueltos. Con Tailscale los candidatos host bastan: ni STUN
# ni TURN (esto corrige lo que decia ARQUITECTURA.md 3, escrito cuando aun
# habia port forward). `monitor` es el `id` de SCREENS_RESULT a capturar; sin
# él (o si no existe ya) se captura el monitor principal. Ver appctl/webrtc.py.
RTC_OFFER = "rtc.offer"
RTC_STOP = "rtc.stop"  # {}  corta el video y suelta la captura

# --- portapapeles compartido (v14) ---------------------------------------
#
# La mitad de texto del traspaso PC <-> movil (la otra mitad son ficheros, y esa
# no pasa por aqui: va por HTTPS, ver POST /upload en server.py).
#
# {on}  enciende o apaga el vigilante del portapapeles del PC. Encendido, cada
# vez que copias algo en el PC (en cualquier aplicacion) el texto sale hacia el
# movil solo, sin pedir nada. Apagado, el PC no mira el portapapeles siquiera:
# esto es lo que hace que "no vigilar" sea de verdad no vigilar y no solo "no
# mandar". Lo manda el movil al conectar segun su propio interruptor.
CLIP_WATCH = "clip.watch"
CLIP_GET = "clip.get"  # {}  dame lo que haya copiado AHORA en el PC -> CLIP_TEXT
# {text}  copia esto en el portapapeles del PC (lo que tenias copiado en el
# movil, para pegarlo alli con Ctrl+V). El PC da ese texto por visto en el
# vigilante antes de escribirlo, o el cambio que acaba de provocar volveria al
# movil como si fuera nuevo (ver portapapeles.Vigilante.recuerda).
CLIP_SET = "clip.set"

# PC -> movil
HELLO = "hello"  # {version, brains, tools}
CHAT_DELTA = "chat.delta"  # {id, text}   fragmento en streaming
CHAT_END = "chat.end"  # {id}
TOOL = "tool"  # {id, name, args, confirm}      empieza una tool
TOOL_PROGRESS = "tool.progress"  # {id, name, text}   linea de estado en vivo (build en marcha, etc)
TOOL_RESULT = "tool.result"  # {id, name, text}
MISSING_TOOL = "missing_tool"  # {id, text}     abre el bucle de auto-ampliacion
PERMISSION_REQUEST = "permission.request"  # {req_id, brain, name, args, motivo, savable, sugerencia}
# {req_id, brain, questions}   Claude llamo a AskUserQuestion (v11). No es un
# permiso Si/No: es una o varias preguntas de opcion multiple que el movil pinta
# como burbuja con botones. `questions` es la lista cruda de la tool: cada una con
# {question, header, multiSelect, options:[{label, description}]}. La respuesta
# vuelve por permission.reply con `answers` (ver PERMISSION_REPLY). Reutiliza toda
# la maquinaria de permisos (future, caducidad, permission.cancel): lo unico
# distinto es la tarjeta y que se contesta con la opcion elegida.
QUESTION_REQUEST = "question.request"
# {req_id}   ese permiso ya no cuenta: caduco, o su turno murio. Retira la tarjeta.
PERMISSION_CANCEL = "permission.cancel"
TOOL_SAVED = "tool.saved"  # {ok, name, text}   resultado del boton "Guardar"
AI_STATE = "ai.state"  # {text}
COST = "cost"  # {turn, total}   solo Claude Code: lo local no cuesta dinero
# {status, resets_at, tipo, etiqueta, utilizacion}   los tokens de la CUENTA (v8).
#
# Esto no es el gasto del turno (eso es COST): es la ventana de uso de la
# suscripcion. `status` es "allowed" (todo bien), "allowed_warning" (queda poco) o
# "rejected" (se acabaron), y `resets_at` es el epoch en segundos a la que vuelve a
# haber tokens -- el unico dato que de verdad se quiere leer desde el gym.
#
# Existe porque antes el unico corte que veia el movil era un tope de gasto que nos
# habiamos puesto nosotros ($5 por conversacion, ver brain_claude.py), y era
# indistinguible de quedarse sin tokens de cuenta: el mensaje decia "limite" sin
# decir de que ni hasta cuando. Ese tope ya no existe; este aviso si es real.
LIMIT = "limit"
PONG = "pong"
ERROR = "error"  # {message, id?}
# {id, artifact_id, name, size}   Fase 3: APK listo, se baja por GET /artifact/<artifact_id>
ARTIFACT_READY = "artifact.ready"
# {text, data}  `text` es el mismo parrafo de siempre (y lo que entiende un APK
# viejo); `data` es la medida en crudo (ver sysinfo.snapshot) para que el movil
# dibuje barras en vez de re-parsear a mano un texto que acabamos de formatear.
STATS_RESULT = "stats.result"
ACTION_RESULT = "action.result"  # {name, ok, text}
PROJECTS_RESULT = "projects.result"  # {projects: [{nombre, tipo, path, descripcion, existe, ...}]}
# {screens: [{id, nombre, x, y, ancho, alto, principal}]}  los monitores del PC
# (v16). `id` es el nombre de dispositivo de Windows (p.ej. `\\.\DISPLAY1`),
# estable entre peticiones; es lo que el movil manda de vuelta en `monitor` al
# ofrecer video (RTC_OFFER) y en cada SCREEN_*. Ver appctl/pantallas.py.
SCREENS_RESULT = "screens.result"
SESSION_NEW_OK = "session.new_ok"  # {brain}  confirma que se olvido; el movil limpia esa conversacion.
# {abierta, titulo, modelo, uso, mandos, sesiones, error}  el estado de la app de
# escritorio (v12). Ver app_state() para el detalle de cada campo.
APP_STATE = "app.state"
# {sdp, tipo}  la respuesta al RTC_OFFER del movil, con los candidatos dentro.
RTC_ANSWER = "rtc.answer"
# {text, cortado, origen}   el portapapeles del PC (v14). Llega solo cuando el
# vigilante ve un Ctrl+C, o como respuesta a un CLIP_GET.
#
# `cortado` avisa de que el texto no venia entero: MAX_CLIP en server.py. Un
# portapapeles puede tener un fichero de log de 40 MB dentro, y meterlo en el
# mismo socket por el que viaja el chat en streaming lo dejaria mudo un buen
# rato. `origen` es informativo ("pc"): deja sitio para que manana el eco de un
# clip.set se distinga sin cambiar el formato.
CLIP_TEXT = "clip.text"

VERSION = 16


def hello(brains: list[str], tools: list[str]) -> dict[str, Any]:
    return {"type": HELLO, "version": VERSION, "brains": brains, "tools": tools}


def delta(msg_id: str, text: str) -> dict[str, Any]:
    return {"type": CHAT_DELTA, "id": msg_id, "text": text}


def end(msg_id: str) -> dict[str, Any]:
    return {"type": CHAT_END, "id": msg_id}


def tool(msg_id: str, name: str, args: dict[str, Any], confirm: bool) -> dict[str, Any]:
    return {"type": TOOL, "id": msg_id, "name": name, "args": args, "confirm": confirm}


def tool_progress(msg_id: str, name: str, text: str) -> dict[str, Any]:
    return {"type": TOOL_PROGRESS, "id": msg_id, "name": name, "text": text}


def tool_result(msg_id: str, name: str, text: str) -> dict[str, Any]:
    return {"type": TOOL_RESULT, "id": msg_id, "name": name, "text": text}


def missing_tool(msg_id: str, text: str) -> dict[str, Any]:
    return {"type": MISSING_TOOL, "id": msg_id, "text": text}


def permission_request(
    req_id: str,
    brain: str,
    name: str,
    args: dict[str, Any],
    motivo: str,
    savable: bool = False,
    sugerencia: str = "",
    admin: bool = False,
) -> dict[str, Any]:
    """`savable` decide si el movil pinta el tercer boton, y `sugerencia` lo rellena.

    `brain` va aqui porque cada cerebro tiene ya su propio chat en el movil: sin
    el, el "aprobaste X" del permiso caia en la conversacion que estuviera abierta
    en ese momento, que no tiene por que ser la del cerebro que lo pidio.

    `admin` (v7) es un campo propio y no algo que el movil deduzca mirando dentro
    de `args`: es lo que decide si la tarjeta grita que el comando va a correr con
    privilegios de administrador (ver controladora/elevate.py). Un aviso asi no
    puede depender de buscar una subcadena en un JSON.
    """
    return {
        "type": PERMISSION_REQUEST,
        "req_id": req_id,
        "brain": brain,
        "name": name,
        "args": args,
        "motivo": motivo,
        "savable": savable,
        "sugerencia": sugerencia,
        "admin": admin,
    }


def question_request(req_id: str, brain: str, questions: list[dict[str, Any]]) -> dict[str, Any]:
    """AskUserQuestion: la burbuja azul con botones (ver QUESTION_REQUEST).

    `questions` es tal cual la lista que trae la tool en sus args, sin tocar: el
    movil necesita el texto exacto de cada pregunta (es la CLAVE con la que se
    devuelve la respuesta) y la etiqueta exacta de cada opcion (es el VALOR).
    """
    return {
        "type": QUESTION_REQUEST,
        "req_id": req_id,
        "brain": brain,
        "questions": questions,
    }


def permission_cancel(req_id: str) -> dict[str, Any]:
    """Retira una tarjeta de permiso que ya no se puede contestar."""
    return {"type": PERMISSION_CANCEL, "req_id": req_id}


def tool_saved(ok: bool, name: str, text: str) -> dict[str, Any]:
    return {"type": TOOL_SAVED, "ok": ok, "name": name, "text": text}


def ai_state(text: str) -> dict[str, Any]:
    return {"type": AI_STATE, "text": text}


def cost(turn: float, total: float) -> dict[str, Any]:
    return {"type": COST, "turn": turn, "total": total}


def limit(
    status: str,
    resets_at: int | None,
    tipo: str,
    etiqueta: str,
    utilizacion: float | None,
) -> dict[str, Any]:
    """Estado de los tokens de la cuenta. Ver LIMIT.

    `resets_at` puede ser None: el CLI no siempre lo manda, y es mejor decir "sin
    tokens" a secas que inventarse una hora.
    """
    return {
        "type": LIMIT,
        "status": status,
        "resets_at": resets_at,
        "tipo": tipo,
        "etiqueta": etiqueta,
        "utilizacion": utilizacion,
    }


def error(message: str, msg_id: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"type": ERROR, "message": message}
    if msg_id:
        out["id"] = msg_id
    return out


def artifact_ready(msg_id: str, artifact_id: str, name: str, size: int) -> dict[str, Any]:
    return {
        "type": ARTIFACT_READY,
        "id": msg_id,
        "artifact_id": artifact_id,
        "name": name,
        "size": size,
    }


def stats_result(text: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"type": STATS_RESULT, "text": text, "data": data or {}}


def action_result(name: str, ok: bool, text: str) -> dict[str, Any]:
    return {"type": ACTION_RESULT, "name": name, "ok": ok, "text": text}


def projects_result(projects: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": PROJECTS_RESULT, "projects": projects}


def session_new_ok(brain: str) -> dict[str, Any]:
    return {"type": SESSION_NEW_OK, "brain": brain}


def rtc_answer(sdp: str, tipo: str) -> dict[str, Any]:
    return {"type": RTC_ANSWER, "sdp": sdp, "tipo": tipo}


def clip_text(text: str, cortado: bool = False, origen: str = "pc") -> dict[str, Any]:
    """El portapapeles del PC camino del movil. Ver CLIP_TEXT."""
    return {"type": CLIP_TEXT, "text": text, "cortado": cortado, "origen": origen}


def app_state(
    abierta: bool,
    titulo: str | None = None,
    modelo: str | None = None,
    uso: str | None = None,
    mandos: list[str] | None = None,
    opciones: list[str] | None = None,
    sesiones: list[dict[str, Any]] | None = None,
    error: str = "",
) -> dict[str, Any]:
    """El estado de la app de escritorio de Claude (v12).

    - `abierta`: si hay ventana. Cuando es False todo lo demas viene vacio y el
      movil ensena "la app no esta abierta" en vez de una pantalla en blanco.
    - `titulo`: la sesion que se esta VIENDO en la app. Sale de la barra lateral
      y no del indice de disco, que solo sabe cual se toco mas recientemente
      (ARQUITECTURA.md 5.1: las dos respuestas no son la misma).
    - `mandos`: los botones pulsables ahora mismo, tal cual los nombra la app.
      El movil los pinta como botones de verdad; para pulsarlos manda APP_PRESS
      con el nombre. Van en crudo y sin filtrar a proposito -- si la app saca una
      tarjeta de permiso, sus botones aparecen aqui solos y se pueden tocar sin
      que el PC tenga que conocerlos de antemano.
    - `opciones`: las entradas de un menu ABIERTO ahora mismo en la app (el
      selector de modelo, el de esfuerzo, el de permisos). Vacio casi siempre.
      Cuando no lo esta, la app espera a que elijas y no atiende a nada mas, asi
      que el movil debe enseñarlas por delante de todo. Se pulsan con APP_PRESS
      igual que un mando: son elementos de otro tipo (RadioButton, MenuItem),
      pero de eso ya se encarga el PC.
    - `sesiones`: [{titulo, trabajando, estado, modelo, esfuerzo, permisos, cwd}].
      `trabajando` puede ser None: significa "el estado que pinta la app no esta
      en la tabla de traducciones", no "esta parada". Ver uia.ESTADOS.

    No lleva `ventana`: hasta v15 iba aqui el rectangulo de la ventana de Claude,
    para el letterbox del video. Desde v16 el video es de pantalla completa y su
    geometria sale de SCREENS_RESULT, que no cambia entre peticiones como si
    cambiaba una ventana -- no hace falta reenviarla en cada foto de la app.
    """
    return {
        "type": APP_STATE,
        "abierta": abierta,
        "titulo": titulo,
        "modelo": modelo,
        "uso": uso,
        "mandos": mandos or [],
        "opciones": opciones or [],
        "sesiones": sesiones or [],
        "error": error,
    }


def screens_result(screens: list[dict[str, Any]]) -> dict[str, Any]:
    """Los monitores del PC (v16). Ver SCREENS_RESULT."""
    return {"type": SCREENS_RESULT, "screens": screens}
