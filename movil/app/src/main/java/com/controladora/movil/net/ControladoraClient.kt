package com.controladora.movil.net

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import android.util.Log
import com.controladora.movil.BuildConfig
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.BufferedSink
import org.json.JSONObject
import java.io.IOException
import java.net.ConnectException
import java.net.URLEncoder
import java.net.UnknownHostException
import java.time.LocalTime
import java.time.format.DateTimeFormatter
import java.util.UUID
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLException
import javax.net.ssl.SSLHandshakeException

private const val TAG = "Controladora"
private const val LOG_MAX_LINES = 300

sealed interface Conn {
    data object Offline : Conn
    data object Connecting : Conn
    data object Online : Conn
    data class Failed(val reason: String) : Conn
}

/** Mensajes que llegan del PC. Refleja controladora/protocol.py. */
sealed interface ServerMsg {
    data class Hello(val version: Int, val brains: List<String>, val tools: List<String>) : ServerMsg
    data class Delta(val id: String, val text: String) : ServerMsg
    data class End(val id: String) : ServerMsg
    data class ToolCall(val id: String, val name: String, val args: String, val confirm: Boolean) : ServerMsg
    data class ToolProgress(val id: String, val name: String, val text: String) : ServerMsg
    data class ToolResult(val id: String, val name: String, val text: String) : ServerMsg
    data class MissingTool(val id: String, val text: String) : ServerMsg
    data class PermissionRequest(
        val reqId: String,
        val brain: String,
        val name: String,
        val args: String,
        val motivo: String,
        val savable: Boolean,
        val sugerencia: String,
        /** Ese comando corre como ADMINISTRADOR (ver elevate.py en el PC). */
        val admin: Boolean,
    ) : ServerMsg
    /** Ese permiso ya no cuenta (caduco, o su turno murio): quita la tarjeta. */
    data class PermissionCancel(val reqId: String) : ServerMsg
    /**
     * Claude llamo a AskUserQuestion (protocol.QUESTION_REQUEST, v11): una o varias
     * preguntas de opcion multiple. NO es un permiso Si/No -- se pinta como burbuja
     * con botones y se contesta con la opcion elegida (ver replyQuestion). [reqId]
     * es el mismo mecanismo de caducidad/cancelacion que un permiso.
     */
    data class QuestionRequest(
        val reqId: String,
        val brain: String,
        val questions: List<Pregunta>,
    ) : ServerMsg
    data class ToolSaved(val ok: Boolean, val name: String, val text: String) : ServerMsg
    data class AiState(val text: String) : ServerMsg
    data class Error(val message: String, val id: String? = null) : ServerMsg
    data class ArtifactReady(val id: String, val artifactId: String, val name: String, val size: Long) : ServerMsg
    /**
     * Fase Monitor: medida directa del PC, sin pasar por ningun cerebro. [text] es
     * el parrafo de siempre; [data] son los numeros en crudo para poder dibujarlos
     * (ver protocol.stats_result y sysinfo.snapshot en el PC). Antes solo llegaba
     * el texto ya formateado y el movil lo pintaba tal cual en monoespaciado: no
     * habia con que hacer una barra sin re-parsear a mano lo que el PC acababa de
     * formatear.
     */
    data class StatsResult(val text: String, val data: Stats?) : ServerMsg
    /** Resultado de una accion directa (reboot_pc, build_and_send desde un boton...). */
    data class ActionResult(val name: String, val ok: Boolean, val text: String) : ServerMsg
    /**
     * Los tokens de la CUENTA de Claude, no el gasto del turno (ver protocol.LIMIT
     * en el PC). [status] es "allowed", "allowed_warning" o "rejected", y
     * [resetsAt] es el epoch en segundos al que vuelve a haber tokens.
     */
    data class Limite(
        val status: String,
        val resetsAt: Long?,
        val tipo: String,
        val etiqueta: String,
        val utilizacion: Float?,
    ) : ServerMsg
    /** paths.json leido por el PC. Ver ProjectsPanel: aqui no hay LLM de por medio. */
    data class ProjectsResult(val projects: List<Proyecto>) : ServerMsg
    /** Confirma que [brain] olvido su contexto (ver protocol.SESSION_NEW/v9):
     * el PC ya cerro/reseteo su lado, y el movil puede vaciar esa conversacion. */
    data class SessionNewOk(val brain: String) : ServerMsg

    /**
     * El estado de la app de escritorio de Claude en el PC (protocol.APP_STATE, v12).
     *
     * [titulo] es la sesion que se esta VIENDO en la app, no la que se toco mas
     * recientemente: son cosas distintas y el PC ya se encarga de distinguirlas.
     * [mandos] son los botones pulsables ahora mismo, con el nombre exacto que
     * hay que devolver en `app.press`. Van sin filtrar a proposito: si la app
     * saca una tarjeta de permiso, sus botones aparecen aqui y se pueden tocar
     * sin que ni el PC ni el movil tengan que conocerlos de antemano.
     */
    data class AppState(
        val abierta: Boolean,
        val titulo: String?,
        val modelo: String?,
        val uso: String?,
        val mandos: List<String>,
        /** Las entradas de un menú ABIERTO en la app (selector de modelo, de
         * esfuerzo…). Vacío casi siempre; cuando no, la app está esperando a que
         * elijas y no atiende a nada más, así que van por delante de todo. */
        val opciones: List<String>,
        val sesiones: List<SesionApp>,
        val error: String,
    ) : ServerMsg

    /** La respuesta del PC a nuestra oferta de vídeo (protocol.RTC_ANSWER). */
    data class RtcAnswer(val sdp: String, val tipo: String) : ServerMsg

    /** Los monitores del PC (protocol.SCREENS_RESULT, v16). Ver [Pantalla]. */
    data class ScreensResult(val screens: List<Pantalla>) : ServerMsg

    /**
     * El portapapeles del PC (protocol.CLIP_TEXT, v14). Llega solo cuando el
     * vigilante ve un Ctrl+C en el PC, o como respuesta a un `clip.get`.
     *
     * [cortado] avisa de que el PC no mandó el texto entero (tope de 100 000
     * caracteres, ver MAX_CLIP en server.py). Se dice en la pantalla en vez de
     * dejar que pegues medio texto creyendo que está completo.
     */
    data class ClipText(val text: String, val cortado: Boolean) : ServerMsg
}

