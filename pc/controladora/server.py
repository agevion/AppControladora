from __future__ import annotations

import asyncio
import hmac
import json
import logging
import uuid
from typing import Any
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from . import artifacts, brain_terminal, paths, portapapeles, protocol as p
from . import recibidos, sysinfo, toolgen, toolrun
from .appctl import pantalla_input, pantallas
from .appctl.webrtc import Emisor as AppVideo
from .brain_app import AppBrain
from .brain_claude import ClaudeBrain
from .brain_local import LocalBrain
from .config import Config, load
from .registry import Registry

log = logging.getLogger("controladora")

app = FastAPI(title="AppControladora", docs_url=None, redoc_url=None, openapi_url=None)
cfg: Config = load()

registry = Registry()
registry.load()

# Una sola instancia para todo el proceso, no una por conexion: el cliente del
# SDK guarda la memoria de la conversacion, y antes vivia dentro de cada Session
# y se cerraba al desconectar (ver el finally de ws() mas abajo). Cada vez que
# el movil saltaba de WiFi a datos, o pasaba un rato en segundo plano y el
# socket se caia, Claude perdia el hilo entero sin avisar. Compartida aqui,
# sobrevive a las reconexiones -- y de paso dejan de nacer CLI huerfanos: hay
# como mucho un claude.exe vivo en vez de uno nuevo por reconexion. Si el
# proceso entero muere, el Job Object de winjob.py se lleva el subproceso por
# delante igualmente, asi que no hace falta cerrarlo a mano en ningun sitio.
claude_brain = ClaudeBrain()

# La IA local, por el MISMO motivo que claude_brain y con el mismo bug detras:
# vivia dentro de Session, o sea una instancia nueva por cada conexion del
# WebSocket, con su `_history` vacio. Cada salto de WiFi a datos, cada rato en
# segundo plano, cada backoff de reconexion le borraba la conversacion entera --
# y a diferencia de Claude, que al menos guarda su contexto en el CLI, aqui el
# historial ES la memoria. De ahi lo de "no se entera de nada, hay que
# repetirselo todo": no es que sea tonta, es que empezaba de cero cada dos por
# tres. El arreglo se hizo para Claude y no se aplico aqui.
local_brain = LocalBrain(registry)

# El Cerebro D: la app de escritorio (ver brain_app.py). Compartido por el mismo
# motivo que los otros dos, aunque aqui pesa menos: no guarda conversacion -- la
# conversacion vive en la propia app, que es justo la gracia. Lo que si recuerda
# entre reconexiones es en que sesion se estaba escribiendo.
app_brain = AppBrain()

# Los cerebros que anunciamos en el hello. Estaba escrito a mano en cuatro sitios
# y al anadir "app" se quedaron tres desactualizados: una constante y se acabo.
BRAINS = ["local", "claude", "terminal", "app"]

# Cada cuanto se le pregunta a Windows si el portapapeles ha cambiado. Es una
# consulta a un contador, no abrir el portapapeles (ver portapapeles.py), asi
# que medio segundo no le cuesta nada al PC y hace que copiar en el PC y mirar
# el movil se sienta inmediato.
CLIP_INTERVALO = 0.5

# Cuanto texto de portapapeles se manda como mucho. Un portapapeles puede tener
# un log de 40 MB dentro; ese socket lleva ademas el chat en streaming y el
# senalizado del video, y no puede quedarse mudo mientras pasa un mamotreto.
# Lo que se corta se avisa (ver protocol.clip_text).
MAX_CLIP = 100_000

# Tope de lo que se acepta en una subida. No es una limitacion tecnica: es que
# un fichero de mas de esto por Tailscale, desde el movil, casi siempre es un
# dedazo -- y sin tope, el dedazo llena el disco del PC.
MAX_SUBIDA = 2 * 1024 * 1024 * 1024

# Cuanto se espera un Si/No del movil antes de darlo por denegado. Si estas en el
# gym y no miras el telefono, la accion NO se ejecuta: el silencio es un "no".
PERMISSION_TIMEOUT = 120.0


@app.get("/health")
async def health() -> dict[str, object]:
    """Sirve para comprobar el transporte sin levantar la app entera."""
    return {"ok": True, "version": p.VERSION, "tools": registry.names()}


def _token_ok(value: str) -> bool:
    return hmac.compare_digest(value, cfg.token)


def _authorized(websocket: WebSocket) -> bool:
    header = websocket.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer":
        return False
    return _token_ok(value)


@app.get("/artifact/{artifact_id}")
async def download_artifact(artifact_id: str, request: Request) -> FileResponse:
    """El movil baja el APK por aqui tras un evento artifact.ready (ver
    controladora/artifacts.py). mTLS ya exige certificado de cliente a nivel de
    socket (run.py); el token es la misma segunda cerradura que ya protege el
    WebSocket (ARQUITECTURA.md seccion 9), no una nueva superficie sin proteger.
    """
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not _token_ok(value):
        raise HTTPException(status_code=403, detail="token invalido")

    ruta = artifacts.resolve(artifact_id)
    if ruta is None or not ruta.exists():
        raise HTTPException(
            status_code=404,
            detail="Ese APK ya no esta disponible (caduco o el proceso se reinicio). Pide que se compile de nuevo.",
        )

    return FileResponse(
        ruta,
        media_type="application/vnd.android.package-archive",
        filename=ruta.name,
    )


