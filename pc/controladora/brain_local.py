"""Cerebro B: la IA local (Ollama).

Es **la administradora del PC**: tiene que poder hacer cualquier cosa que se
pueda hacer en este ordenador, como una persona sentada delante. No es un
lanzador de cuatro tools.

Que sea barata NO significa que sea limitada -- esa confusion estaba metida en
el codigo y es lo que hacia que "no supiera hacer nada". Lo barato es el cerebro
(un 8B local, sin tokens que pagar); lo que puede hacer es todo, porque para lo
que no tiene tool tiene `run_shell`, y con PowerShell se hace cualquier cosa en
Windows. Las tools especificas de `pc/tools/` no son su techo: son **atajos**
para lo que se repite mucho, para no ir aprobando el mismo comando cada dia.

La frontera de seguridad no es lo que puede pedir, es que TU lo apruebas: cada
comando libre pasa por Permitir/Denegar en el movil y lo que lees es lo que corre
(ARQUITECTURA.md seccion 9). Por eso puede proponer lo que sea sin que eso la
haga peligrosa.

Ciclo de vida: no reside en memoria. Ollama la carga en la primera peticion y la
descarga sola pasado `keep_alive`. Dormirla = keep_alive 0 (tool ai_sleep).
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from . import paths, toolrun
from .protocol import Reply
from .registry import Registry

log = logging.getLogger("controladora.local")

# Cuantas rondas de tool calling seguidas se permiten antes de cortar. Sin esto,
# un modelo pequeno puede entrar en bucle llamando a la misma tool para siempre.
#
# 5 se quedaba corto desde que administra el PC de verdad y no solo dispara una
# tool suelta: "abre AnyDesk y dime el codigo" ya son mirar si esta, lanzarlo,
# esperar y leer el ID -- cuatro rondas, y a la quinta se cortaba sola justo
# antes de contestar. El tope existe por los bucles, no para racionarle pasos.
MAX_ROUNDS = 10

# Contexto del modelo, en tokens. ESTO ERA UN BUG GORDO Y SILENCIOSO: Ollama usa
# num_ctx=4096 por defecto si no se le dice otra cosa, y cuando la conversacion
# lo desborda NO avisa -- trunca por el principio, que es justo donde vive el
# system prompt. O sea: a las pocas vueltas el modelo dejaba de saber que existia
# run_shell y empezaba a contestar "no puedo hacer eso", que es exactamente el
# sintoma de "la IA local no sabe hacer NADA" y no tenia nada que ver con lo
# tonta que sea: se le estaba borrando la hoja de instrucciones por debajo.
# Se llenaba rapido, ademas: 15 esquemas de tools son ~1.5k tokens ANTES de
# hablar, y un tail de log de Gradle son 40 lineas mas por cada build.
# qwen3:8b admite 32k nativos; 16k con Q4 son ~1 GB extra de KV cache en una
# 1080 Ti de 11 GB, que sobra. Configurable en paths.json (ollama.num_ctx).
DEFAULT_NUM_CTX = 16384

# Cuantos mensajes se conservan ademas del system prompt. El recorte va por el
# medio (se queda con los mas nuevos) y NUNCA toca el system prompt: es
# exactamente lo contrario de lo que hacia Ollama al desbordar. El limite de
# tokens de arriba es el techo duro; esto evita acercarse a el en una charla
# larga, sobre todo porque cada resultado de tool puede traer 40 lineas de log.
MAX_HISTORY = 24

# Ollama usa temperature 0.8 por defecto: bien para escribir, muy mal para esto.
# Elegir herramienta no es creativo -- "dame el codigo de AnyDesk" tiene UNA
# respuesta correcta, y con 0.8 la misma frase a veces llamaba a `anydesk_id` y a
# veces se inventaba que no se podia. Verificado: esa frase fallo 1 de 4 veces con
# el modelo eligiendo bien las otras 3, y no habia ninguna diferencia entre los
# intentos salvo el muestreo. No se pone a 0 del todo para que la frase con la que
# te contesta no salga acartonada: lo que se quiere es que no dude de QUE hacer.
DEFAULT_TEMPERATURE = 0.2

SYSTEM_PROMPT = """Eres la IA que ADMINISTRA el PC de Ale. El te escribe por un chat desde el movil y espera que manejes el ordenador entero por el, como lo haria una persona sentada delante del teclado.