/**
 * Un monitor del PC (protocol.SCREENS_RESULT, v16). [id] es el nombre de
 * dispositivo de Windows (p.ej. `\\.\DISPLAY1`), estable: es lo que se manda
 * de vuelta en `rtc.offer` y en cada `screen.*` para decir sobre qué pantalla
 * se gesticula. [x]/[y] pueden ser NEGATIVOS -- un monitor a la izquierda o
 * encima del principal, en coordenadas del escritorio virtual -- y eso no es
 * un error, es justo lo que hace falta para que el PC resuelva el punto bien.
 */
data class Pantalla(
    val id: String,
    val nombre: String,
    val x: Int,
    val y: Int,
    val ancho: Int,
    val alto: Int,
    val principal: Boolean,
)

/**
 * Una conversacion de la app de escritorio (ver ServerMsg.AppState).
 *
 * [trabajando] es `null` cuando el PC no reconoce el estado que pinta la app
 * (ver uia.ESTADOS): significa "no lo se", NO "esta parada". Por eso se guarda
 * ademas [estado], el texto crudo, que siempre se puede enseñar tal cual.
 */
data class SesionApp(
    val titulo: String,
    val trabajando: Boolean?,
    val estado: String,
    val modelo: String,
    val esfuerzo: String,
    val permisos: String,
    val cwd: String,
)

/**
 * Una pregunta de AskUserQuestion (ver ServerMsg.QuestionRequest). [question] es
 * el texto EXACTO, que es la clave con la que se devuelve la respuesta al PC, asi
 * que no se toca. [header] es la etiqueta corta (el chip). [multiSelect] permite
 * elegir varias opciones a la vez.
 */
data class Pregunta(
    val question: String,
    val header: String,
    val multiSelect: Boolean,
    val options: List<Opcion>,
)

/** Una opcion de una [Pregunta]. [label] es el texto EXACTO que se manda de vuelta
 * como respuesta; [description] es la ayuda que se pinta debajo. */
data class Opcion(val label: String, val description: String)

/** Un proyecto de paths.json tal y como lo manda el PC (projects.result). */
data class Proyecto(
    val nombre: String,
    val tipo: String,
    val path: String,
    val descripcion: String,
    val existe: Boolean,
    /** Tarea de Gradle que el PC lanzaria para este proyecto si no se le dice otra
     * cosa: "assembleRelease", "assembleDebug" o "build". La decide el PC mirando
     * el build.gradle (variantes.py), porque el que tiene el disco delante es el.
     * Vacio si el PC es de un protocolo anterior y no manda el campo. */
    val variante: String = "",
    /** Por que esa y no otra. Solo viene cuando hay algo que explicar: tipicamente
     * "este proyecto no puede firmar releases, asi que sale una debug (mas lenta)". */
    val varianteNota: String = "",
) {
    /** Si dandole al boton sale una build de release de verdad (rapida) o no. */
    val esRelease: Boolean get() = variante.endsWith("Release", ignoreCase = true)
}

/** Una medida del PC (stats.result → data). Todo nullable: una GPU que no
 * responde o una temperatura que nadie puede leer son estados normales, no
 * errores, y la pantalla tiene que saber dibujar su ausencia. */
data class Stats(
    val cpuPct: Float,
    val cpuNucleos: Int,
    val porNucleo: List<Float>,
    val cpuFreqMhz: Int?,
    val cpuTempC: Float?,
    val cpuTempNota: String?,
    val ramPct: Float,
    val ramUsadaGb: Float,
    val ramTotalGb: Float,
    val gpu: Gpu?,
    val gpuError: String?,
    val discos: List<Disco>,
    val uptimeS: Long,
)

data class Gpu(
    val nombre: String,
    val tempC: Float?,
    val usoPct: Float?,
    val vramUsadaMb: Float?,
    val vramTotalMb: Float?,
    val potenciaW: Float?,
)

data class Disco(val unidad: String, val pct: Float, val usadoGb: Float, val totalGb: Float)

/** Cómo fue una subida de un archivo al PC. Ver ControladoraClient.uploadFile. */
sealed interface UploadResult {
    /** [ruta] es dónde quedó EN EL PC, tal cual lo dice el propio PC: puede no
     * ser el nombre que mandamos (si ya existía uno igual, el PC añade " (2)"). */
    data class Ok(val ruta: String, val nombre: String, val bytes: Long) : UploadResult
    data class Failed(val reason: String) : UploadResult
}

/** Lo que se sabe de un archivo elegido en el selector, antes de mandarlo. */
data class ArchivoElegido(val uri: Uri, val nombre: String, val bytes: Long)

/** Como fue una descarga de artifact.ready. Ver ControladoraClient.downloadArtifact. */
sealed interface DownloadResult {
    data class Ok(val file: File) : DownloadResult
    data class Failed(val reason: String) : DownloadResult
}