@app.post("/upload")
async def upload(request: Request) -> dict[str, object]:
    """El movil sube un fichero a la carpeta de recibidos (ver recibidos.py).

    Por HTTPS y no por el WebSocket, por el mismo motivo que el APK baja por un
    GET (ver artifacts.py): una foto son varios MB, el socket ya lleva el chat en
    streaming y el senalizado del video, y meter bytes ahi como base64 los infla
    un 33% y deja el chat mudo mientras pasan. La proteccion es la misma que ya
    hay: mTLS a nivel de socket (run.py) mas el token.

    El cuerpo son los bytes pelados y el nombre viaja en una cabecera: multipart
    obligaria a meter python-multipart y a que el movil arme el sobre, para
    ganar exactamente nada -- aqui siempre va un fichero por peticion.

    La cabecera va percent-encoded porque una cabecera HTTP es latin-1 y los
    nombres de fichero del movil traen tildes, emojis y espacios.
    """
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not _token_ok(value):
        raise HTTPException(status_code=403, detail="token invalido")

    nombre = unquote(request.headers.get("x-nombre", "")).strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="falta la cabecera X-Nombre")

    try:
        destino = await asyncio.to_thread(recibidos.hueco, nombre)
    except (ValueError, OSError) as e:
        raise HTTPException(status_code=400, detail=f"no se puede guardar con ese nombre: {e}")

    # Se escribe primero a ".parte" y se renombra al final. Asi la carpeta nunca
    # ensena un fichero a medias como si estuviera entero: si la conexion se
    # corta a mitad (sales del alcance del wifi con el movil en la mano), lo que
    # queda es un .parte que se ve que es basura, no una foto rota con su nombre
    # bueno. El renombrado dentro del mismo disco es atomico.
    parcial = destino.with_name(destino.name + ".parte")
    escritos = 0
    try:
        with parcial.open("wb") as f:
            async for trozo in request.stream():
                if not trozo:
                    continue
                escritos += len(trozo)
                if escritos > MAX_SUBIDA:
                    raise HTTPException(status_code=413, detail="fichero demasiado grande")
                # En un hilo: escribir a disco bloquea, y este bucle corre en el
                # mismo loop que emite el video a 30 fps y atiende el chat.
                await asyncio.to_thread(f.write, trozo)
    except HTTPException:
        parcial.unlink(missing_ok=True)
        raise
    except Exception as e:
        parcial.unlink(missing_ok=True)
        log.warning("subida cortada (%s): %s", nombre, e)
        raise HTTPException(status_code=400, detail=f"la subida se corto: {type(e).__name__}")

    # El movil dice cuanto pesaba el fichero (X-Bytes). Si no cuadra con lo que
    # ha llegado, la subida se corto de una forma que no dio error -- y lo peor
    # que puede hacer esto es dejar media foto en la carpeta con su nombre bueno,
    # pareciendo entera. Si el movil no manda la cabecera (o no sabia el tamano,
    # que pasa con algunos proveedores de content://), no hay nada que comparar.
    esperados = request.headers.get("x-bytes")
    if esperados and esperados.lstrip("-").isdigit() and int(esperados) >= 0 and int(esperados) != escritos:
        parcial.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"llegaron {escritos} bytes de los {esperados} que decia el movil: subida incompleta",
        )

    parcial.replace(destino)
    log.info("recibido del movil: %s (%d bytes)", destino, escritos)
    return {"ok": True, "nombre": destino.name, "ruta": str(destino), "bytes": escritos}


def _frac(msg: dict[str, Any], clave: str) -> float:
    """Una fraccion de la pantalla (0 a 1) de un mensaje de gesto. Ver protocol.SCREEN_TAP.

    Un campo ausente, nulo o ilegible sale como 0.0 en vez de reventar: esto lo
    alimenta un gesto tactil, y un gesto a medias no debe tumbar la tarea. El
    recorte de verdad lo hace el PC al resolver la fraccion contra el monitor
    (pantallas.punto), asi que un 0.0 es como mucho un toque en la esquina,
    nunca un clic fuera de la pantalla. NaN se descarta aqui: es el unico float
    que se escapa vivo de un `min`/`max`.
    """
    try:
        n = float(msg.get(clave, 0.0))
    except (TypeError, ValueError):
        return 0.0
    return n if n == n else 0.0  # NaN != NaN


def _entero(msg: dict[str, Any], clave: str) -> int:
    try:
        return int(msg.get(clave, 0))
    except (TypeError, ValueError):
        return 0


def _projects_snapshot() -> list[dict[str, Any]]:
    """paths.json en la forma que dibuja el movil. Toca disco: llamalo en un hilo.

    `existe` se comprueba aqui, no en el movil: el movil no tiene el disco del PC
    delante, y un proyecto cuya carpeta se ha movido debe verse a la primera y no
    al fallar el build tres minutos despues.

    `variante` va por lo mismo: quien sabe si un proyecto puede compilar una
    release instalable es quien tiene su build.gradle delante, no el telefono.
    Con esto el boton de Acciones rapidas puede decir "Compilar release y
    enviarme" o avisar de que ese proyecto solo puede darte una debug, ANTES de
    que te pases tres minutos esperando.
    """
    from pathlib import Path

    from controladora import variantes

    salida = []
    for nombre, datos in sorted(paths.projects().items()):
        existe = Path(datos.get("path", "")).is_dir()
        variante = variantes.para(datos) if existe and datos.get("type") == "gradle" else None
        salida.append(
            {
                "nombre": nombre,
                "tipo": datos.get("type", "?"),
                "path": datos.get("path", ""),
                "descripcion": datos.get("descripcion", ""),
                "unity_version": datos.get("unity_version"),
                "existe": existe,
                # Cadena vacia y no null a proposito: el `optString` de org.json en
                # Android devuelve el texto "null" para un null de JSON, no "".
                "variante": variante.tarea if variante else "",
                "variante_nota": variante.motivo if variante else "",
            }
        )
    return salida