Puedes hacer CUALQUIER cosa que se pueda hacer en este PC: abrir y cerrar programas, crear, mover, copiar y borrar ficheros, mirar dentro de carpetas, ver y matar procesos, servicios, red, discos, usuarios, energia, el registro, instalar cosas... Si se hace con PowerShell, puedes hacerlo. NO estas limitada a la lista de herramientas: la lista son atajos, no tu techo.

Como decides que usar:
- Si hay una herramienta especifica para lo que te piden, usala. Son atajos para lo que se repite mucho y no piden aprobacion.
- Para TODO lo demas, usa run_shell con el comando de PowerShell que haga falta. Es tu herramienta PRINCIPAL, no el ultimo recurso ni algo excepcional. Ale lee el comando en el movil y lo aprueba antes de que corra: por eso puedes proponer lo que sea.
- Si algo necesita varios pasos (buscar un programa y luego lanzarlo, mirar algo y luego actuar), hazlos de uno en uno con run_shell hasta terminar. No te rindas tras el primer comando ni le pidas a Ale que lo haga el.
- SI PUEDES hacer cosas de administrador: instalar y desinstalar programas, servicios, HKLM del registro, drivers, configuracion del sistema, ficheros de Archivos de programa. Para eso usa run_shell con admin=true. A Ale le sale una tarjeta roja avisandole y decide el. NUNCA digas que no puedes hacer algo por permisos: pidelo con admin=true.
- Si un comando normal falla con "Access denied", "Acceso denegado" o pide elevacion, NO te rindas: repitelo con admin=true.
- Para INSTALAR un programa son SIEMPRE DOS pasos, en este orden. No te saltes el primero:
  1) run_shell SIN admin: winget search "<nombre>"
  2) run_shell CON admin=true, copiando un Id TAL CUAL de la salida del paso 1:
     winget install --id <Id> --silent --accept-package-agreements --accept-source-agreements
  Los Id de winget no se pueden deducir del nombre (el de 7-Zip es "7zip.7zip", no "7-Zip"). Si escribes un --id que no has visto salir del search, sera falso y la instalacion fallara. NO te lo inventes NUNCA, y no supongas que hay un instalador en Descargas.
- Para desinstalar: winget uninstall --id <Id> --silent, con admin=true.
- No pongas admin=true por si acaso. Casi nada lo necesita: leer, mirar, listar, abrir programas normales y tocar ficheros del usuario van SIN admin. Pedir admin de mas hace que Ale tenga que leerse una tarjeta roja para nada y acaba aprobando sin mirar.
- Si un programa no esta en tus herramientas (AnyDesk, un navegador, lo que sea), NO digas que no puedes: busca el ejecutable con un comando y lanzalo con otro.

Reglas:
- Responde SIEMPRE en espanol, breve y directo. Estas en un chat de movil.
- Da el DATO que te piden, no un resumen vago. Si te preguntan cuanto espacio queda, di el numero que salio en el comando; si te piden un codigo o un ID, di el codigo. Nunca contestes "tiene espacio suficiente" en vez del numero.
- Si te hablan sin pedirte una accion (un saludo, una duda sobre el PC, una pregunta
  sobre lo que acabas de hacer), contesta con normalidad. No hace falta que toda
  respuesta sea una herramienta, y NO digas "accion no disponible" a una conversacion.
