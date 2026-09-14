"""Cerebro A: Claude Code, via el Agent SDK.

A diferencia de la IA local (que traduce intencion a una tool de una lista
cerrada), este razona y edita codigo de verdad. Por eso aqui SI hay shell: la
frontera de seguridad es que sus permisos se reenvian al movil (seccion 9).

El SDK lanza el CLI de Claude Code como subproceso. Ese CLI no esta en el PATH:
lo trae la app de escritorio (ver claude_cli.py) y necesita haber hecho login
una vez (ejecutar `claude` en una terminal y usar `/login`).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    RateLimitEvent,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from . import paths
from .claude_cli import describe_search, find_cli
from .ratelimit_proxy import proxy

log = logging.getLogger("controladora.claude")

# Tools de Claude que no cambian nada: preguntar por cada una desde el movil
# seria insufrible y no protege de nada. Todo lo que muta algo (Write, Edit,
# Bash...) SI pasa por el Si/No.
AUTO_ALLOW = {
    "Read",
    "Glob",
    "Grep",
    "NotebookRead",
    "TodoWrite",
    "WebFetch",
    "WebSearch",
    "Task",
}

# NO hay tope de gasto (`max_budget_usd`). Aqui habia uno de 5 $ por conversacion,
# y hay que explicar por que se ha quitado para que no vuelva:
#
# El CLI esta autenticado con la SUSCRIPCION, no con una API key. Ese numero de
# dolares no es dinero que se cobre a nadie: es el coste equivalente en API que el
# SDK va estimando. Con el saldo extra desactivado en la cuenta, el gasto real es
# 0 siempre; lo unico que se agota son los tokens de la ventana de 5 horas, y de eso
# ya avisa la cuenta sola (ver los eventos "limit" de mas abajo).
#
# O sea que el tope no protegia de ningun gasto: solo cortaba la conversacion mucho
# antes que el limite de verdad, y encima duraba hasta reiniciar el PC (el cliente
# del SDK sobrevive a las reconexiones del movil), asi que el corte llegaba en mitad
# de una charla que no tenia nada que ver con lo que lo agoto. Se quedaba corto por
# abajo y no protegia por arriba: es el peor sitio posible para un limite.
#
# La red de seguridad de "no gastar tokens en cosas que puede hacer una IA local"
# sigue existiendo, pero donde debe: en elegir el cerebro (IA local vs Claude) y en
# las acciones directas que no pasan por ningun LLM (ver server.run_action).

# Los tipos de limite de cuenta que manda el CLI, traducidos a como se dicen en el
# movil. El texto va aqui y no en Kotlin porque es vocabulario de la cuenta de
# Claude, no de la app: si maniana aparece otra ventana, se aniade en un solo sitio.
LIMITES = {
    "five_hour": "límite de 5 h",
    "seven_day": "límite semanal",
    "seven_day_opus": "límite semanal de Opus",
    "seven_day_sonnet": "límite semanal de Sonnet",
    "overage": "saldo extra",
}

# Los tres modos del movil (ver ChatViewModel.Modo), traducidos al permission_mode
# que entiende el SDK. "ask" es el de siempre: cada tool que no este en AUTO_ALLOW
# para por can_use_tool y el movil decide. "auto" salta ese paso entero -- el SDK
# ni siquiera llama a can_use_tool en bypassPermissions, asi que no sale tarjeta.
# "plan" deja a Claude leer y proponer sin tocar nada hasta que el pida salir del
# modo plan (ExitPlanMode), y ESE si pasa por can_use_tool como cualquier otra tool.
MODE_MAP = {"ask": "default", "auto": "bypassPermissions", "plan": "plan"}

# Los niveles de "esfuerzo" que de verdad entiende el SDK (EffortLevel en
# claude_agent_sdk/types.py). Se valida contra esto antes de pasarselo al SDK:
# un valor raro (APK viejo mandando basura, o un campo corrupto) cae a None en
# vez de reventar la conexion -- mismo criterio que un permission.reply con una
# accion desconocida cae en "deny".
EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}

SYSTEM_PROMPT = """Estas conectado a un chat de movil: Ale te escribe desde el gym, no desde el escritorio.
Lee en una pantalla pequena, de pie y con prisa.

- Responde en espanol y CORTO. Maximo tres lineas por mensaje. Si no cabe en tres
  lineas, es que estas contando el proceso en vez del resultado: cuenta solo el resultado.