class Session:
    """Una conexion del movil. Guarda los permisos en vuelo de ESTA conexion.

    La memoria de la charla con Claude ya NO vive aqui -- vive en el
    `claude_brain` compartido a nivel de modulo, para que sobreviva a que esta
    Session muera y nazca otra en la siguiente reconexion (ver el comentario
    junto a `claude_brain` arriba).
    """

    def __init__(self, websocket: WebSocket) -> None:
        self.ws = websocket
        self.local = local_brain
        self.claude = claude_brain
        # El video SI vive aqui y no a nivel de modulo, al reves que los
        # cerebros: una conexion WebRTC pertenece a UN socket concreto (sus
        # candidatos ICE apuntan a ese movil). Si el movil se reconecta, lo que
        # hace falta es una negociacion nueva, no heredar la vieja -- y dejarla
        # viva seria seguir codificando video a 30 fps para nadie.
        self.video = AppVideo()
        self.pending: dict[str, asyncio.Future[p.Reply]] = {}
        # req_id -> id del turno que lo pidio, para poder retirar del movil las
        # tarjetas de un turno que ya ha muerto (ver el finally de handle_chat).
        self.pending_turn: dict[str, str] = {}
        # El portapapeles compartido (v14). El vigilante vive por conexion, como
        # el video y no como los cerebros: lo que hace es empujar texto POR ESTE
        # socket, asi que no tiene ningun sentido que siga corriendo cuando el
        # socket muere. Nace apagado; lo enciende el movil con clip.watch.
        self.clip = portapapeles.Vigilante()
        self.clip_task: asyncio.Task[None] | None = None

    def _drop_pending(self, msg_id: str) -> None:
        """Retira los permisos de un turno que ya no puede contestarlos.

        Sin esto, un turno que revienta mientras esperas el Si/No deja la tarjeta
        pegada en el movil: pulses lo que pulses, al otro lado ya no hay nadie
        escuchando, y parece que la app se ha colgado.
        """
        huerfanos = [r for r, t in self.pending_turn.items() if t == msg_id]
        for req_id in huerfanos:
            fut = self.pending.get(req_id)
            if fut and not fut.done():
                fut.set_result(p.Reply(action="deny"))
            self.pending_turn.pop(req_id, None)
            asyncio.create_task(self._cancel_card(req_id))

    async def _cancel_card(self, req_id: str) -> None:
        try:
            await self.ws.send_json(p.permission_cancel(req_id))
        except Exception:
            pass

    async def ask_permission(self, brain: str, msg_id: str, name: str, args: dict[str, Any]) -> p.Reply:
        """Pide permiso al movil y espera. El silencio es un no."""
        req_id = uuid.uuid4().hex
        fut: asyncio.Future[p.Reply] = asyncio.get_running_loop().create_future()
        self.pending[req_id] = fut
        self.pending_turn[req_id] = msg_id

        # AskUserQuestion no es un Si/No: es una pregunta de opcion multiple que el
        # movil pinta como burbuja azul con botones (ver protocol.QUESTION_REQUEST).
        # Reutiliza TODA la maquinaria de permisos de aqui abajo (la future, la
        # caducidad, el permission.cancel): lo unico que cambia es la tarjeta que se
        # manda y que se contesta con la opcion elegida (answers) en vez de allowed.
        if name == "AskUserQuestion":
            questions = args.get("questions")
            if not isinstance(questions, list):
                questions = []
            try:
                await self.ws.send_json(p.question_request(req_id, brain, questions))
            except Exception:
                self.pending.pop(req_id, None)
                self.pending_turn.pop(req_id, None)
                return p.Reply(action="deny")
            try:
                return await asyncio.wait_for(fut, timeout=PERMISSION_TIMEOUT)
            except asyncio.TimeoutError:
                log.info("pregunta %s: sin respuesta en %.0fs -> sin contestar", req_id, PERMISSION_TIMEOUT)
                await self._cancel_card(req_id)
                return p.Reply(action="deny")
            finally:
                self.pending.pop(req_id, None)
                self.pending_turn.pop(req_id, None)

        motivo = args.get("motivo") or ""
        # Un comando administrativo NO se puede congelar como tool: una tool
        # guardada nace con CONFIRM=False, o sea que no vuelve a preguntar nunca, y
        # "administrador para siempre y sin tarjeta" es exactamente lo que no se
        # quiere (ver elevate.py). Que la unica savable siga siendo run_shell es
        # porque es la unica cuyo "que hace" cabe entero en un comando que acabas
        # de leer (ver toolgen.py).
        admin = name == "run_shell" and bool(args.get("admin"))
        savable = name == "run_shell" and not admin
        sugerencia = ""
        if savable:
            sugerencia = str(args.get("nombre_tool") or "") or toolgen.suggest_name(
                str(args.get("comando") or "")
            )

        if admin:
            log.warning("permiso ADMIN pedido: %s", str(args.get("comando"))[:120])

        try:
            await self.ws.send_json(
                p.permission_request(req_id, brain, name, args, motivo, savable, sugerencia, admin)
            )
        except Exception:
            # El movil se fue a mitad de turno (segundo plano, WiFi->datos): no hay
            # a quien pedirle el Si/No. Denegar es lo seguro, y ademas deja que el
            # turno siga drenandose hasta el final en vez de reventar aqui -- que es
            # justo lo que deja limpio el cliente SDK de Claude (ver handle_chat).
            self.pending.pop(req_id, None)
            self.pending_turn.pop(req_id, None)
            return p.Reply(action="deny")

        try:
            return await asyncio.wait_for(fut, timeout=PERMISSION_TIMEOUT)
        except asyncio.TimeoutError:
            log.info("permiso %s: sin respuesta en %.0fs -> denegado", name, PERMISSION_TIMEOUT)
            # El movil tiene la tarjeta abierta creyendo que aun cuenta. Si no se
            # le dice que ha caducado, se queda ahi tapando la pantalla.
            await self._cancel_card(req_id)
            return p.Reply(action="deny")
        finally:
            self.pending.pop(req_id, None)
            self.pending_turn.pop(req_id, None)

    def resolve_permission(self, req_id: str, reply: p.Reply) -> None:
        fut = self.pending.get(req_id)
        if fut and not fut.done():
            fut.set_result(reply)

    async def save_tool(self, nombre: str, args: dict[str, Any], resultado: str) -> None:
        """Congela un run_shell aprobado como tool permanente y recarga el registry."""
        comando = str(args.get("comando") or "")

        # Cinturon y tirantes: el movil ya no ofrece "Guardar" en una tarjeta admin
        # (savable va a False en ask_permission), pero esto es lo que de verdad
        # ejecuta, y un APK viejo o un cliente cualquiera podria mandar "save" igual.
        # Una tool guardada no vuelve a pedir permiso: admin ahi no entra.
        if args.get("admin"):
            await self.ws.send_json(
                p.tool_saved(False, nombre, "No se guardan comandos de administrador: una tool guardada no vuelve a preguntar.")
            )
            return

        if not toolgen.command_succeeded(resultado):
            # Guardar un comando que acaba de fallar seria congelar un error y
            # ademas dejarselo al modelo como si funcionara.
            await self.ws.send_json(
                p.tool_saved(False, nombre, "No la guardo: el comando no termino bien.")
            )
            return

        try:
            destino = await asyncio.to_thread(
                toolgen.save_shell_tool, nombre, comando, str(args.get("motivo") or "")
            )
        except toolgen.ToolGenError as e:
            await self.ws.send_json(p.tool_saved(False, nombre, str(e)))
            return

        await asyncio.to_thread(registry.load)
        log.info("tool guardada: %s", destino)

        await self.ws.send_json(
            p.tool_saved(True, destino.stem, f"Guardada como {destino.name}. Ya puedes pedirmela por su nombre.")
        )
        # La lista de tools del movil acaba de cambiar.
        await self.ws.send_json(p.hello(brains=BRAINS, tools=registry.names()))

    # --- portapapeles compartido (v14) ----------------------------------

    async def clip_watch(self, encendido: bool) -> None:
        """Enciende o apaga el vigilante del portapapeles del PC (ver CLIP_WATCH)."""
        if not encendido:
            self.parar_clip()
            return
        if self.clip_task and not self.clip_task.done():
            return  # ya estaba: encenderlo dos veces no arranca dos bucles
        self.clip_task = asyncio.create_task(self._vigilar_clip())

    def parar_clip(self) -> None:
        """Apaga el vigilante. La llama tambien el finally de ws() al desconectar."""
        if self.clip_task:
            self.clip_task.cancel()
            self.clip_task = None

    async def _vigilar_clip(self) -> None:
        """Cada CLIP_INTERVALO: ¿ha cambiado el portapapeles? Si si, al movil.

        No hay evento del sistema que valga aqui: enterarse "de verdad" pide una
        ventana oculta con AddClipboardFormatListener y un bucle de mensajes de
        Win32 propio, y este proceso ya tiene un hilo con su apartamento de COM
        para la app de escritorio (appctl/hilo.py). Preguntar por el contador
        cada medio segundo cuesta menos que mantener eso, y no se nota.
        """
        try:
            while True:
                texto = await asyncio.to_thread(self.clip.cambio)
                if texto:
                    await self._enviar_clip(texto)
                await asyncio.sleep(CLIP_INTERVALO)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Un fallo del portapapeles no puede llevarse por delante la
            # conexion entera: se deja dicho y este vigilante se muere solo.
            log.exception("el vigilante del portapapeles se paro")

    async def _enviar_clip(self, texto: str) -> None:
        cortado = len(texto) > MAX_CLIP
        await self.ws.send_json(p.clip_text(texto[:MAX_CLIP], cortado))

    async def clip_get(self) -> None:
        """El movil pide lo que haya copiado ahora mismo en el PC (CLIP_GET).

        Contesta SIEMPRE, aunque no haya texto: el movil ha pulsado un boton y
        el silencio es indistinguible de que se haya perdido la peticion. Un
        portapapeles con una imagen dentro se contesta con texto vacio, y eso el
        movil lo sabe pintar ("no hay texto copiado en el PC").
        """
        texto = await asyncio.to_thread(portapapeles.leer)
        # Se da por visto: si no, el vigilante lo mandaria otra vez acto seguido.
        self.clip.recuerda(texto)
        await self._enviar_clip(texto)

    async def clip_set(self, texto: str) -> None:
        """Copia en el PC lo que el movil tenia copiado (CLIP_SET)."""
        if not texto:
            return
        # recuerda() ANTES de escribir, no despues: entre escribir y recordar
        # cabe una vuelta del vigilante, y ahi el texto volveria al movil como
        # si alguien lo hubiera copiado en el PC.
        self.clip.recuerda(texto)
        ok = await asyncio.to_thread(portapapeles.escribir, texto)
        if not ok:
            await self.ws.send_json(
                p.error("no pude escribir en el portapapeles del PC: lo tenia ocupado otra aplicacion")
            )

    async def run_stats(self) -> None:
        """Pantalla de Monitor: refresca sola cada pocos segundos. Sin cerebro
        de por medio no hay tokens que gastar ni un LLM al que esperar.

        Va directo a sysinfo en vez de pasar por registry.call("system_stats"):
        la tool devuelve el texto ya formateado para el modelo, y el movil quiere
        los numeros para dibujar. Se manda una sola medida en los dos formatos
        (ver protocol.stats_result) para que no puedan contradecirse.
        """
        try:
            snap = await asyncio.to_thread(sysinfo.snapshot)
            await self.ws.send_json(p.stats_result(sysinfo.to_text(snap), snap))
        except Exception as e:
            log.exception("no pude leer el estado del PC")
            await self.ws.send_json(
                p.stats_result(f"No pude leer el estado del PC: {type(e).__name__}: {e}")
            )

    async def send_projects(self) -> None:
        """La lista de proyectos, leida por el PC de su propio paths.json.

        Esto sustituye a las Acciones rapidas que le pedian a Claude Code "busca
        el proyecto X en pc/paths.json y dime su ruta". Aquello era pagar tokens
        por leer un JSON de 100 lineas que esta en el disco de este mismo
        proceso, y encima no funcionaba: el cwd de Claude es la carpeta del
        proyecto seleccionado, asi que "pc/paths.json" no existia desde ahi y
        contestaba que ese fichero no estaba en la maquina.
        """
        try:
            lista = await asyncio.to_thread(_projects_snapshot)
        except Exception as e:
            log.exception("no pude leer paths.json")
            await self.ws.send_json(p.error(f"No pude leer paths.json: {type(e).__name__}: {e}"))
            return
        await self.ws.send_json(p.projects_result(lista))

    async def send_app_state(self) -> None:
        """Una foto de la app de escritorio (ver protocol.app_state).

        La pide la pantalla "App" del movil al abrirse y cada pocos segundos. No
        pasa por ningun cerebro ni gasta tokens: es leer la ventana y un par de
        ficheros, igual que hace `run_stats` con los sensores.
        """
        try:
            estado = await app_brain.estado()
        except Exception as e:
            log.exception("no pude leer el estado de la app de escritorio")
            await self.ws.send_json(p.app_state(abierta=False, error=f"{type(e).__name__}: {e}"))
            return
        await self.ws.send_json(p.app_state(**estado))

    async def app_command(self, kind: str, msg: dict[str, Any]) -> None:
        """Los mandos de la app: abrir sesion, nueva, pulsar un boton, parar.

        Todos terminan mandando el estado de vuelta, sin excepcion. Es lo que
        hace que el movil no tenga que suponer que su orden funciono: pulsas
        "Opus 5" y lo que ves cambiar es lo que la app dice de si misma, no lo
        que el movil se imagina que habra pasado.
        """
        try:
            if kind == p.APP_OPEN:
                fallo = await app_brain.abrir(str(msg.get("titulo") or ""))
            elif kind == p.APP_NEW:
                fallo = await app_brain.nueva()
            elif kind == p.APP_PRESS:
                fallo = await app_brain.pulsar(str(msg.get("nombre") or ""))
            elif kind == p.APP_STOP:
                fallo = await app_brain.parar()
            else:
                fallo = f"orden desconocida para la app: {kind}"
        except Exception as e:
            log.exception("orden %s a la app reventada", kind)
            fallo = f"{type(e).__name__}: {e}"

        if fallo:
            await self.ws.send_json(p.error(fallo))
        # La app tarda un momento en repintarse tras un clic; sin esta pausa la
        # foto sale con el estado de ANTES y parece que no ha pasado nada.
        await asyncio.sleep(0.8)
        await self.send_app_state()

    async def send_screens(self) -> None:
        """La lista de monitores del PC (v16, ver protocol.SCREENS_RESULT)."""
        try:
            pantallas_ = await asyncio.to_thread(pantallas.listar)
        except Exception as e:
            log.exception("no pude listar los monitores")
            await self.ws.send_json(p.error(f"No pude listar los monitores: {type(e).__name__}: {e}"))
            return
        await self.ws.send_json(
            p.screens_result(
                [
                    {
                        "id": s.id,
                        "nombre": s.nombre,
                        "x": s.x,
                        "y": s.y,
                        "ancho": s.ancho,
                        "alto": s.alto,
                        "principal": s.principal,
                    }
                    for s in pantallas_
                ]
            )
        )

    async def screen_gesture(self, kind: str, msg: dict[str, Any]) -> None:
        """El puntero sobre el video de pantalla completa: tocar, arrastrar,
        desplazar (v16, antes Fase E.1 atada a la ventana de Claude).

        No manda ningun estado de vuelta: quien confirma que el gesto ha
        surtido efecto es el VIDEO, que ya se esta mirando a 30 fps.

        Lo que llega son fracciones de la pantalla (0 a 1), no pixeles: el
        porque esta en protocol.SCREEN_TAP. `_frac` las deja utilizables
        aunque vengan ausentes o ilegibles, y el recorte final lo hace el PC
        (pantallas.punto).
        """
        try:
            pantalla_ = await asyncio.to_thread(pantallas.buscar, msg.get("monitor"))
            if pantalla_ is None:
                fallo = "no hay ningun monitor que capturar"
            elif kind == p.SCREEN_TAP:
                x, y = pantallas.punto(pantalla_, _frac(msg, "fx"), _frac(msg, "fy"))
                await asyncio.to_thread(pantalla_input.clic, x, y)
                fallo = ""
            elif kind == p.SCREEN_DRAG:
                x1, y1 = pantallas.punto(pantalla_, _frac(msg, "fx"), _frac(msg, "fy"))
                x2, y2 = pantallas.punto(pantalla_, _frac(msg, "fx2"), _frac(msg, "fy2"))
                await asyncio.to_thread(pantalla_input.arrastrar, x1, y1, x2, y2)
                fallo = ""
            elif kind == p.SCREEN_SCROLL:
                x, y = pantallas.punto(pantalla_, _frac(msg, "fx"), _frac(msg, "fy"))
                await asyncio.to_thread(pantalla_input.rueda, x, y, _entero(msg, "muescas"))
                fallo = ""
            else:
                fallo = f"gesto desconocido para la pantalla: {kind}"
        except Exception as e:
            log.exception("gesto %s sobre la pantalla reventado", kind)
            fallo = f"{type(e).__name__}: {e}"

        if fallo:
            await self.ws.send_json(p.error(fallo))

    async def screen_copy(self) -> None:
        """Boton "Copiar seleccion" sobre el video (v16): Ctrl+C global y lo manda YA.

        A diferencia de tocar/arrastrar/desplazar, esto SI tiene algo que
        devolver -- el propio texto copiado. Se manda pase lo que pase con el
        interruptor `clip.watch`: pedir explicitamente "copia esto" es
        distinto de "avisame de lo que copies" y tiene que funcionar aunque el
        segundo este apagado.
        """
        try:
            await asyncio.to_thread(pantalla_input.copiar)
        except Exception as e:
            log.exception("no se pudo copiar la seleccion de la pantalla")
            await self.ws.send_json(p.error(f"{type(e).__name__}: {e}"))
            return

        await self.clip_get()

    async def screen_type(self, texto: str) -> None:
        """Teclado libre sobre la pantalla (v16, Fase E.2): escribe donde este el foco."""
        if not texto:
            return
        try:
            await asyncio.to_thread(pantalla_input.escribir, texto)
        except Exception as e:
            log.exception("no se pudo teclear sobre la pantalla")
            await self.ws.send_json(p.error(f"{type(e).__name__}: {e}"))

    async def screen_key(self, nombre: str) -> None:
        """Una tecla especial (Intro, Retroceso...) del teclado libre. Ver pantalla_input.TECLAS."""
        try:
            ok = await asyncio.to_thread(pantalla_input.tecla, nombre)
        except Exception as e:
            log.exception("no se pudo mandar la tecla %r", nombre)
            await self.ws.send_json(p.error(f"{type(e).__name__}: {e}"))
            return
        if not ok:
            await self.ws.send_json(p.error(f"tecla desconocida: {nombre}"))

    async def start_video(self, sdp: str, tipo: str, monitor: str | None) -> None:
        """Negocia el video de pantalla completa (ver appctl/webrtc.py).

        Una oferta nueva sustituye a la anterior: si el movil renegocia (cambio
        de red, cambio de monitor, la app volvio de segundo plano) lo que
        quiere es empezar de cero, no sumar un emisor mas codificando para un
        socket muerto.
        """
        try:
            respuesta = await self.video.oferta(sdp, tipo, monitor)
        except Exception as e:
            log.exception("no pude arrancar el video")
            await self.ws.send_json(p.error(f"No pude arrancar el vídeo: {type(e).__name__}: {e}"))
            return
        await self.ws.send_json(p.rtc_answer(respuesta["sdp"], respuesta["tipo"]))

    async def run_action(self, msg_id: str, name: str, args: dict[str, Any]) -> None:
        """Boton directo del movil (Acciones rapidas y Monitor).

        No pasa por ningun cerebro: un boton ya sabe exactamente que tool quiere y
        con que argumentos, asi que meter un LLM en medio para que lo adivine solo
        anade tokens, latencia y una forma nueva de equivocarse.

        Emite los MISMOS eventos que un turno de chat (tool / tool.progress /
        tool.result / artifact.ready / chat.end) con el `msg_id` que manda el
        movil. Asi un "compila y mandame el APK" desde un boton se ve igual que
        pedirlo por el chat -- con su tarjeta y su progreso en vivo -- en vez de
        quedarse callado varios minutos y escupirlo todo al final.
        """
        try:
            tool = registry.get(name)
            if tool is None:
                await self.ws.send_json(p.action_result(name, False, f"no existe la tool '{name}'"))
                return

            if tool.confirm:
                motivo = str(args.get("motivo") or f"Pedido desde un boton del movil: {name}")
                reply = await self.ask_permission("local", msg_id, name, {**args, "motivo": motivo})
                if not reply.allowed:
                    await self.ws.send_json(p.action_result(name, False, "no se aprobo desde el movil"))
                    return

            await self.ws.send_json(p.tool(msg_id, name, args, tool.confirm))

            texto, ok = "", False
            async for tipo, valor in toolrun.run_with_progress(registry, name, args):
                if tipo == "progress":
                    await self.ws.send_json(p.tool_progress(msg_id, name, valor))
                elif tipo == "artifact":
                    await self.ws.send_json(
                        p.artifact_ready(msg_id, valor.artifact_id, valor.name, valor.size)
                    )
                else:
                    texto, ok = valor, tipo == "result"

            await self.ws.send_json(p.tool_result(msg_id, name, texto))
            await self.ws.send_json(p.action_result(name, ok, texto))
        except Exception as e:
            log.exception("accion %s reventada", name)
            try:
                await self.ws.send_json(p.action_result(name, False, f"{type(e).__name__}: {e}"))
            except Exception:
                pass
        finally:
            # Mismo motivo que en handle_chat: si la accion muere esperando un
            # Si/No, la tarjeta se queda pegada en el movil pidiendo una respuesta
            # que ya no escucha nadie. Y el chat.end es lo unico que apaga el
            # indicador de turno del movil: sin el se queda "ejecutando..." para
            # siempre, que es como se ve un cuelgue desde el gym.
            self._drop_pending(msg_id)
            try:
                await self.ws.send_json(p.end(msg_id))
            except Exception:
                pass

    async def handle_chat(
        self,
        msg_id: str,
        brain: str,
        text: str,
        project: str | None = None,
        mode: str = "ask",
        model: str | None = None,
        effort: str | None = None,
        shell: str = "powershell",
        sesion: str | None = None,
        nueva: bool = False,
    ) -> None:
        async def pedir(name: str, args: dict[str, Any]) -> p.Reply:
            return await self.ask_permission(brain, msg_id, name, args)

        if brain == "app":
            # El Cerebro D no pasa por `pedir` y no es un descuido: los permisos
            # de la app los pide LA APP, en su propia ventana. Cuando saca una
            # tarjeta, sus botones llegan al movil dentro de app.state y se
            # pulsan con app.press -- o sea, se aprueba tocando el boton de
            # verdad, no una copia. Ver protocol.APP_PRESS.
            stream = app_brain.chat(text, sesion=sesion, nueva=nueva)
        elif brain == "claude":
            # model/effort solo los mira este cerebro: la IA local no tiene el
            # concepto (ver protocol.CHAT).
            stream = self.claude.chat(
                text, project=project, mode=mode, model=model, effort=effort, on_permission=pedir
            )
        elif brain == "terminal":
            # La Terminal NO pasa por `pedir`: el comando lo tecleo el usuario, asi
            # que no hay nada que aprobar (ver brain_terminal.py). `shell` decide
            # cmd o PowerShell; siempre corre como administrador.
            stream = brain_terminal.chat(text, shell=shell)
        else:
            stream = self.local.chat(text, on_tool_call=pedir)

        # El movil marca el turno como vivo al enviar y solo lo cierra con este
        # chat.end. Si el turno revienta por el camino (el cerebro lanza, o se cae
        # un send), sin este try/finally no sale ningun end y el movil se queda
        # esperando un turno que ya no existe -- que es exactamente como se ve un
        # cuelgue desde el gym. El end sale siempre, haya ido bien o mal.
        # El movil puede irse a mitad de turno (lo mandas a segundo plano para poner
        # musica, saltas de WiFi a datos) y su socket morir. Cuando eso pasa NO se
        # puede abortar el turno, y este es el bug que mas jodia: el cerebro de
        # Claude comparte UN solo cliente del SDK entre todas las conexiones (vive en
        # claude_brain, a nivel de modulo, para que la charla sobreviva a reconectar).
        # Si se corta su receive_response() a media respuesta, los mensajes que
        # quedan sin leer se quedan en su cola -- y el PROXIMO turno los lee desde
        # ahi, desincronizado: preguntas una cosa y Claude te contesta a la anterior.
        # A partir de la primera caida, "ya no funciona la comunicacion con Claude"
        # hasta reiniciar el PC o pulsar Nueva sesion. (Reproducido y verificado.)
        #
        # El arreglo: si un envio al movil falla, se deja de enviar pero se SIGUE
        # consumiendo el stream hasta el final. Drenarlo entero es lo unico que deja
        # el cliente del SDK limpio para el siguiente turno. El turno igual termina
        # su trabajo en el PC (lo que se pierde es solo pintarlo en un movil que ya
        # no esta escuchando); al reconectar, el siguiente mensaje ya va fino.
        movil_vivo = True

        async def emitir(payload: dict[str, Any]) -> None:
            nonlocal movil_vivo
            if not movil_vivo:
                return
            try:
                await self.ws.send_json(payload)
            except Exception:
                movil_vivo = False

        try:
            async for ev in stream:
                kind = ev["kind"]
                if kind == "text":
                    await emitir(p.delta(msg_id, ev["text"]))
                elif kind == "tool":
                    await emitir(p.tool(msg_id, ev["name"], ev["args"], ev["confirm"]))
                elif kind == "tool_progress":
                    await emitir(p.tool_progress(msg_id, ev["name"], ev["text"]))
                elif kind == "tool_result":
                    await emitir(p.tool_result(msg_id, ev["name"], ev["text"]))
                elif kind == "missing_tool":
                    await emitir(p.missing_tool(msg_id, ev["text"]))
                elif kind == "save_tool":
                    # Solo con el movil vivo: guardar una tool implica sus propios
                    # envios, y si el movil ya no esta no hay a quien confirmarselo.
                    # Su fallo tampoco debe cortar el drenado del stream.
                    if movil_vivo:
                        try:
                            await self.save_tool(ev["nombre"], ev["args"], ev["resultado"])
                        except Exception:
                            movil_vivo = False
                elif kind == "artifact":
                    await emitir(p.artifact_ready(msg_id, ev["artifact_id"], ev["name"], ev["size"]))
                elif kind == "cost":
                    await emitir(p.cost(ev["turn"], ev["total"]))
                elif kind == "limit":
                    # Los tokens de la cuenta, no el gasto del turno (ver
                    # protocol.LIMIT). Va fuera del msg_id a proposito: el limite
                    # no es de este turno, es de la cuenta entera.
                    await emitir(
                        p.limit(
                            ev["status"], ev["resets_at"], ev["tipo"],
                            ev["etiqueta"], ev["utilizacion"],
                        )
                    )
                elif kind == "error":
                    await emitir(p.error(ev["text"], msg_id))
        except Exception as e:
            # Aqui ya solo llega un error del propio cerebro (el stream lanzo): los
            # fallos de enviar al movil los absorbe emitir() sin cortar el bucle.
            log.exception("turno %s (%s) reventado", msg_id, brain)
            await emitir(p.error(f"El turno se corto: {type(e).__name__}: {e}", msg_id))
        finally:
            # Un permiso de este turno que siga esperando ya no lo va a contestar
            # nadie: su tarea se ha ido. Sin esto la tarjeta se queda pegada en el
            # movil y el usuario pulsa un boton que no resuelve nada.
            self._drop_pending(msg_id)
            await emitir(p.end(msg_id))