- Si no sabes que proyecto es, usa list_projects antes de preguntar.
- Si te piden compilar Y ademas mandar/instalar/desplegar en el movil, usa build_and_send (no build_gradle solo). Compila y manda el APK al chat del movil por la misma conexion (sin USB, sin adb, sin que el movil necesite wifi ni depuracion inalambrica activa): el usuario lo instala tocando "Instalar" cuando le llega el aviso.
- build_gradle, build_and_send y unity_build NO necesitan que el IDE este abierto: compilan por linea de comandos. Si te piden compilar/desplegar, NO abras el IDE tambien salvo que te lo pidan explicitamente para otra cosa (ver o editar codigo). Abrir el IDE a la vez que se compila puede hacer que los dos fallen: compiten por los mismos ficheros de cache de Gradle.
- adb_install y adb_connect son para cuando el movil YA esta conectado por USB o adb inalambrico (p. ej. estas en casa, delante del PC). Para "mandame/instalame la build" desde fuera de casa, usa build_and_send: no depende de adb.
- Al usar run_shell: pon en "motivo" que consigue el comando en una linea (lo lee el usuario para decidir), y si el comando sirve tal cual mas de una vez, propon un "nombre_tool" en snake_case para que pueda guardarlo como herramienta permanente.
- Si ya existe una herramienta especifica para algo, usa esa y NO run_shell. Las herramientas concretas no necesitan aprobacion.
- Di "Accion no disponible: <que haria falta>" SOLO cuando haga falta PROGRAMAR algo de verdad (varios ficheros, logica, una API que no conoces). Casi nunca es el caso: si se resuelve con uno o varios comandos, son comandos, y eso lo haces tu. No lo digas nunca solo porque no tengas una tool con ese nombre.
- No inventes rutas, nombres de proyecto, versiones ni salidas de comandos. Si no lo sabes, miralo con un comando. Si un comando falla, lee el error y prueba otra cosa.
"""


def _hechos_pc() -> str:
    """Los cuatro datos del PC que administra, para no tener que adivinarlos.

    Nace de un fallo real: "apunta esto en un fichero del escritorio" acababa en
    `C:\\Users\\Ale\\Desktop\\...`, que no existe. El modelo dedujo el usuario de
    Windows del nombre que sale en el prompt ("el PC de Ale") -- porque era lo
    unico que tenia. El usuario real es otro, asi que el comando fallaba y Ale
    veia "no se pudo crear el fichero" sin ninguna pista de por que.

    Decirle "no inventes rutas" no arregla eso: no se estaba inventando por
    listilla, es que no habia forma de que lo supiera. Esto se lo dice, y cuesta
    unas pocas decenas de tokens de un contexto de 16k que ademas es gratis.

    Se calcula una vez por proceso (los perfiles de Windows no se mueven en
    caliente) y va al final del system prompt.
    """
    import os
    import platform
    import string

    inicio = Path(os.path.expanduser("~"))
    # El escritorio se mueve si hay OneDrive con Escritorio sincronizado, y en un
    # Windows en español la carpeta puede llamarse "Escritorio". Se comprueba en
    # disco en vez de dar por buena la convencion.
    candidatos = [
        inicio / "Desktop",
        inicio / "Escritorio",
        inicio / "OneDrive" / "Desktop",
        inicio / "OneDrive" / "Escritorio",
    ]
    escritorio = next((c for c in candidatos if c.is_dir()), inicio / "Desktop")

    unidades = [f"{L}:" for L in string.ascii_uppercase if Path(f"{L}:\\").exists()]

    return f"""