class ControladoraClient(
    private val context: Context,
    private val scope: CoroutineScope,
) {
    private val _state = MutableStateFlow<Conn>(Conn.Offline)
    val state: StateFlow<Conn> = _state.asStateFlow()

    private val _events = MutableSharedFlow<ServerMsg>(extraBufferCapacity = 64)
    val events: SharedFlow<ServerMsg> = _events.asSharedFlow()

    // Log de diagnostico visible en la UI. No es Logcat: el usuario no siempre puede
    // conectar el movil a un PC con adb para leerlo, asi que tiene que quedarse
    // dibujado en pantalla y ser copiable. NUNCA metas el token aqui: este log se
    // piensa para copiar y pegar a quien te ayude a depurar.
    private val _log = MutableStateFlow<List<String>>(emptyList())
    val log: StateFlow<List<String>> = _log.asStateFlow()

    private var socket: WebSocket? = null
    private var reconnectJob: Job? = null
    private var attempt = 0
    private var wanted = false

    /**
     * Numero de la conexion actual. Cada [open] crea un listener nuevo, pero el
     * anterior NO deja de existir por dejar de usarlo: OkHttp le sigue mandando
     * onFailure/onClosed cuando el socket viejo termina de morir. Sin este numero,
     * el estropicio de una conexion ya sustituida ponia Failed encima de una
     * conexion nueva que estaba perfectamente, y su onClosed programaba una
     * reconexion de mas -- dos sockets vivos a la vez. Se llega ahi pulsando
     * Conectar mientras el socket anterior aun se esta muriendo, que es
     * exactamente lo que uno hace cuando ve que algo va mal. Cada listener recuerda
     * su numero y se calla si ya no es el vigente.
     */
    private var gen = 0

    // Se guardan para poder construir la URL de descarga de un artifact.ready
    // (GET /artifact/<id>, ver server.py): es el mismo host:puerto del WS, pero
    // por HTTPS normal en vez de por el socket.
    private var currentHost: String = ""
    private var currentPort: Int = BuildConfig.DEFAULT_PORT

    private val http: OkHttpClient by lazy {
        val (factory, trust) = Tls.build(context)
        OkHttpClient.Builder()
            .sslSocketFactory(factory, trust)
            // Sin timeout de lectura: un WS puede estar callado mucho rato, y un
            // build de Gradle son minutos sin decir nada. Quien detecta que el
            // enlace ha muerto es el ping, no el timeout.
            .readTimeout(0, TimeUnit.MILLISECONDS)
            // Y sin timeout de escritura, por lo mismo pero para el otro sentido:
            // subir un vídeo al PC (POST /upload) por datos móviles se atasca a
            // ratos, y el corte por reloj lo daría por fallido cuando lo único
            // que pasaba es que la red iba lenta. Quien detecta un enlace muerto
            // sigue siendo el ping.
            .writeTimeout(0, TimeUnit.MILLISECONDS)
            .pingInterval(20, TimeUnit.SECONDS)
            .connectTimeout(15, TimeUnit.SECONDS)
            .build()
    }

    fun connect(host: String, port: Int = BuildConfig.DEFAULT_PORT) {
        wanted = true
        attempt = 0
        appendLog("== conectar solicitado: $host:$port ==")
        open(host, port)
    }

    fun clearLog() {
        _log.value = emptyList()
    }

    fun disconnect() {
        wanted = false
        reconnectJob?.cancel()
        appendLog("desconexion manual")
        socket?.close(1000, "bye")
        socket = null
        _state.value = Conn.Offline
    }

    private fun open(host: String, port: Int) {
        currentHost = host
        currentPort = port
        reconnectJob?.cancel()
        _state.value = Conn.Connecting
        // A partir de aqui, todo lo que diga un listener anterior es de una
        // conexion que ya no es la nuestra (ver [gen]).
        val miGen = ++gen
        appendLog("conectando a wss://$host:$port/ws (intento ${attempt + 1})")

        val request = Request.Builder()
            .url("wss://$host:$port/ws")
            .header("Authorization", "Bearer ${BuildConfig.TOKEN}")
            .build()

        socket = http.newWebSocket(request, object : WebSocketListener() {
            /** false = este callback viene de una conexion ya sustituida: ignorar. */
            private fun vigente(): Boolean = miGen == gen

            override fun onOpen(webSocket: WebSocket, response: Response) {
                if (!vigente()) return
                attempt = 0
                _state.value = Conn.Online
                appendLog("conectado: handshake TLS + WS ok (HTTP ${response.code})")
                Log.i(TAG, "conectado a $host:$port")
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                if (!vigente()) return
                parse(text)?.let { msg -> scope.launch { _events.emit(msg) } }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                val summary = summarize(t, response)
                if (!vigente()) {
                    appendLog("(conexion vieja descartada: $summary)")
                    return
                }
                appendLog("FALLO: $summary")
                appendLog("  -> ${hint(t, response)}")
                Log.w(TAG, "caida: $summary", t)
                _state.value = Conn.Failed(summary)
                scheduleReconnect(host, port)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                if (!vigente()) {
                    appendLog("(cierre de una conexion vieja, code=$code)")
                    return
                }
                appendLog("cerrado por el servidor: code=$code reason=${reason.ifBlank { "(vacio)" }}")
                _state.value = Conn.Offline
                if (wanted) scheduleReconnect(host, port)
            }
        })
    }

    /**
     * Backoff exponencial hasta 30 s. Cambiar de WiFi a datos al salir de casa es
     * exactamente esto: una caida y una reconexion, no un error que deba ver el usuario.
     */
    private fun scheduleReconnect(host: String, port: Int) {
        if (!wanted) return
        reconnectJob?.cancel()
        reconnectJob = scope.launch {
            val wait = minOf(30_000L, 1_000L shl minOf(attempt, 5))
            attempt++
            appendLog("reintentando en ${wait}ms")
            delay(wait)
            if (wanted) open(host, port)
        }
    }

    /**
     * Manda un JSON por el socket y dice SI DE VERDAD SALIO.
     *
     * Este `Boolean` es el arreglo del bug mas feo que tenia la app: aqui habia un
     * `socket?.send(...)` suelto, cuyo valor nadie miraba. Sin conexion, `socket`
     * es null y ese `?.` no hace nada -- sin lanzar, sin avisar, sin devolver
     * nada. Osea que escribir con el PC apagado "funcionaba": el mensaje se
     * evaporaba, el ViewModel marcaba el turno como vivo igualmente y el
     * indicador se ponia a contar "pensando... 90s" de una IA que no habia
     * recibido nada. Eso es literalmente la app inventandose que el PC esta
     * trabajando estando desconectada.
     *
     * OkHttp tambien devuelve false si el socket ya esta cerrandose o si la cola
     * de salida esta llena, que son igual de "no ha salido" que no tener socket.
     * Quien llama DEBE mirar esto y contarlo, no seguir como si nada.
     */
    private fun enviar(payload: JSONObject): Boolean {
        val ok = socket?.send(payload.toString()) ?: false
        if (!ok) appendLog("NO ENVIADO (sin conexion): ${payload.optString("type")}")
        return ok
    }

    /**
     * Devuelve el id del mensaje para poder casar los deltas que vuelvan, o
     * **null si no se ha enviado** (ver [enviar]). Un null significa que el PC no
     * se ha enterado de nada: no hay turno, no hay nada que esperar.
     *
     * [mode], [model] y [effort] solo los mira el PC cuando [brain] es "claude"
     * (ver protocol.py, v9): [mode] es "ask"/"auto"/"plan" de siempre; [model] es
     * un alias del SDK ("sonnet", "opus", "haiku") o vacio = el que decida la
     * CLI; [effort] es "low"/"medium"/"high"/"xhigh"/"max" o vacio = el que
     * decida la CLI.
     */
    fun send(
        text: String,
        brain: String,
        mode: String = "ask",
        model: String = "",
        effort: String = "",
        shell: String = "",
        sesion: String = "",
        nueva: Boolean = false,
    ): String? {
        val id = UUID.randomUUID().toString()
        val payload = JSONObject()
            .put("type", "chat")
            .put("id", id)
            .put("brain", brain)
            .put("text", text)
            .put("mode", mode)
            .put("model", model)
            .put("effort", effort)
            // Solo lo mira el PC cuando brain es "terminal" (protocol.py v10):
            // "powershell" o "cmd". Vacio = el PC cae a PowerShell.
            .put("shell", shell)
            // Solo cuando brain es "app" (protocol.py v12): en que conversacion
            // de la app de escritorio hay que escribir. Vacio = en la que este
            // abierta; [nueva] empieza una.
            .put("sesion", sesion)
            .put("nueva", nueva)
        return if (enviar(payload)) id else null
    }

    /** Pide una foto de la app de escritorio (protocol.APP_REQUEST, v12). Sin
     * cerebro y sin tokens: el PC lee su propia ventana. */
    fun requestAppState() = enviar(JSONObject().put("type", "app.request"))

    /** Abre esa conversacion en la app pulsandola de verdad en la barra lateral. */
    fun openAppSession(titulo: String): Boolean {
        appendLog("app: abrir «$titulo»")
        return enviar(JSONObject().put("type", "app.open").put("titulo", titulo))
    }

    fun newAppSession(): Boolean {
        appendLog("app: conversación nueva")
        return enviar(JSONObject().put("type", "app.new"))
    }

    /**
     * Pulsa un boton de la app por su nombre exacto, el que vino en
     * [ServerMsg.AppState.mandos]. Es generico a proposito: con esto se toca el
     * selector de modelo, el de esfuerzo, el modo de permisos y los botones de
     * cualquier tarjeta que la app saque, sin tener que enseñarle cada uno.
     */
    fun pressApp(nombre: String): Boolean {
        appendLog("app: pulsar «$nombre»")
        return enviar(JSONObject().put("type", "app.press").put("nombre", nombre))
    }

    /** Corta el turno en curso de la app (equivale a Escape en su ventana). */
    fun stopApp(): Boolean {
        appendLog("app: parar turno")
        return enviar(JSONObject().put("type", "app.stop"))
    }

    /** Pide la lista de monitores del PC (protocol.SCREENS_REQUEST, v16). Una
     * vez, no en bucle: la geometría de un monitor no cambia sola como la de
     * una ventana. */
    fun requestScreens(): Boolean = enviar(JSONObject().put("type", "screens.request"))

    // -- el puntero y el teclado sobre el vídeo de pantalla completa (v16) ----
    //
    // Hasta v15 esto era `app.tap`/`app.drag`/`app.scroll`/`app.copy`, atados a
    // la ventana de Claude. Desde v16 es pantalla completa: cada mensaje lleva
    // [monitor] (el `id` de la [Pantalla] que se está viendo) y las coordenadas
    // siguen viajando como FRACCIONES (0 a 1) de ESE monitor, no en píxeles.
    // El porqué es el mismo que antes: `screens.result` es una foto que se
    // pide una vez, y el PC resuelve la fracción contra el rectángulo real del
    // monitor en el instante del gesto (pantallas.punto en el PC).
    //
    // Ninguno espera respuesta: lo que confirma que han surtido efecto es el
    // vídeo, que ya se está mirando.

    fun tapScreen(monitor: String, fx: Float, fy: Float): Boolean {
        appendLog("pantalla: toque en ${redondo(fx)}, ${redondo(fy)}")
        return enviar(
            JSONObject()
                .put("type", "screen.tap")
                .put("monitor", monitor)
                .put("fx", fx.toDouble())
                .put("fy", fy.toDouble()),
        )
    }

    fun dragScreen(monitor: String, fx: Float, fy: Float, fx2: Float, fy2: Float): Boolean {
        appendLog("pantalla: arrastre ${redondo(fx)},${redondo(fy)} -> ${redondo(fx2)},${redondo(fy2)}")
        return enviar(
            JSONObject()
                .put("type", "screen.drag")
                .put("monitor", monitor)
                .put("fx", fx.toDouble())
                .put("fy", fy.toDouble())
                .put("fx2", fx2.toDouble())
                .put("fy2", fy2.toDouble()),
        )
    }

    /**
     * [muescas] con signo: positivo = hacia el principio del documento.
     *
     * Éste NO escribe en el log a propósito, al revés que los otros dos: un solo
     * barrido del dedo son varias muescas, y a 300 líneas de tope se llevaría por
     * delante todo lo que hubiera pasado antes — justo lo que uno va a mirar
     * cuando algo falle.
     */
    fun scrollScreen(monitor: String, fx: Float, fy: Float, muescas: Int): Boolean =
        enviar(
            JSONObject()
                .put("type", "screen.scroll")
                .put("monitor", monitor)
                .put("fx", fx.toDouble())
                .put("fy", fy.toDouble())
                .put("muescas", muescas),
        )

    /** "Copiar selección" sobre el vídeo (v16): Ctrl+C global. El texto copiado
     * vuelve solo, como un `clip.text` más (ver Session.screen_copy en el PC). */
    fun copyScreen(monitor: String): Boolean =
        enviar(JSONObject().put("type", "screen.copy").put("monitor", monitor))

    /** Teclado libre (v16): teclea [texto] donde esté el foco ahora mismo en el PC. */
    fun typeScreen(monitor: String, texto: String): Boolean =
        enviar(JSONObject().put("type", "screen.type").put("monitor", monitor).put("text", texto))

    /** Una tecla especial del teclado libre (Intro, Retroceso...). Ver
     * appctl.pantalla_input.TECLAS en el PC para los nombres reconocidos. */
    fun keyScreen(monitor: String, tecla: String): Boolean =
        enviar(JSONObject().put("type", "screen.key").put("monitor", monitor).put("tecla", tecla))

    /** Una fracción con tres decimales. Sólo para el log: en el socket va entera. */
    private fun redondo(f: Float): String = String.format(java.util.Locale.US, "%.3f", f)

    /**
     * Ofrece una conexión de vídeo para ver [monitor] a pantalla completa
     * (protocol.RTC_OFFER). El [sdp] ya lleva los candidatos ICE dentro: no hay
     * trickle (ver VideoCliente).
     */
    fun enviarOfertaVideo(sdp: String, monitor: String): Boolean {
        appendLog("vídeo: oferta enviada (${sdp.length} bytes de SDP) para $monitor")
        return enviar(
            JSONObject()
                .put("type", "rtc.offer")
                .put("sdp", sdp)
                .put("tipo", "offer")
                .put("monitor", monitor),
        )
    }

    fun pararVideo(): Boolean = enviar(JSONObject().put("type", "rtc.stop"))

    /** Pide olvidar el contexto de [brain] (ver protocol.SESSION_NEW, v9): en el
     * PC cierra el cliente del SDK (Claude) o limpia el historial (local). El
     * movil no borra nada hasta que llegue la confirmacion (session.new_ok). */
    fun newSession(brain: String): Boolean {
        appendLog("nueva sesión pedida: $brain")
        return enviar(JSONObject().put("type", "session.new").put("brain", brain))
    }

    /**
     * Ejecuta una tool directa (reboot_pc, build_and_send, open_app...) sin pasar
     * por ningun cerebro: un boton ya sabe que quiere, no hace falta un LLM que lo
     * adivine ni tokens que pagarle. Devuelve el id del "turno" (el PC devuelve
     * los mismos tool/tool.progress/tool.result/chat.end que en un chat) o null
     * si no se ha enviado.
     *
     * Si la tool pide confirmacion, el PC manda el permission.request de siempre
     * y aparece la tarjeta habitual.
     */
    fun runAction(name: String, args: Map<String, Any> = emptyMap()): String? {
        val id = UUID.randomUUID().toString()
        val jsonArgs = JSONObject()
        args.forEach { (k, v) -> jsonArgs.put(k, v) }
        appendLog("accion solicitada: $name $args")
        val payload = JSONObject()
            .put("type", "action.request")
            .put("id", id)
            .put("name", name)
            .put("args", jsonArgs)
        return if (enviar(payload)) id else null
    }

    /**
     * [action] es "allow", "deny" o "save". [nombre] solo lo lee el PC cuando la
     * accion es "save": es el nombre con el que se congela el comando como tool.
     * Se sigue mandando "allow" para que un PC de protocolo v3 lo entienda.
     */
    fun replyPermission(reqId: String, action: String, nombre: String = "") {
        appendLog("permiso $reqId -> $action${if (nombre.isNotBlank()) " ($nombre)" else ""}")
        enviar(
            JSONObject()
                .put("type", "permission.reply")
                .put("req_id", reqId)
                .put("action", action)
                .put("nombre", nombre)
                .put("allow", action != "deny"),
        )
    }

    /**
     * Contesta un AskUserQuestion (ver ServerMsg.QuestionRequest). [answers] es
     * {texto_de_la_pregunta: etiqueta_elegida}: el PC lo mete en el updated_input
     * de la tool para que el CLI la resuelva con lo que tocaste. Va como un
     * permission.reply "allow" con el campo answers, asi reutiliza toda la
     * maquinaria de permisos del PC (misma future, misma caducidad). Un PC viejo
     * que no entienda answers al menos lee el "allow" y no se cuelga.
     */
    fun replyQuestion(reqId: String, answers: Map<String, String>) {
        appendLog("respuesta a pregunta $reqId -> ${answers.values.joinToString(", ")}")
        val jsonAnswers = JSONObject()
        answers.forEach { (k, v) -> jsonAnswers.put(k, v) }
        enviar(
            JSONObject()
                .put("type", "permission.reply")
                .put("req_id", reqId)
                .put("action", "allow")
                .put("allow", true)
                .put("answers", jsonAnswers),
        )
    }

    fun requestAiStatus() = enviar(JSONObject().put("type", "ai.status"))

    fun sleepAi(): Boolean {
        appendLog("durmiendo la IA local")
        return enviar(JSONObject().put("type", "ai.sleep"))
    }

    fun reloadTools(): Boolean {
        appendLog("recargando registry de tools")
        return enviar(JSONObject().put("type", "tools.reload"))
    }

    /** Pide una medida del PC: sin cerebro, sin tokens. Para el refresco del Monitor. */
    // --- portapapeles compartido (v14) -----------------------------------

    /**
     * Enciende o apaga el vigilante del portapapeles DEL PC (protocol.CLIP_WATCH).
     *
     * Se manda al conectar y cada vez que se toca el interruptor. Apagado, el PC
     * ni siquiera mira su portapapeles: no es "que no me lo mande", es "que no lo
     * mire". Importa porque leer el portapapeles ajeno es de esas cosas que uno
     * quiere poder apagar de verdad.
     */
    fun watchClip(encendido: Boolean): Boolean =
        enviar(JSONObject().put("type", "clip.watch").put("on", encendido))

    /** Pide lo que haya copiado AHORA en el PC. El PC contesta siempre, aunque
     * no haya texto (una imagen copiada no es texto): ver Session.clip_get. */
    fun getClip(): Boolean = enviar(JSONObject().put("type", "clip.get"))

    /** Copia [texto] en el portapapeles del PC, para pegarlo allí con Ctrl+V. */
    fun setClip(texto: String): Boolean =
        enviar(JSONObject().put("type", "clip.set").put("text", texto))

    fun requestStats() = enviar(JSONObject().put("type", "stats.request"))

    /** Pide la lista de proyectos de paths.json, que la lee el PC de su propio disco. */
    fun requestProjects() = enviar(JSONObject().put("type", "projects.request"))

    private fun strings(o: JSONObject, key: String): List<String> =
        o.optJSONArray(key)?.let { arr -> List(arr.length()) { arr.getString(it) } }.orEmpty()

    /**
     * `optString` de org.json NO distingue "falta la clave" de "vale JSON null":
     * en ambos casos, y tambien cuando el valor SI es null, devuelve el string
     * literal "null" en vez de Kotlin null. Sin este helper, un `titulo: null`
     * que manda el PC (app cerrada, sesion sin nombre...) se pintaba en el movil
     * como el texto "null" de verdad.
     */
    private fun JSONObject.optStringOrNull(key: String): String? =
        if (isNull(key)) null else optString(key).ifBlank { null }

    private fun parse(raw: String): ServerMsg? = try {
        val o = JSONObject(raw)
        when (o.getString("type")) {
            "hello" -> ServerMsg.Hello(o.optInt("version"), strings(o, "brains"), strings(o, "tools"))
            "chat.delta" -> ServerMsg.Delta(o.getString("id"), o.getString("text"))
            "chat.end" -> ServerMsg.End(o.getString("id"))
            "tool" -> ServerMsg.ToolCall(
                o.getString("id"),
                o.getString("name"),
                o.optJSONObject("args")?.toString() ?: "{}",
                o.optBoolean("confirm"),
            )
            "tool.progress" -> ServerMsg.ToolProgress(o.getString("id"), o.getString("name"), o.optString("text"))
            "tool.result" -> ServerMsg.ToolResult(o.getString("id"), o.getString("name"), o.optString("text"))
            "missing_tool" -> ServerMsg.MissingTool(o.getString("id"), o.optString("text"))
            "permission.request" -> ServerMsg.PermissionRequest(
                o.getString("req_id"),
                // Un PC de protocolo v5 no manda brain. "local" es la apuesta
                // segura: es el cerebro que ya pedia permisos antes de la v6.
                o.optString("brain").ifBlank { "local" },
                o.getString("name"),
                o.optJSONObject("args")?.toString() ?: "{}",
                o.optString("motivo"),
                o.optBoolean("savable"),
                o.optString("sugerencia"),
                // Ausente = false: un PC que no manda el campo es de antes de que
                // existiera el admin, asi que no puede estar pidiendo uno.
                o.optBoolean("admin"),
            )
            "permission.cancel" -> ServerMsg.PermissionCancel(o.getString("req_id"))
            "question.request" -> ServerMsg.QuestionRequest(
                o.getString("req_id"),
                o.optString("brain").ifBlank { "claude" },
                parseQuestions(o.optJSONArray("questions")),
            )
            "tool.saved" -> ServerMsg.ToolSaved(o.optBoolean("ok"), o.optString("name"), o.optString("text"))
            "ai.state" -> ServerMsg.AiState(o.optString("text"))
            "error" -> ServerMsg.Error(o.optString("message"), o.optString("id").ifBlank { null })
            "artifact.ready" -> ServerMsg.ArtifactReady(
                o.getString("id"),
                o.getString("artifact_id"),
                o.optString("name"),
                o.optLong("size"),
            )
            "stats.result" -> ServerMsg.StatsResult(o.optString("text"), parseStats(o.optJSONObject("data")))
            "action.result" -> ServerMsg.ActionResult(o.optString("name"), o.optBoolean("ok"), o.optString("text"))
            "limit" -> ServerMsg.Limite(
                o.optString("status").ifBlank { "allowed" },
                if (o.isNull("resets_at")) null else o.optLong("resets_at"),
                o.optString("tipo"),
                // Un PC viejo no manda etiqueta; el tipo crudo es feo pero cierto.
                o.optString("etiqueta").ifBlank { o.optString("tipo") },
                if (o.isNull("utilizacion")) null else o.optDouble("utilizacion").toFloat(),
            )
            "projects.result" -> ServerMsg.ProjectsResult(parseProjects(o.optJSONArray("projects")))
            "session.new_ok" -> ServerMsg.SessionNewOk(o.optString("brain"))
            "app.state" -> ServerMsg.AppState(
                abierta = o.optBoolean("abierta"),
                titulo = o.optStringOrNull("titulo"),
                modelo = o.optStringOrNull("modelo"),
                uso = o.optStringOrNull("uso"),
                mandos = strings(o, "mandos"),
                opciones = strings(o, "opciones"),
                sesiones = parseSesionesApp(o.optJSONArray("sesiones")),
                error = o.optString("error"),
            )
            "rtc.answer" -> ServerMsg.RtcAnswer(o.optString("sdp"), o.optString("tipo").ifBlank { "answer" })
            "screens.result" -> ServerMsg.ScreensResult(parsePantallas(o.optJSONArray("screens")))
            "clip.text" -> ServerMsg.ClipText(o.optString("text"), o.optBoolean("cortado"))
            else -> null
        }
    } catch (e: Exception) {
        Log.w(TAG, "mensaje ilegible: $raw", e)
        null
    }

    private fun parseQuestions(arr: org.json.JSONArray?): List<Pregunta> {
        if (arr == null) return emptyList()
        return List(arr.length()) { i ->
            val q = arr.getJSONObject(i)
            val opts = q.optJSONArray("options")
            Pregunta(
                question = q.optString("question"),
                header = q.optString("header"),
                multiSelect = q.optBoolean("multiSelect"),
                options = List(opts?.length() ?: 0) { j ->
                    val op = opts!!.getJSONObject(j)
                    Opcion(op.optString("label"), op.optString("description"))
                },
            )
        }
    }

    private fun parseSesionesApp(arr: org.json.JSONArray?): List<SesionApp> {
        if (arr == null) return emptyList()
        return List(arr.length()) { i ->
            val o = arr.getJSONObject(i)
            SesionApp(
                titulo = o.optString("titulo"),
                // `null` cuando el PC no reconoce el estado que pinta la app.
                // optBoolean lo convertiria en false, o sea "parada", que es
                // justo la mentira que este campo existe para evitar.
                trabajando = if (o.isNull("trabajando")) null else o.optBoolean("trabajando"),
                estado = o.optString("estado"),
                modelo = o.optString("modelo"),
                esfuerzo = o.optString("esfuerzo"),
                permisos = o.optString("permisos"),
                cwd = o.optString("cwd"),
            )
        }
    }

    private fun parsePantallas(arr: org.json.JSONArray?): List<Pantalla> {
        if (arr == null) return emptyList()
        return List(arr.length()) { i ->
            val o = arr.getJSONObject(i)
            Pantalla(
                id = o.optString("id"),
                nombre = o.optString("nombre").ifBlank { o.optString("id") },
                x = o.optInt("x"),
                y = o.optInt("y"),
                ancho = o.optInt("ancho"),
                alto = o.optInt("alto"),
                principal = o.optBoolean("principal"),
            )
        }
    }

    private fun parseProjects(arr: org.json.JSONArray?): List<Proyecto> {
        if (arr == null) return emptyList()
        return List(arr.length()) { i ->
            val o = arr.getJSONObject(i)
            Proyecto(
                nombre = o.optString("nombre"),
                tipo = o.optString("tipo"),
                path = o.optString("path"),
                descripcion = o.optString("descripcion"),
                existe = o.optBoolean("existe", true),
                variante = o.optString("variante"),
                varianteNota = o.optString("variante_nota"),
            )
        }
    }

    /** `null` si el PC no mando `data` (un servidor de protocolo v6 o anterior):
     * la pantalla se queda con el texto, que es lo unico que hay. */
    private fun parseStats(o: JSONObject?): Stats? {
        if (o == null || !o.has("cpu")) return null
        return try {
            val cpu = o.getJSONObject("cpu")
            val ram = o.getJSONObject("ram")
            val gpu = o.optJSONObject("gpu")
            val nucleos = cpu.optJSONArray("por_nucleo")
            val discos = o.optJSONArray("discos")

            Stats(
                cpuPct = cpu.optDouble("pct", 0.0).toFloat(),
                cpuNucleos = cpu.optInt("nucleos"),
                porNucleo = List(nucleos?.length() ?: 0) { nucleos!!.getDouble(it).toFloat() },
                cpuFreqMhz = if (cpu.isNull("freq_mhz")) null else cpu.optInt("freq_mhz"),
                cpuTempC = if (cpu.isNull("temp_c")) null else cpu.optDouble("temp_c").toFloat(),
                cpuTempNota = if (cpu.isNull("temp_nota")) null else cpu.optString("temp_nota"),
                ramPct = ram.optDouble("pct", 0.0).toFloat(),
                ramUsadaGb = ram.optDouble("usada_gb", 0.0).toFloat(),
                ramTotalGb = ram.optDouble("total_gb", 0.0).toFloat(),
                gpuError = gpu?.optString("error")?.ifBlank { null },
                gpu = if (gpu == null || gpu.has("error")) {
                    null
                } else {
                    Gpu(
                        nombre = gpu.optString("nombre"),
                        tempC = num(gpu, "temp_c"),
                        usoPct = num(gpu, "uso_pct"),
                        vramUsadaMb = num(gpu, "vram_usada_mb"),
                        vramTotalMb = num(gpu, "vram_total_mb"),
                        potenciaW = num(gpu, "potencia_w"),
                    )
                },
                discos = List(discos?.length() ?: 0) { i ->
                    val d = discos!!.getJSONObject(i)
                    Disco(
                        unidad = d.optString("unidad"),
                        pct = d.optDouble("pct", 0.0).toFloat(),
                        usadoGb = d.optDouble("usado_gb", 0.0).toFloat(),
                        totalGb = d.optDouble("total_gb", 0.0).toFloat(),
                    )
                },
                uptimeS = o.optLong("uptime_s"),
            )
        } catch (e: Exception) {
            // Datos raros no deben tumbar el Monitor: se cae al texto y ya.
            Log.w(TAG, "stats.data ilegible", e)
            null
        }
    }

    private fun num(o: JSONObject, key: String): Float? =
        if (o.isNull(key)) null else o.optDouble(key).toFloat()

    /**
     * Baja el APK de un artifact.ready a cacheDir/apks/. Es un GET normal (no el WS):
     * un APK son varios MB y el chat ya usa el socket para el streaming de texto.
     * Reusa el mismo mTLS + token que el WS (Tls.build), asi que la conexion esta
     * igual de protegida (ARQUITECTURA.md seccion 9) sin abrir nada nuevo.
     */
    suspend fun downloadArtifact(
        artifactId: String,
        name: String,
        onProgress: (Float?) -> Unit = {},
    ): DownloadResult = withContext(Dispatchers.IO) {
        if (currentHost.isBlank()) return@withContext DownloadResult.Failed("no hay conexion con el PC")

        val request = Request.Builder()
            .url("https://$currentHost:$currentPort/artifact/$artifactId")
            .header("Authorization", "Bearer ${BuildConfig.TOKEN}")
            .build()

        try {
            http.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    return@withContext DownloadResult.Failed("HTTP ${response.code}: ${response.message}")
                }
                val body = response.body ?: return@withContext DownloadResult.Failed("respuesta sin contenido")
                val total = body.contentLength() // -1 si el servidor no lo manda

                val dir = File(context.cacheDir, "apks").apply { mkdirs() }
                val destino = File(dir, name)
                // Copia manual por bloques en vez de copyTo: es lo unico que permite
                // saber cuanto llevamos y avisar a la UI (antes no habia forma de
                // distinguir "va lenta" de "se ha colgado" en una build grande).
                body.byteStream().use { input ->
                    destino.outputStream().use { out ->
                        val buffer = ByteArray(8 * 1024)
                        var leidos = 0L
                        var ultimoAviso = 0L
                        while (true) {
                            val n = input.read(buffer)
                            if (n < 0) break
                            out.write(buffer, 0, n)
                            leidos += n
                            // Como mucho cada 64KB: no saturar la UI de actualizaciones.
                            if (leidos - ultimoAviso >= 64 * 1024 || (total in 1..leidos)) {
                                onProgress(if (total > 0) (leidos.toFloat() / total).coerceIn(0f, 1f) else null)
                                ultimoAviso = leidos
                            }
                        }
                    }
                }
                onProgress(1f)
                appendLog("APK bajado: ${destino.name} (${destino.length()} bytes)")
                DownloadResult.Ok(destino)
            }
        } catch (e: Exception) {
            Log.w(TAG, "fallo al bajar artifact $artifactId", e)
            DownloadResult.Failed("${e.javaClass.simpleName}: ${e.message}")
        }
    }

    /**
     * Lo que hace falta saber de un archivo elegido en el selector: cómo se llama
     * y cuánto ocupa.
     *
     * Se pregunta al proveedor del `content://` en vez de mirar la ruta porque
     * un Uri del selector NO tiene ruta de fichero: puede venir de Google Fotos,
     * de Drive o de una app que lo genera al vuelo. DISPLAY_NAME es lo único que
     * se parece a un nombre, y puede no estar (ahí se inventa uno con la hora,
     * que es mejor que llamarlos a todos "archivo").
     */
    suspend fun datosDe(uri: Uri): ArchivoElegido = withContext(Dispatchers.IO) {
        var nombre: String? = null
        var bytes = -1L
        try {
            context.contentResolver.query(uri, null, null, null, null)?.use { c ->
                if (c.moveToFirst()) {
                    val iNombre = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if (iNombre >= 0 && !c.isNull(iNombre)) nombre = c.getString(iNombre)
                    val iTam = c.getColumnIndex(OpenableColumns.SIZE)
                    if (iTam >= 0 && !c.isNull(iTam)) bytes = c.getLong(iTam)
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "no se pudo consultar $uri", e)
        }
        ArchivoElegido(uri, nombre ?: "archivo-${System.currentTimeMillis()}", bytes)
    }

    /**
     * Sube un archivo al PC (POST /upload, ver server.py). Va por HTTPS y no por
     * el WebSocket por lo mismo que el APK baja por un GET: una foto son varios
     * MB y el socket lleva el chat en streaming y el señalizado del vídeo.
     *
     * El nombre viaja percent-encoded en una cabecera porque una cabecera HTTP
     * es latin-1 y los nombres traen tildes, espacios y hasta emojis. El cuerpo
     * son los bytes pelados, sin multipart: siempre va un archivo por petición,
     * así que el sobre no aportaría nada.
     *
     * Sin timeout de escritura (el del cliente compartido ya es 0 para lectura):
     * subir 200 MB por Tailscale desde datos móviles tarda lo que tarda, y
     * cortarlo a mitad por reloj sería peor que esperar.
     */
    suspend fun uploadFile(
        archivo: ArchivoElegido,
        onProgress: (Float?) -> Unit = {},
    ): UploadResult = withContext(Dispatchers.IO) {
        if (currentHost.isBlank()) return@withContext UploadResult.Failed("no hay conexión con el PC")

        val cuerpo = CuerpoDeUri(context, archivo, onProgress)
        val request = Request.Builder()
            .url("https://$currentHost:$currentPort/upload")
            .header("Authorization", "Bearer ${BuildConfig.TOKEN}")
            .header("X-Nombre", URLEncoder.encode(archivo.nombre, "UTF-8"))
            // El PC compara esto con lo que ha escrito de verdad y tira el
            // archivo si no cuadra: una subida cortada no debe quedarse en la
            // carpeta con su nombre bueno, pareciendo entera.
            .header("X-Bytes", archivo.bytes.toString())
            .post(cuerpo)
            .build()

        try {
            http.newCall(request).execute().use { response ->
                val texto = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    val detalle = try {
                        JSONObject(texto).optString("detail").ifBlank { response.message }
                    } catch (_: Exception) {
                        response.message
                    }
                    appendLog("subida rechazada (${archivo.nombre}): HTTP ${response.code} $detalle")
                    return@withContext UploadResult.Failed("HTTP ${response.code}: $detalle")
                }
                onProgress(1f)
                val o = JSONObject(texto)
                appendLog("subido al PC: ${o.optString("nombre")} (${o.optLong("bytes")} bytes)")
                UploadResult.Ok(o.optString("ruta"), o.optString("nombre"), o.optLong("bytes"))
            }
        } catch (e: Exception) {
            Log.w(TAG, "fallo al subir ${archivo.nombre}", e)
            appendLog("fallo al subir ${archivo.nombre}: ${summarize(e, null)}")
            UploadResult.Failed(summarize(e, null))
        }
    }

    /**
     * El cuerpo de la subida, leído del `content://` a chorro y no cargado en
     * memoria: el móvil no puede permitirse meter un vídeo de 700 MB en un
     * ByteArray, y hacerlo es la forma clásica de que la app muera con un
     * OutOfMemory justo con el archivo que más importaba.
     *
     * `contentLength` devuelve -1 a propósito (OkHttp usa entonces
     * Transfer-Encoding: chunked). El tamaño que da el proveedor del Uri es
     * orientativo, y si dijera uno y llegaran otros bytes, OkHttp reventaría la
     * petición por incoherente. Lo que sí es exacto va aparte, en X-Bytes, y lo
     * comprueba el PC.
     */
    private class CuerpoDeUri(
        private val context: Context,
        private val archivo: ArchivoElegido,
        private val onProgress: (Float?) -> Unit,
    ) : RequestBody() {
        override fun contentType() = "application/octet-stream".toMediaTypeOrNull()

        override fun contentLength(): Long = -1

        override fun writeTo(sink: BufferedSink) {
            val entrada = context.contentResolver.openInputStream(archivo.uri)
                ?: throw IOException("el archivo elegido ya no se puede leer")
            entrada.use { input ->
                val buffer = ByteArray(64 * 1024)
                var enviados = 0L
                var ultimoAviso = 0L
                while (true) {
                    val n = input.read(buffer)
                    if (n < 0) break
                    sink.write(buffer, 0, n)
                    enviados += n
                    // Como mucho cada 256 KB: avisar por cada bloque saturaría
                    // la UI de recomposiciones sin que se note la diferencia.
                    if (enviados - ultimoAviso >= 256 * 1024) {
                        ultimoAviso = enviados
                        onProgress(
                            if (archivo.bytes > 0) (enviados.toFloat() / archivo.bytes).coerceIn(0f, 1f) else null,
                        )
                    }
                }
            }
        }
    }

    /** Clase de excepcion + mensaje + causa raiz. Esto es lo que de verdad dice OkHttp. */
    private fun summarize(t: Throwable, response: Response?): String {
        response?.code?.let { return "HTTP $it" }
        val root = generateSequence(t) { it.cause }.last()
        val msg = root.message ?: root.javaClass.simpleName
        return "${root.javaClass.simpleName}: $msg"
    }

    /** Traduce la excepcion tecnica a "que suele significar esto" en el sitio. */
    private fun hint(t: Throwable, response: Response?): String = when {
        response != null -> "el servidor respondio pero rechazo la peticion (token o ruta incorrectos)."
        t is UnknownHostException ->
            "no se resuelve ese host. Revisa que la IP/DDNS este bien escrita."
        t is java.net.SocketTimeoutException ->
            "no hay respuesta del PC. Revisa que Tailscale este conectado en los dos lados " +
                "(en el PC: tailscale status debe decir Running), y que el servicio este arrancado."
        t is ConnectException ->
            "conexion rechazada activamente. El puerto esta cerrado o el firewall del PC lo bloquea."
        t is SSLHandshakeException ->
            "el TLS empezo pero fallo el handshake. Puede que el certificado del servidor no " +
                "cubra este host: revisa los SAN en pc/config.json."
        t is SSLException ->
            "fallo de TLS antes de completar el handshake. Revisa que el server este vivo en ese puerto."
        else -> "sin pista automatica para ${t.javaClass.simpleName}; copia el log y revisalo con detalle."
    }

    private val timeFmt = DateTimeFormatter.ofPattern("HH:mm:ss.SSS")

    private fun appendLog(line: String) {
        val stamped = "${LocalTime.now().format(timeFmt)}  $line"
        _log.value = (_log.value + stamped).takeLast(LOG_MAX_LINES)
    }
}