@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    # El mTLS ya ha filtrado a cualquiera sin certificado de cliente; el token
    # es la segunda vuelta de llave, por si el .p12 se escapa del movil.
    if not _authorized(websocket):
        await websocket.close(code=1008, reason="unauthorized")
        log.warning("conexion rechazada: token invalido")
        return

    await websocket.accept()
    peer = websocket.client.host if websocket.client else "?"
    log.info("movil conectado desde %s", peer)

    session = Session(websocket)
    await websocket.send_json(p.hello(brains=BRAINS, tools=registry.names()))

    try:
        while True:
            try:
                msg = json.loads(await websocket.receive_text())
            except json.JSONDecodeError:
                await websocket.send_json(p.error("json invalido"))
                continue

            kind = msg.get("type")

            if kind == p.PING:
                await websocket.send_json({"type": p.PONG})

            elif kind == p.CHAT:
                # En su propia tarea: un build tarda minutos y no debe bloquear
                # el resto de mensajes (ni el Si/No de un permiso).
                asyncio.create_task(
                    session.handle_chat(
                        msg.get("id", ""),
                        msg.get("brain", "local"),
                        msg.get("text", ""),
                        msg.get("project"),
                        msg.get("mode", "ask"),
                        # "" (un APK viejo no manda el campo) cuenta como "sin
                        # forzar nada": el .get(..., "") de abajo y el "or None"
                        # de aqui son el mismo criterio que ya usa "project".
                        msg.get("model") or None,
                        msg.get("effort") or None,
                        # "powershell" por defecto: un APK viejo no manda el campo
                        # y la Terminal ni existia (ver protocol.CHAT, v10).
                        msg.get("shell") or "powershell",
                        # Solo los mira el cerebro "app" (v12).
                        msg.get("sesion") or None,
                        bool(msg.get("nueva")),
                    )
                )

            elif kind == p.PERMISSION_REPLY:
                # Un APK viejo manda {allow: bool} y no conoce "save"; se traduce.
                # Cualquier accion que no sea de las tres conocidas cae en "deny":
                # ante un mensaje raro, la respuesta segura es no ejecutar.
                accion = msg.get("action")
                if accion not in ("allow", "deny", "save"):
                    accion = "allow" if msg.get("allow") else "deny"
                # answers solo viaja al contestar un AskUserQuestion: es
                # {pregunta: etiqueta}. Solo se aceptan pares texto->texto; un
                # valor raro se descarta y esa pregunta queda sin responder en vez
                # de colar basura en el updated_input de la tool.
                raw_answers = msg.get("answers")
                answers = None
                if isinstance(raw_answers, dict) and raw_answers:
                    answers = {
                        str(k): str(v)
                        for k, v in raw_answers.items()
                        if isinstance(k, str) and isinstance(v, str)
                    } or None
                session.resolve_permission(
                    msg.get("req_id", ""),
                    p.Reply(action=accion, nombre=str(msg.get("nombre") or ""), answers=answers),
                )

            elif kind == p.AI_STATUS:
                await websocket.send_json(p.ai_state(session.local.status()))

            elif kind == p.AI_SLEEP:
                await asyncio.to_thread(registry.call, "ai_sleep", {})
                await websocket.send_json(p.ai_state(session.local.status()))

            elif kind == p.STATS_REQUEST:
                asyncio.create_task(session.run_stats())

            elif kind == p.ACTION_REQUEST:
                args = msg.get("args")
                asyncio.create_task(
                    session.run_action(
                        msg.get("id", f"action-{uuid.uuid4().hex}"),
                        msg.get("name", ""),
                        args if isinstance(args, dict) else {},
                    )
                )

            elif kind == p.PROJECTS_REQUEST:
                asyncio.create_task(session.send_projects())

            elif kind == p.APP_REQUEST:
                asyncio.create_task(session.send_app_state())

            elif kind == p.SCREENS_REQUEST:
                asyncio.create_task(session.send_screens())

            elif kind == p.RTC_OFFER:
                asyncio.create_task(
                    session.start_video(
                        msg.get("sdp", ""), msg.get("tipo") or "offer", msg.get("monitor")
                    )
                )

            elif kind == p.RTC_STOP:
                asyncio.create_task(session.video.cerrar())

            elif kind == p.CLIP_WATCH:
                # Por defecto True: un clip.watch sin campo "on" es un movil
                # pidiendo que se vigile, no lo contrario.
                await session.clip_watch(msg.get("on", True) is not False)

            elif kind == p.CLIP_GET:
                # En su propia tarea: abrir el portapapeles puede tardar hasta un
                # cuarto de segundo si otra aplicacion lo tiene cogido (ver
                # portapapeles.INTENTOS), y eso no puede parar el socket.
                asyncio.create_task(session.clip_get())

            elif kind == p.CLIP_SET:
                texto = msg.get("text")
                if isinstance(texto, str):
                    asyncio.create_task(session.clip_set(texto[:MAX_CLIP]))

            elif kind in (p.APP_OPEN, p.APP_NEW, p.APP_PRESS, p.APP_STOP):
                # En su propia tarea, como el chat: traer la ventana al frente y
                # recorrer el arbol de accesibilidad tarda decimas, y no debe
                # bloquear el Si/No de un permiso que este esperando.
                asyncio.create_task(session.app_command(kind, msg))

            elif kind in (p.SCREEN_TAP, p.SCREEN_DRAG, p.SCREEN_SCROLL):
                # Tambien en su propia tarea: un arrastre son varios pasos con
                # pausas entre medias (ver appctl.pantalla_input.arrastrar), y
                # eso no puede parar el bucle que atiende al resto del socket.
                asyncio.create_task(session.screen_gesture(kind, msg))

            elif kind == p.SCREEN_COPY:
                # Propia tarea: el Ctrl+C espera un respiro a que la app
                # escriba en el portapapeles, y eso no puede bloquear el socket.
                asyncio.create_task(session.screen_copy())

            elif kind == p.SCREEN_TYPE:
                asyncio.create_task(session.screen_type(str(msg.get("text") or "")))

            elif kind == p.SCREEN_KEY:
                asyncio.create_task(session.screen_key(str(msg.get("tecla") or "")))

            elif kind == p.SESSION_NEW:
                # Olvida el contexto de ESE cerebro (ver protocol.SESSION_NEW):
                # para "claude" cierra el ClaudeSDKClient compartido (la proxima
                # vez que se hable con el reconecta desde cero); para "local"
                # limpia el historial. No hace falta await_for ninguna tarea en
                # marcha: si habia un turno vivo de este cerebro, su propio
                # try/except en handle_chat absorbe el corte como un error
                # normal de turno.
                brain_pedido = msg.get("brain", "claude")
                if brain_pedido == "claude":
                    await claude_brain.close()
                elif brain_pedido == "local":
                    local_brain.reset()
                # "terminal" no guarda contexto (no hay LLM): no hay nada que
                # resetear en el PC, solo se confirma para que el movil limpie su
                # propia conversacion.
                log.info("nueva sesion pedida: %s", brain_pedido)
                await websocket.send_json(p.session_new_ok(brain_pedido))

            elif kind == p.TOOLS_RELOAD:
                # Recarga en caliente: cierra el bucle de auto-ampliacion sin reiniciar.
                await asyncio.to_thread(registry.load)
                await websocket.send_json(p.hello(brains=BRAINS, tools=registry.names()))

            else:
                await websocket.send_json(p.error(f"tipo desconocido: {kind}", msg.get("id")))

    except WebSocketDisconnect:
        log.info("movil desconectado (%s)", peer)
    finally:
        # El video SI se cierra aqui, a diferencia de los cerebros: sus
        # candidatos ICE apuntan a este movil concreto, asi que no le sirve de
        # nada a la proxima conexion. Sin esto quedaria un emisor capturando y
        # codificando la ventana a 30 fps para un socket que ya no existe --
        # trabajo invisible que solo se nota en que el PC va mas lento.
        await session.video.cerrar()
        # El vigilante del portapapeles, por el mismo motivo: empujaba texto por
        # ESTE socket. Sin esto queda un bucle preguntandole a Windows por el
        # portapapeles cada medio segundo, para siempre, por cada reconexion del
        # movil -- y son muchas (wifi a datos, la app al fondo, el backoff).
        session.parar_clip()
    # Ya NO se cierra claude_brain aqui: es compartido entre conexiones (ver
    # arriba) precisamente para que la charla sobreviva a esta desconexion.