Datos de ESTE PC (son ciertos, usalos y no los deduzcas de otra cosa):
- Sistema: {platform.system()} {platform.release()}, equipo "{platform.node()}"
- Usuario de Windows: {os.getlogin()}  (OJO: NO es el nombre de la persona, no lo adivines por como se llame quien te habla)
- Carpeta personal: {inicio}
- Escritorio: {escritorio}
- Descargas: {inicio / "Downloads"}
- Unidades con datos: {", ".join(unidades)}
- Rutas con espacios: entrecomillalas en PowerShell.
"""


class OllamaDown(Exception):
    """Ollama no responde. Se distingue de un fallo del modelo a proposito."""


def _post(url: str, payload: dict[str, Any], timeout: float = 300) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        raise OllamaDown(f"Ollama no responde en {url}: {e.reason}") from e


class LocalBrain:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self._history: list[dict[str, Any]] = []

    @property
    def _cfg(self) -> dict[str, Any]:
        return paths.ollama()

    def reset(self) -> None:
        self._history = []

    def status(self) -> str:
        """Que modelos hay cargados en VRAM ahora mismo."""
        url = self._cfg.get("url", "http://127.0.0.1:11434")
        try:
            with urllib.request.urlopen(f"{url}/api/ps", timeout=10) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            return f"Ollama no responde: {e}"

        cargados = data.get("models") or []
        if not cargados:
            return "IA local dormida (0 VRAM en uso)"

        partes = []
        for m in cargados:
            vram = m.get("size_vram", 0) / 1024 / 1024 / 1024
            partes.append(f"{m.get('name')} ({vram:.1f} GB VRAM)")
        return "IA local despierta: " + ", ".join(partes)

    def _trim(self) -> None:
        """Poda la conversacion conservando SIEMPRE el system prompt.

        El recorte tiene que caer en un sitio valido: si se corta justo detras de
        un mensaje del asistente que pidio tools, quedan mensajes `tool` sueltos
        respondiendo a una llamada que ya no esta en el historial, y Ollama
        rechaza esa conversacion. Por eso se avanza el corte hasta el siguiente
        mensaje de usuario, que siempre es un punto limpio para empezar.
        """
        if len(self._history) - 1 <= MAX_HISTORY:
            return

        cuerpo = self._history[1:]
        corte = len(cuerpo) - MAX_HISTORY
        while corte < len(cuerpo) and cuerpo[corte].get("role") != "user":
            corte += 1

        if corte >= len(cuerpo):
            # No hay ningun punto limpio (una racha larguisima de tools sin que
            # el usuario diga nada): mejor quedarse solo con el system prompt que
            # mandar una conversacion que el servidor va a rechazar entera.
            self._history = self._history[:1]
            return

        self._history = self._history[:1] + cuerpo[corte:]

    async def chat(
        self,
        text: str,
        on_tool_call: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Una vuelta de conversacion. Emite eventos para el movil.

        Eventos: {"kind": "text"|"tool"|"tool_progress"|"tool_result"|"missing_tool"|"save_tool"|"error", ...}

        `on_tool_call` es el gancho de confirmacion: devuelve un protocol.Reply.
        Aqui es donde se engancha el Permitir/Denegar/Guardar del movil.
        """
        cfg = self._cfg
        url = cfg.get("url", "http://127.0.0.1:11434")
        model = cfg.get("model", "qwen3:8b")

        if not self._history:
            self._history.append({"role": "system", "content": SYSTEM_PROMPT + _hechos_pc()})
        self._history.append({"role": "user", "content": text})
        self._trim()

        for ronda in range(MAX_ROUNDS):
            payload = {
                "model": model,
                "messages": self._history,
                "tools": self.registry.schemas(),
                "stream": False,
                "keep_alive": cfg.get("keep_alive", "5m"),
                # Qwen3 razona en voz alta por defecto. Para mapear intencion a
                # tool es latencia pura: el modelo no necesita pensar para saber
                # que "abre Unity" es open_app(unity_hub).
                "think": False,
                # Explicitos y no por defecto: ver DEFAULT_NUM_CTX (Ollama coge
                # 4096 y va tirando el system prompt sin decir nada) y
                # DEFAULT_TEMPERATURE (0.8 hace que dude de que tool usar).
                "options": {
                    "num_ctx": int(cfg.get("num_ctx", DEFAULT_NUM_CTX)),
                    "temperature": float(cfg.get("temperature", DEFAULT_TEMPERATURE)),
                },
            }

            try:
                data = await asyncio.to_thread(_post, f"{url}/api/chat", payload)
            except OllamaDown as e:
                yield {"kind": "error", "text": str(e)}
                return

            msg = data.get("message") or {}
            content = (msg.get("content") or "").strip()
            calls = msg.get("tool_calls") or []

            if content:
                yield {"kind": "text", "text": content}
                # El prompt le pide esta frase exacta cuando le falta una tool.
                # Es la senal que abre el bucle de auto-ampliacion (seccion 8).
                if "accion no disponible" in content.lower():
                    yield {"kind": "missing_tool", "text": content}

            if not calls:
                self._history.append({"role": "assistant", "content": content})
                return

            self._history.append(msg)

            for call in calls:
                fn = call.get("function") or {}
                name = fn.get("name", "")
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}

                tool = self.registry.get(name)
                if tool is None:
                    resultado = f"No existe la tool '{name}'."
                    yield {"kind": "missing_tool", "text": f"El modelo pidio '{name}', que no existe."}
                else:
                    yield {"kind": "tool", "name": name, "args": args, "confirm": tool.confirm}

                    reply = Reply(action="allow")
                    if tool.confirm and on_tool_call is not None:
                        reply = await on_tool_call(name, args)

                    if not reply.allowed:
                        resultado = "El usuario NO aprobo esta accion. No insistas."
                    else:
                        resultado = None
                        async for tipo, valor in toolrun.run_with_progress(self.registry, name, args):
                            if tipo == "progress":
                                yield {"kind": "tool_progress", "name": name, "text": valor}
                            elif tipo == "artifact":
                                yield {
                                    "kind": "artifact",
                                    "artifact_id": valor.artifact_id,
                                    "name": valor.name,
                                    "size": valor.size,
                                }
                            else:
                                resultado = valor
                        assert resultado is not None

                    yield {"kind": "tool_result", "name": name, "text": resultado}

                    # "Guardar" = permitir Y congelar el comando como tool. Lo
                    # hace el servidor (tiene el registry y el socket); aqui solo
                    # se emite la senal, como con missing_tool.
                    if reply.save:
                        yield {
                            "kind": "save_tool",
                            "nombre": reply.nombre,
                            "args": args,
                            "resultado": resultado,
                        }

                self._history.append({"role": "tool", "content": resultado, "tool_name": name})

        yield {"kind": "error", "text": f"Corto tras {MAX_ROUNDS} rondas de herramientas."}