- Nada de preambulos ("voy a proceder a...", "perfecto, entiendo que..."). Primera
  linea = que has hecho o que has encontrado. Sin titulos, sin listas de fases, sin resumenes
  de lo que acabas de leer.
- No pegues codigo en el chat salvo que te lo pidan. Haz el cambio y di que cambiaste, en una linea.
- ANTES de editar o de correr algo, di en UNA linea que vas a hacer y por que. Ese aviso es lo
  unico que Ale ve para decidir si te da permiso: si no lo dices, esta aprobando a ciegas.
- Si necesitas una decision suya, pregunta UNA cosa concreta. Nunca cinco opciones.
"""


class ClaudeCliNotFound(Exception):
    """No aparece el ejecutable. Es un problema distinto de no haber hecho login.

    Estaban mezclados en la misma excepcion, y eso hacia que el mensaje del movil
    culpase al login cuando el fallo era la ruta, y al reves. Son dos arreglos
    completamente distintos (instalar/localizar vs `claude` + `/login`), asi que
    son dos excepciones.
    """


class ClaudeBrain:
    """Una instancia por servidor, no por conexion del movil (ver server.py).

    El cliente del SDK -- y con el, la memoria de la conversacion -- sobrevive a
    que el movil se reconecte. Antes vivia dentro de la Session de cada
    WebSocket y se cerraba al desconectar, asi que Claude olvidaba todo en
    cuanto saltabas de WiFi a datos o el movil pasaba un rato en segundo plano.
    """

    def __init__(self) -> None:
        self._client: ClaudeSDKClient | None = None
        self._project: str | None = None
        self._applied_mode: str | None = None
        # Modelo/esfuerzo con los que se abrio el cliente actual. "model" se
        # puede cambiar en caliente (client.set_model, ver _ensure_client);
        # "effort" NO -- el SDK no tiene set_effort, asi que cambiarlo fuerza
        # una reconexion, igual que cambiar de proyecto.
        self._applied_model: str | None = None
        self._applied_effort: str | None = None
        self._cost_total = 0.0
        # Ultimo estado del limite de la cuenta que dijo el CLI. Se guarda porque
        # el dato bueno (a que hora se restablece) SOLO llega en el rate_limit_event,
        # y el 429 que corta el turno puede llegar despues, en otro turno o incluso
        # tras una reconexion. Sin recordarlo, el movil diria "sin tokens" sin poder
        # decir hasta cuando, que es justo lo unico que se quiere saber.
        self._limite: dict[str, Any] | None = None
        # Ultimo status que dijo el CLI ("allowed"/"allowed_warning"/"rejected").
        # No vive dentro de _limite porque _evento_limite lo recibe aparte; se
        # recuerda para que el refresco del proxy (que rellena el % por debajo del
        # ~90%) NO degrade a "allowed" un aviso que el evento nativo acaba de dar.
        self._ultimo_status = "allowed"
        # El handler de permisos de la conexion ACTUAL. Tiene que releerse en
        # cada turno, no capturarse una vez al crear el cliente: si el cliente
        # sobrevive a una reconexion (ver arriba) pero can_use_tool cerrase sobre
        # el on_permission de la conexion vieja, un permiso pedido en la sesion
        # nueva intentaria mandar la tarjeta por un WebSocket ya muerto.
        self._on_permission: Callable[[str, dict[str, Any]], Any] | None = None

    @property
    def cost_total(self) -> float:
        return self._cost_total

    @property
    def limite(self) -> dict[str, Any] | None:
        """Ultimo estado conocido del limite de tokens de la cuenta, o None."""
        return self._limite

    def _evento_limite(self, status: str) -> dict[str, Any]:
        """El evento que va al movil, mezclando [status] con lo ultimo que se sabe.

        [status] se pasa aparte porque un 429 seco (ver el ResultMessage de chat())
        dice "rechazado" sin traer datos: la hora de reset es la del ultimo
        rate_limit_event que llego, no una nueva.
        """
        info = self._limite or {}
        tipo = info.get("tipo") or "five_hour"
        self._ultimo_status = status
        return {
            "kind": "limit",
            "status": status,
            "resets_at": info.get("resets_at"),
            "tipo": tipo,
            "etiqueta": LIMITES.get(tipo, tipo),
            "utilizacion": info.get("utilizacion"),
        }

    def _cwd_for(self, project: str | None) -> str:
        if project:
            p = paths.project(project)
            if p:
                return p["path"]
        # Sin proyecto: la raiz del propio sistema, para poder ampliarse a si mismo.
        return str(Path(__file__).resolve().parent.parent.parent)

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None
            self._applied_mode = None
            self._applied_model = None
            self._applied_effort = None
        self._on_permission = None

    async def _ensure_client(
        self,
        project: str | None,
        mode: str,
        model: str | None,
        effort: str | None,
        on_permission: Callable[[str, dict[str, Any]], Any] | None,
    ) -> ClaudeSDKClient:
        # Se actualiza SIEMPRE, tanto si se reutiliza el cliente como si no: es
        # lo que hace que can_use_tool (mas abajo) hable con la conexion de
        # movil que esta viva ahora mismo, no con la que habia cuando se creo
        # el cliente hace tres reconexiones.
        self._on_permission = on_permission

        # Cambiar de proyecto = cambiar de cwd, y el cwd se fija al conectar.
        # Cambiar de effort tambien obliga a reconectar: el SDK no tiene
        # set_effort (solo set_permission_mode y set_model), asi que no hay
        # forma de aplicarlo sobre un cliente ya abierto.
        reutilizable = (
            self._client is not None
            and self._project == project
            and effort == self._applied_effort
        )
        if reutilizable:
            # Mismo cliente, pero el movil pudo cambiar modo/modelo desde el
            # ultimo turno (los selectores no reconectan, solo avisan aqui).
            if mode != self._applied_mode:
                await self._client.set_permission_mode(MODE_MAP.get(mode, "default"))
                self._applied_mode = mode
            if model != self._applied_model:
                # A diferencia de effort, esto SI lo soporta el SDK en caliente
                # y preserva la conversacion (client.set_model, ver client.py).
                await self._client.set_model(model)
                self._applied_model = model
            return self._client

        await self.close()

        # close() (justo arriba) hace self._on_permission = None. La asignacion
        # del principio de esta funcion vale para la rama reutilizable -- que
        # sale por `return` ANTES de este close -- pero en la rama de cliente
        # nuevo el close la borra. Hay que volver a fijarla AQUI, despues del
        # close: si no, el can_use_tool de mas abajo naceria con
        # _on_permission=None y, en el PRIMER turno de cada cliente, denegaria en
        # silencio cualquier AskUserQuestion (sin mandar la question.request al
        # movil) y autoaprobaria cualquier permiso sin ensenar tarjeta. Este era
        # el bug de "las preguntas de Claude no salen nunca". (Reproducido.)
        self._on_permission = on_permission

        cli = find_cli()
        if not cli:
            # Con la lista de sitios mirados delante, esto se diagnostica desde el
            # movil sin tener que ir al PC a adivinar. Sin ella ya costo media hora.
            log.error("CLI de Claude Code no encontrado. Busqueda:\n%s", describe_search())
            raise ClaudeCliNotFound(
                "No encuentro el CLI de Claude Code. Deberia estar en "
                "%APPDATA%\\Claude\\claude-code\\<version>\\claude.exe\n\n"
                + describe_search()
            )

        async def can_use_tool(tool_name: str, input_data: dict[str, Any], context: Any):
            # self._on_permission, no el "on_permission" de este scope: el cliente
            # puede sobrevivir a varias reconexiones del movil, y en cada turno
            # _ensure_client() actualiza self._on_permission a la conexion viva
            # ahora mismo. Si esta closure capturase el parametro de cuando se
            # creo el cliente, un permiso pedido tras reconectar intentaria
            # mandar la tarjeta por un WebSocket ya cerrado.
            # AskUserQuestion se resuelve SIEMPRE preguntando al movil, incluso en
            # modo Automatico: una pregunta de opcion multiple no tiene "autoaprobado"
            # que valga -- si nadie elige, no hay respuesta que darle a la tool. Por
            # eso va antes que el corto de AUTO_ALLOW y que el de modo auto. La
            # respuesta no es allowed/denied: es la opcion elegida, que el CLI lee
            # de updated_input["answers"] ({texto_pregunta: etiqueta}, ver
            # protocol.QUESTION_REQUEST y server.ask_permission).
            if tool_name == "AskUserQuestion":
                if self._on_permission is None:
                    return PermissionResultDeny(message="No hay movil conectado para responder la pregunta.")
                reply = await self._on_permission(tool_name, input_data)
                if reply.allowed and reply.answers:
                    return PermissionResultAllow(
                        updated_input={**input_data, "answers": reply.answers}
                    )
                return PermissionResultDeny(message="El usuario no respondio la pregunta desde el movil.")

            if tool_name in AUTO_ALLOW or self._on_permission is None:
                return PermissionResultAllow(updated_input=input_data)

            # Cinturon y tirantes: en teoria el SDK ni siquiera llama a esta
            # funcion cuando permission_mode es "bypassPermissions" (modo
            # Automatico del movil), pero en la practica seguia pidiendo
            # tarjeta -- la CLI de esta version no lo suprime del todo. En vez
            # de confiar en eso, se comprueba aqui el modo que de verdad esta
            # activo ahora mismo (self._applied_mode, actualizado en
            # _ensure_client en cada turno) y se autoaprueba directamente.
            if self._applied_mode == "auto":
                return PermissionResultAllow(updated_input=input_data)

            reply = await self._on_permission(tool_name, input_data)
            if reply.allowed:
                return PermissionResultAllow(updated_input=input_data)
            return PermissionResultDeny(message="El usuario no lo aprobo desde el movil.")

        # El proxy que lee el % de tokens de las cabeceras del propio CLI (ver
        # ratelimit_proxy.py). Fallo blando: si no levanta, base es None, NO se
        # pone ANTHROPIC_BASE_URL y el CLI habla directo con Anthropic igual que
        # siempre. Nunca debe impedir que el chat funcione.
        base = await proxy.start()
        env = {"ANTHROPIC_BASE_URL": base} if base else {}

        options = ClaudeAgentOptions(
            cli_path=cli,
            cwd=self._cwd_for(project),
            system_prompt=SYSTEM_PROMPT,
            can_use_tool=can_use_tool,
            permission_mode=MODE_MAP.get(mode, "default"),
            model=model,
            effort=effort,
            env=env,
        )

        client = ClaudeSDKClient(options=options)
        await client.connect()
        self._client = client
        self._project = project
        self._applied_mode = mode
        self._applied_model = model
        self._applied_effort = effort
        log.info(
            "claude conectado (proyecto=%s, cwd=%s, modo=%s, modelo=%s, esfuerzo=%s)",
            project, options.cwd, mode, model or "(defecto)", effort or "(defecto)",
        )
        return client

    async def chat(
        self,
        text: str,
        project: str | None = None,
        mode: str = "ask",
        model: str | None = None,
        effort: str | None = None,
        on_permission: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Una vuelta de conversacion. Emite los mismos eventos que LocalBrain.

        [model]: alias del SDK ("sonnet", "opus", "haiku") o None = el que
        decida la CLI. Cambiarlo aplica en caliente sin perder la conversacion.

        [effort]: "low"/"medium"/"high"/"xhigh"/"max" o None = el que decida la
        CLI. Se valida contra EFFORT_LEVELS; un valor no reconocido se trata
        como None. A diferencia de [model], cambiarlo fuerza una reconexion
        (pierde el hilo), porque el SDK no tiene forma de aplicarlo en caliente.

        [mode]: "ask" (de siempre), "auto" (bypassPermissions, sin tarjetas) o
        "plan" (Claude solo lee y propone, ver MODE_MAP).
        """
        modelo = model or None
        esfuerzo = effort if effort in EFFORT_LEVELS else None
        if effort and esfuerzo is None:
            log.warning("effort desconocido ignorado: %r", effort)

        try:
            client = await self._ensure_client(project, mode, modelo, esfuerzo, on_permission)
        except ClaudeCliNotFound as e:
            yield {"kind": "error", "text": str(e)}
            return
        except Exception as e:
            yield {"kind": "error", "text": f"No pude arrancar Claude Code: {type(e).__name__}: {e}"}
            return

        # Texto acumulado del turno: sin sesion iniciada, el CLI no lanza una
        # excepcion -- contesta con un AssistantMessage normal ("Not logged in,
        # please run /login") y solo se sabe que fue un error al llegar el
        # ResultMessage.is_error final. Sin este acumulado, el movil veria ese
        # texto suelto sin ninguna pista de que hacer con el.
        texto_turno = ""

        try:
            await client.query(text)

            async for message in client.receive_response():
                # Los tokens de la cuenta. El CLI manda esto cuando el estado
                # CAMBIA (allowed -> allowed_warning -> rejected), no en cada
                # turno, asi que se guarda: es la unica fuente de la hora a la que
                # se restablece la ventana.
                if isinstance(message, RateLimitEvent):
                    info = message.rate_limit_info
                    self._limite = {
                        "resets_at": info.resets_at,
                        "tipo": info.rate_limit_type or "five_hour",
                        "utilizacion": info.utilization,
                    }
                    log.info(
                        "limite de cuenta: %s (%s, reset=%s)",
                        info.status,
                        info.rate_limit_type,
                        info.resets_at,
                    )
                    yield self._evento_limite(info.status)

                elif isinstance(message, AssistantMessage):
                    # El turno muere por falta de tokens: el CLI lo cuenta aqui,
                    # sin traer hora de reset. Se rellena con lo ultimo que se supo.
                    if message.error == "rate_limit":
                        yield self._evento_limite("rejected")

                    for block in message.content:
                        if isinstance(block, TextBlock):
                            texto_turno += block.text
                            yield {"kind": "text", "text": block.text}
                        elif isinstance(block, ToolUseBlock):
                            # AskUserQuestion NO se pinta como tarjeta de tool: ya
                            # viaja como question.request (la burbuja/recuadro con
                            # botones, ver can_use_tool -> ask_permission). Emitir
                            # ademas el tool_use dejaria una tarjeta muda de
                            # "AskUserQuestion" al lado de la pregunta de verdad.
                            if block.name == "AskUserQuestion":
                                continue
                            yield {
                                "kind": "tool",
                                "name": block.name,
                                "args": block.input if isinstance(block.input, dict) else {},
                                "confirm": block.name not in AUTO_ALLOW,
                            }

                elif isinstance(message, ResultMessage):
                    coste = getattr(message, "total_cost_usd", None) or 0.0
                    self._cost_total += coste

                    # Ultima red: si la llamada murio con un 429 y no llego ni
                    # rate_limit_event ni AssistantMessage.error, el turno se
                    # cortaria con un "error (success)" incomprensible. Un 429 es
                    # SIEMPRE falta de tokens, se diga como se diga.
                    if message.api_error_status == 429:
                        yield self._evento_limite("rejected")

                    if message.is_error:
                        if "not logged in" in texto_turno.lower() or "/login" in texto_turno.lower():
                            yield {
                                "kind": "error",
                                "text": "Claude Code no tiene sesión iniciada. En el PC: ejecuta `claude` y usa `/login`",
                            }
                            await self.close()
                        else:
                            yield {
                                "kind": "error",
                                "text": f"Claude Code devolvió un error ({message.subtype}).",
                            }

                    yield {
                        "kind": "cost",
                        "turn": coste,
                        "total": self._cost_total,
                    }

                    # Rellena el % que el CLI calla por debajo del ~90%: el proxy
                    # (ratelimit_proxy.py) lo saca de las cabeceras de esta misma
                    # respuesta. Si el rate_limit_event nativo ya lo trajo (cerca
                    # del tope), esto solo confirma el mismo numero. El status se
                    # respeta: se usa el de la cabecera si viene, si no el ultimo
                    # conocido -- nunca se degrada un aviso a "allowed".
                    lectura = proxy.latest()
                    fh = (lectura or {}).get("five_hour")
                    if fh and fh.get("utilization") is not None:
                        self._limite = {
                            "resets_at": fh.get("resets_at") or (self._limite or {}).get("resets_at"),
                            "tipo": "five_hour",
                            "utilizacion": fh["utilization"],
                        }
                        yield self._evento_limite(fh.get("status") or self._ultimo_status)

        except Exception as e:
            texto = str(e)
            if "not logged in" in texto.lower() or "login" in texto.lower():
                # La sesion se pierde de vez en cuando; decirlo claro ahorra
                # media hora de depuracion a ciegas.
                yield {
                    "kind": "error",
                    "text": (
                        "Claude Code no tiene sesion iniciada. En el PC: "
                        "ejecuta `claude` y usa `/login`"
                    ),
                }
            else:
                yield {"kind": "error", "text": f"{type(e).__name__}: {texto}"}
            await self.close()
