package com.controladora.movil

import android.app.Application
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.net.Uri
import android.os.IBinder
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.controladora.movil.net.ApkInstaller
import com.controladora.movil.net.Conn
import com.controladora.movil.net.ConnectionService
import com.controladora.movil.net.ControladoraClient
import com.controladora.movil.net.DownloadResult
import com.controladora.movil.net.Pregunta
import com.controladora.movil.net.Proyecto
import com.controladora.movil.net.ServerMsg
import com.controladora.movil.net.Stats
import java.io.File
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

const val BRAIN_LOCAL = "local"
const val BRAIN_CLAUDE = "claude"

/**
 * La ventana Terminal: NO es una IA. El texto que escribes ES el comando y se
 * ejecuta tal cual en el PC, siempre como administrador y sin tarjeta de permiso
 * (lo tecleas tu, teclearlo es la aprobacion). Ver brain_terminal.py en el PC.
 */
const val BRAIN_TERMINAL = "terminal"

/**
 * La ventana App: tampoco es una IA propia. Maneja la APLICACION DE ESCRITORIO
 * de Claude que hay abierta en el PC — escribe en su compositor, pulsa sus
 * botones y lee su conversacion. Lo que escribas aqui aparece tecleado en la
 * ventana del PC, y lo que conteste lo contesta esa app, no un modelo aparte.
 * Ver brain_app.py y ARQUITECTURA.md 5.1.
 */
const val BRAIN_APP = "app"

/** El interprete con el que la Terminal ejecuta el comando. Conmutable en
 * cualquier momento (protocol.CHAT "shell", v10). */
const val SHELL_POWERSHELL = "powershell"
const val SHELL_CMD = "cmd"

/**
 * Los tres modos de permisos de Claude Code, iguales que en la app de escritorio
 * (ver brain_claude.MODE_MAP en el PC). Solo aplican al cerebro "claude": la IA
 * local ya tiene su propio Si/No por tool y no conoce estos modos.
 *
 * - [MODO_ASK]: de siempre, cada tool arriesgada abre la tarjeta de permiso.
 * - [MODO_AUTO]: no pregunta nada (bypassPermissions). Es el "modo automatico"
 *   que evita tener que aprobar cada permiso a mano.
 * - [MODO_PLAN]: Claude solo lee y propone un plan; para ejecutarlo pide salir
 *   del modo plan, y ESO si aparece como tarjeta de permiso.
 */
const val MODO_ASK = "ask"
const val MODO_AUTO = "auto"
const val MODO_PLAN = "plan"

/**
 * Los alias de modelo que entiende el SDK (ver `model` en
 * `claude_agent_sdk.types.ClaudeAgentOptions`, y brain_claude.ClaudeBrain).
 * [MODELO_DEFECTO] (cadena vacia) es "no forzar nada, que decida la CLI".
 * Cambiar de modelo se aplica en caliente sin perder la conversacion.
 */
const val MODELO_DEFECTO = ""
const val MODELO_SONNET = "sonnet"
const val MODELO_OPUS = "opus"
const val MODELO_HAIKU = "haiku"

/**
 * Los niveles de "esfuerzo" que entiende el SDK (`EffortLevel` en
 * `claude_agent_sdk.types`). [ESFUERZO_DEFECTO] es "no forzar nada". A
 * diferencia del modelo, cambiar el esfuerzo SIEMPRE reconecta (el SDK no
 * tiene forma de aplicarlo en caliente) y por tanto pierde la conversacion.
 */
const val ESFUERZO_DEFECTO = ""
const val ESFUERZO_LOW = "low"
const val ESFUERZO_MEDIUM = "medium"
const val ESFUERZO_HIGH = "high"
const val ESFUERZO_XHIGH = "xhigh"
const val ESFUERZO_MAX = "max"

/** Etiqueta legible para el mensaje de sistema al cambiar de modelo. */
fun etiquetaModelo(valor: String): String = when (valor) {
    MODELO_SONNET -> "Sonnet"
    MODELO_OPUS -> "Opus"
    MODELO_HAIKU -> "Haiku"
    else -> "automático"
}

/** Etiqueta legible para el mensaje de sistema al cambiar de esfuerzo. */
fun etiquetaEsfuerzo(valor: String): String = when (valor) {
    ESFUERZO_LOW -> "bajo"
    ESFUERZO_MEDIUM -> "medio"
    ESFUERZO_HIGH -> "alto"
    ESFUERZO_XHIGH -> "extra"
    ESFUERZO_MAX -> "máximo"
    else -> "automático"
}

/**
 * "las 21:04", "mañana a las 03:00" o null si el PC no mando hora.
 *
 * El epoch viene en SEGUNDOS (es lo que manda el CLI de Claude, ver protocol.LIMIT)
 * y se pinta en la zona horaria del movil: la pregunta que se hace uno mirando esto
 * es "¿cuándo puedo seguir?", y la respuesta util es la hora de su reloj.
 */
fun horaDeReset(epochSegundos: Long?): String? {
    if (epochSegundos == null || epochSegundos <= 0) return null
    val zona = ZoneId.systemDefault()
    val cuando = Instant.ofEpochSecond(epochSegundos).atZone(zona)
    val hora = cuando.format(DateTimeFormatter.ofPattern("HH:mm"))
    return when (ChronoUnit.DAYS.between(LocalDate.now(zona), cuando.toLocalDate())) {
        0L -> "las $hora"
        1L -> "mañana a las $hora"
        // Los limites semanales se restablecen dias despues: ahi la hora sola
        // mentiria por omision ("las 09:00" sonando a esta manana).
        else -> cuando.format(DateTimeFormatter.ofPattern("d 'de' MMMM 'a las' HH:mm"))
    }
}

/**
 * Una entrada del chat. `key` es unica; `id` es el id del mensaje del protocolo y
 * lo comparten varias entradas (el texto, las tools que llamo, sus resultados).
 */
sealed interface Item {
    val key: String

    data class Text(
        override val key: String,
        val mine: Boolean,
        val text: String,
        val streaming: Boolean = false,
    ) : Item

    data class ToolCall(
        override val key: String,
        val name: String,
        val args: String,
        val progreso: String = "",
    ) : Item
    data class ToolResult(override val key: String, val name: String, val text: String) : Item
    data class Missing(override val key: String, val text: String) : Item

    /**
     * AskUserQuestion: la burbuja azul con botones (ver QuestionCard en
     * ChatScreen). [reqId] casa la respuesta con la pregunta que espera el PC.
     * [respondido] pasa de null a un resumen de lo elegido en cuanto contestas o
     * la pregunta caduca: eso apaga los botones para que no la contestes dos veces.
     */
    data class Question(
        override val key: String,
        val reqId: String,
        val questions: List<Pregunta>,
        val respondido: String? = null,
    ) : Item
    data class Sys(override val key: String, val text: String) : Item
    data class Artifact(
        override val key: String,
        val artifactId: String,
        val name: String,
        val size: Long,
        val state: ArtifactState = ArtifactState.Ready,
    ) : Item
}

/** Fase 3: en que punto esta un APK que llego por artifact.ready (ver ChatViewModel.installArtifact). */
sealed interface ArtifactState {
    data object Ready : ArtifactState
    /** [pct] en 0f..1f si se conoce el tamano total, o null si aun no hay dato
     * (primer instante de la descarga, antes de leer el primer bloque). */
    data class Downloading(val pct: Float? = null) : ArtifactState
    data class Downloaded(val path: String) : ArtifactState
    data class Failed(val reason: String) : ArtifactState
}

/**
 * En que punto esta el turno de un cerebro.
 *
 * Esto sustituye a la barra indeterminada que habia antes. La barra solo sabia
 * decir "algo esta pasando", que es justo lo que no necesitas saber: cuando un
 * turno tarda dos minutos quieres saber SI esta pensando, compilando o esperando
 * a que le des permiso, porque en un caso esperas y en otro tienes que tocar tu.
 *
 * No hay porcentaje a proposito: ni Claude ni un build de Gradle dicen cuanto les
 * queda, asi que un porcentaje seria inventado. Lo que si es verdad es la fase y
 * el rato que lleva ([desde]), y con eso ya se distingue "va lento" de "esta muerto".
 */
sealed interface Turno {
    /** Momento (SystemClock-ish, via System.currentTimeMillis) en que empezo esta fase. */
    val desde: Long

    data object Parado : Turno {
        override val desde: Long get() = 0L
    }

    data class Pensando(override val desde: Long) : Turno
    data class Escribiendo(override val desde: Long) : Turno
    data class Ejecutando(val tool: String, val linea: String, override val desde: Long) : Turno
    data class EsperandoPermiso(val tool: String, override val desde: Long) : Turno

    /** Claude hizo una pregunta (AskUserQuestion) y espera que toques una opcion.
     * Como EsperandoPermiso, pero contestas eligiendo, no con un Si/No. */
    data class EsperandoRespuesta(override val desde: Long) : Turno
}

/**
 * Un permiso pendiente. Se dibuja como dialogo por encima de todo, centrado: antes
 * se pintaba al final de la lista del chat y, cuando los args eran largos (un Edit
 * de Claude lleva el fichero entero dentro), la tarjeta crecia mas que la pantalla,
 * empujaba fuera los botones y la caja de texto, y la app parecia colgada.
 *
 * [savable] lo decide el PC (hoy: solo run_shell). Cuando es true la tarjeta ofrece
 * un tercer boton que ademas de ejecutar congela el comando como tool permanente,
 * y [sugerencia] es el nombre que propone la IA local, editable antes de guardar.
 *
 * [admin] es el aviso de que ESE comando va a correr con privilegios de
 * administrador (ver elevate.py en el PC). Lo manda el PC como campo propio a
 * proposito: un aviso de este calibre no puede depender de que el movil busque
 * una subcadena dentro del JSON de los args. Cuando es true, [savable] siempre
 * llega false -- un comando admin no se puede congelar como tool.
 */
data class Pending(
    val reqId: String,
    val brain: String,
    val name: String,
    val args: String,
    val motivo: String,
    val savable: Boolean = false,
    val sugerencia: String = "",
    val admin: Boolean = false,
)

/**
 * Un texto que se copió en el PC y llegó aquí (protocol.CLIP_TEXT, v14).
 *
 * [copiado] es si ya se llegó a dejar en el portapapeles DEL TELÉFONO, que no es
 * lo mismo que haberlo recibido: desde Android 10 una app sólo puede escribir en
 * el portapapeles mientras está en primer plano, así que lo que llega con la app
 * guardada en el bolsillo se queda esperando aquí hasta que la abres. Por eso el
 * aviso de la barra de notificaciones y por eso esta bandera: sin ella no habría
 * forma de distinguir "ya lo tienes para pegar" de "lo tengo, pero Android no me
 * deja dártelo todavía".
 *
 * [cortado] lo dice el PC: el texto venía por encima del tope y llega recortado.
 * [cuando] hace de identificador (dos textos idénticos copiados en momentos
 * distintos son dos entradas distintas) y de fecha para la lista.
 */
data class ClipPc(
    val texto: String,
    val cortado: Boolean,
    val cuando: Long,
    val copiado: Boolean = false,
)

/** En qué punto está un archivo que se está mandando al PC. */
sealed interface EnvioEstado {
    data object Esperando : EnvioEstado
    /** [pct] en 0f..1f, o null si el proveedor del archivo no dijo el tamaño y
     * por tanto no hay porcentaje que calcular sin inventárselo. */
    data class Subiendo(val pct: Float? = null) : EnvioEstado
    /** [ruta] es dónde quedó en el PC, dicho por el PC. Puede no ser el nombre
     * que se mandó: si ya había uno igual, el PC añade " (2)" en vez de pisarlo. */
    data class Hecho(val ruta: String) : EnvioEstado
    data class Fallo(val razon: String) : EnvioEstado
}

/** Un archivo elegido en el selector, camino del PC. */
data class Envio(
    val id: String,
    val nombre: String,
    val bytes: Long,
    val estado: EnvioEstado = EnvioEstado.Esperando,
)

/** "2,4 MB", "812 KB", o "" si no se sabe el tamaño. */
fun tamanoLegible(bytes: Long): String = when {
    bytes < 0 -> ""
    bytes < 1024 -> "$bytes B"
    bytes < 1024 * 1024 -> String.format(java.util.Locale.getDefault(), "%.0f KB", bytes / 1024.0)
    bytes < 1024L * 1024 * 1024 -> String.format(java.util.Locale.getDefault(), "%.1f MB", bytes / (1024.0 * 1024))
    else -> String.format(java.util.Locale.getDefault(), "%.2f GB", bytes / (1024.0 * 1024 * 1024))
}

class ChatViewModel(app: Application) : AndroidViewModel(app) {

    /** Solo para el valor inicial de los flows del store, mientras vuelve el bind. */
    private val prefs = app.getSharedPreferences("controladora", Context.MODE_PRIVATE)

    /**
     * Ni el socket ni la conversacion viven aqui: viven en [ConnectionService],
     * que se mantiene en foreground mientras haya conexion deseada para que
     * Android no lo mate al minimizar la app (ver ConnectionService.kt). Este
     * ViewModel se ata (bindService) y no es mas que una fachada: dibuja lo que
     * hay en [ChatStore] y le reenvia lo que tocas. Cuando muere (rotacion,
     * Activity destruida) solo se desata; NUNCA llama a disconnect().
     *
     * Que el historial este en el servicio y no aqui es el arreglo de "no veo lo
     * que Claude hace hasta que le escribo": este objeto muere en cuanto guardas
     * el movil, y lo que llegaba mientras tanto se perdia. El motivo completo,
     * en ChatStore.
     */
    private val _client = MutableStateFlow<ControladoraClient?>(null)
    private val _store = MutableStateFlow<ChatStore?>(null)
    private val _video = MutableStateFlow<com.controladora.movil.net.VideoCliente?>(null)
    private var binder: ConnectionService.LocalBinder? = null

    private val serviceConnection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, service: IBinder?) {
            val local = service as? ConnectionService.LocalBinder ?: return
            binder = local
            _client.value = local.client
            _store.value = local.store
            _video.value = local.video
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            binder = null
            _client.value = null
            _store.value = null
            _video.value = null
        }
    }

    private val _state = MutableStateFlow<Conn>(Conn.Offline)
    val state: StateFlow<Conn> = _state.asStateFlow()

    private val _log = MutableStateFlow<List<String>>(emptyList())
    val log: StateFlow<List<String>> = _log.asStateFlow()

    /** Ejecuta [accion] con el cliente ya disponible: si el bind todavia no ha
     * vuelto (solo puede pasar en el primerisimo instante tras abrir la app)
     * espera a que llegue en vez de perder la orden del usuario en silencio. */
    private fun conClient(accion: (ControladoraClient) -> Unit) {
        _client.value?.let { accion(it); return }
        viewModelScope.launch { accion(_client.filterNotNull().first()) }
    }

    /** Igual que [conClient], pero para lo que toca la conversacion. */
    private fun conStore(accion: (ChatStore) -> Unit) {
        _store.value?.let { accion(it); return }
        viewModelScope.launch { accion(_store.filterNotNull().first()) }
    }

    /** Asoma un flow del store. [inicial] solo se ve en el parpadeo entre que la
     * pantalla se dibuja y el bindService vuelve (un frame o dos), asi que sale
     * de las mismas prefs que usa el store para no pintar un valor que cambie. */
    @OptIn(ExperimentalCoroutinesApi::class)
    private fun <T> delStore(inicial: T, selector: (ChatStore) -> StateFlow<T>): StateFlow<T> =
        _store.filterNotNull().flatMapLatest(selector)
            .stateIn(viewModelScope, SharingStarted.Eagerly, inicial)

    val host: StateFlow<String> =
        delStore(prefs.getString("host", null) ?: BuildConfig.DEFAULT_HOST) { it.host }
    val brain: StateFlow<String> = delStore(prefs.getString("brain", null) ?: BRAIN_LOCAL) { it.brain }
    val modoClaude: StateFlow<String> = delStore(prefs.getString("modo_claude", null) ?: MODO_ASK) { it.modoClaude }
    val modeloClaude: StateFlow<String> =
        delStore(prefs.getString("modelo_claude", null) ?: MODELO_DEFECTO) { it.modeloClaude }
    val esfuerzoClaude: StateFlow<String> =
        delStore(prefs.getString("esfuerzo_claude", null) ?: ESFUERZO_DEFECTO) { it.esfuerzoClaude }
    val shellTerminal: StateFlow<String> =
        delStore(prefs.getString("shell_terminal", null) ?: SHELL_POWERSHELL) { it.shellTerminal }
    val items: StateFlow<List<Item>> = delStore(emptyList()) { it.items }
    val aiState: StateFlow<String> = delStore("") { it.aiState }
    val tools: StateFlow<List<String>> = delStore(emptyList()) { it.tools }
    val stats: StateFlow<Stats?> = delStore(null) { it.stats }
    val statsText: StateFlow<String> = delStore("") { it.statsText }
    val proyectos: StateFlow<List<Proyecto>> = delStore(emptyList()) { it.proyectos }
    val actionStatus: StateFlow<String> = delStore("") { it.actionStatus }
    val pending: StateFlow<Pending?> = delStore(null) { it.pending }

    // --- traspaso: portapapeles y archivos (v14) ----------------------------
    val clips: StateFlow<List<ClipPc>> = delStore(emptyList()) { it.clips }
    val pendienteCopiar: StateFlow<ClipPc?> = delStore(null) { it.pendienteCopiar }
    val vigilarClip: StateFlow<Boolean> = delStore(prefs.getBoolean("vigilar_clip", true)) { it.vigilarClip }
    val avisoTraspaso: StateFlow<String> = delStore("") { it.avisoTraspaso }
    val envios: StateFlow<List<Envio>> = delStore(emptyList()) { it.envios }

    /** El estado de la app de escritorio del PC (pestana App). Ver ChatStore.appState. */
    val appState: StateFlow<com.controladora.movil.net.ServerMsg.AppState?> =
        delStore(null) { it.appState }

    /** La conversacion de la app a la que va lo que escribas; vacio = la abierta. */
    val sesionApp: StateFlow<String> = delStore("") { it.sesionApp }

    /**
     * El vídeo de pantalla completa (v16). Vive en [ConnectionService] (el
     * motor de WebRTC y su contexto de OpenGL son caros de crear y no pueden
     * nacer y morir con cada rotación de pantalla), así que aquí sólo se asoma.
     */
    @OptIn(ExperimentalCoroutinesApi::class)
    val video: StateFlow<com.controladora.movil.net.Video> =
        _video.filterNotNull().flatMapLatest { it.estado }
            .stateIn(viewModelScope, SharingStarted.Eagerly, com.controladora.movil.net.Video.Parado)

    /** El contexto de OpenGL que comparten el decodificador y el renderizador. */
    val eglVideo: org.webrtc.EglBase.Context?
        get() = _video.value?.egl?.eglBaseContext

    /** Los monitores del PC y cuál se está viendo/eligiendo (v16). */
    val pantallas: StateFlow<List<com.controladora.movil.net.Pantalla>> =
        delStore(emptyList()) { it.pantallas }
    val pantallaActual: StateFlow<com.controladora.movil.net.Pantalla?> =
        delStore(null) { it.pantallaActual }

    fun refrescarPantallas() = conStore { it.refrescarPantallas() }

    /** Empieza a ver la [pantallaActual] elegida. Si aún no hay ninguna (la
     * lista no ha llegado todavía) no hace nada -- el botón está deshabilitado
     * en ese caso, ver VideoPanel. */
    fun verVideo() {
        val monitor = _store.value?.pantallaActual?.value?.id ?: return
        _video.value?.empezar(monitor)
            ?: viewModelScope.launch { _video.filterNotNull().first().empezar(monitor) }
    }

    /** Selector de monitor: cambia cuál se ve y, si el vídeo ya estaba en
     * marcha, renegocia con el nuevo -- [VideoCliente.empezar] es idempotente
     * a propósito, así que no hace falta parar antes a mano. */
    fun cambiarPantalla(p: com.controladora.movil.net.Pantalla) {
        conStore { it.elegirPantalla(p) }
        if (video.value !is com.controladora.movil.net.Video.Parado) {
            _video.value?.empezar(p.id)
                ?: viewModelScope.launch { _video.filterNotNull().first().empezar(p.id) }
        }
    }

    fun pararVideo() = _video.value?.parar()

    /** La pregunta de Claude (AskUserQuestion) sin responder, o null. Se pinta como
     * recuadro centrado (QuestionDialog), igual que [pending]. Ver ChatStore.pregunta. */
    val pregunta: StateFlow<Item.Question?> = delStore(null) { it.pregunta }
    val turno: StateFlow<Turno> = delStore(Turno.Parado) { it.turno }
    val limite: StateFlow<ServerMsg.Limite?> = delStore(null) { it.limite }
    val ultimoLimiteConocido: StateFlow<ServerMsg.Limite?> = delStore(null) { it.ultimoLimiteConocido }

    init {
        val ctx = getApplication<Application>()
        ctx.bindService(Intent(ctx, ConnectionService::class.java), serviceConnection, Context.BIND_AUTO_CREATE)

        // state y log son StateFlow del cliente: recuerdan su ultimo valor, asi que
        // un ViewModel nuevo los recupera enteros al re-suscribirse. No hay nada que
        // acumular aqui -- lo que si habia (el historial) se fue a ChatStore.
        viewModelScope.launch {
            val client = _client.filterNotNull().first()
            launch { client.state.collect { _state.value = it } }
            launch { client.log.collect { _log.value = it } }
        }
    }

    fun setHost(value: String) = conStore { it.setHost(value) }

    fun setBrain(value: String) = conStore { it.setBrain(value) }

    fun setModoClaude(value: String) = conStore { it.setModoClaude(value) }
    fun setModeloClaude(value: String) = conStore { it.setModeloClaude(value) }
    fun setEsfuerzoClaude(value: String) = conStore { it.setEsfuerzoClaude(value) }
    fun setShellTerminal(value: String) = conStore { it.setShellTerminal(value) }

    /** Botón "Nueva sesión": olvida el contexto del cerebro que se está mirando. */
    fun nuevaSesion() = conStore { it.nuevaSesion() }

    /** Arranca (o promueve a foreground) ConnectionService: sube la prioridad
     * del proceso ANTES de que el socket termine de abrir, para que Android no
     * lo mate mientras el WS todavia esta a medias. */
    fun connect() {
        ContextCompat.startForegroundService(
            getApplication(),
            Intent(getApplication(), ConnectionService::class.java),
        )
        conStore { store -> conClient { it.connect(store.host.value.trim()) } }
    }

    /** Desconexion PEDIDA por el usuario: unica que quita la notificacion
     * persistente. La app puede seguir en marcha; ConnectionService deja de
     * proteger el proceso hasta el proximo connect(). */
    fun disconnect() {
        conClient { it.disconnect() }
        binder?.dejarDeSerPersistente()
    }

    /**
     * Boton Actualizar. Hace las TRES cosas que hacen falta para volver de segundo
     * plano y estar al dia, no solo bajar el scroll (eso lo hace la pantalla aparte):
     *
     *  1. Si el bind con [ConnectionService] se soltó -- Android puede matar y
     *     recrear el servicio con la app en segundo plano -- este ViewModel se queda
     *     mirando un store que ya no existe y la pantalla congelada. Reengancharse lo
     *     reconecta a la conversacion, que ha seguido acumulandose en el servicio.
     *
     *  2. Si el socket se cayo mientras la app estaba minimizada (o el proceso murio
     *     y volvio SIN conexion, con un cliente recien nacido que no reintenta solo),
     *     fuerza la reconexion YA en vez de esperar al backoff. Reconectar es seguro:
     *     la charla de Claude vive en el PC (claude_brain) y sobrevive a que este
     *     socket muera y nazca otro -- por eso el boton viejo que reconectaba se
     *     quito mal; el problema que tenia (matar la sesion de Claude) ya no existe.
     *     NO se reconecta si ya esta Online: ahi recrear el socket solo cortaria un
     *     turno que va bien.
     *
     * Lo que ni este boton ni ninguno puede hacer es "recuperar" lo que Claude dijo
     * mientras el socket estaba muerto: el PC no guarda transcripcion, esos trozos se
     * enviaron a un socket que ya no escuchaba. Pero tras el arreglo del servidor
     * (drenar el turno en vez de abandonarlo) el PROXIMO mensaje ya va bien: basta
     * reconectar y volver a preguntar.
     */
    fun refrescar() {
        if (_store.value == null) {
            val ctx = getApplication<Application>()
            ctx.bindService(Intent(ctx, ConnectionService::class.java), serviceConnection, Context.BIND_AUTO_CREATE)
        }
        if (_state.value !is Conn.Online) connect()
    }

    fun clearLog() = conClient { it.clearLog() }
    fun sleepAi() = conClient { it.sleepAi() }
    fun refreshAiStatus() = conClient { it.requestAiStatus() }
    fun reloadTools() = conClient { it.reloadTools() }
    fun refreshStats() = conClient { it.requestStats() }
    fun refreshProjects() = conClient { it.requestProjects() }

    /** Los mandos de la pestana App. Ninguno afirma nada: el PC devuelve el
     * estado real de la aplicacion despues de cada uno (ver ChatStore). */
    fun refrescarApp() = conStore { it.refrescarApp() }
    fun abrirSesionApp(titulo: String) = conStore { it.abrirSesionApp(titulo) }
    fun nuevaSesionApp() = conStore { it.nuevaSesionApp() }
    fun pulsarApp(nombre: String) = conStore { it.pulsarApp(nombre) }
    fun pararApp() = conStore { it.pararApp() }

    /** El puntero sobre el vídeo de pantalla completa (v16). Fracciones del
     * monitor, 0 a 1: ver ui.gestosDeVideo y protocol.SCREEN_TAP en el PC. */
    fun tocarApp(monitor: String, fx: Float, fy: Float) = conStore { it.tocarApp(monitor, fx, fy) }
    fun arrastrarApp(monitor: String, fx: Float, fy: Float, fx2: Float, fy2: Float) =
        conStore { it.arrastrarApp(monitor, fx, fy, fx2, fy2) }
    fun desplazarApp(monitor: String, fx: Float, fy: Float, muescas: Int) =
        conStore { it.desplazarApp(monitor, fx, fy, muescas) }

    /** Teclado libre sobre el vídeo (v16). Ver ChatStore.escribirEnPantalla/teclaEnPantalla. */
    fun escribirEnPantalla(texto: String) = conStore { it.escribirEnPantalla(texto) }
    fun teclaEnPantalla(tecla: String) = conStore { it.teclaEnPantalla(tecla) }

    /** Botón "Copiar selección" que aparece sobre el vídeo tras seleccionar
     * texto (mantener + arrastrar). Ver ChatStore.copiarSeleccionApp. */
    fun copiarSeleccionApp() = conStore { it.copiarSeleccionApp() }

    /**
     * Los botones de Monitor y de Acciones rapidas. Van directos a la tool, sin
     * cerebro de por medio: si la tool pide confirmacion (reboot_pc, shutdown_pc),
     * aparece la tarjeta de permiso de siempre.
     *
     * [titulo] es solo para poder decir "no se pidió «Reiniciar PC»" en vez de
     * "no se pidió «reboot_pc»" cuando no hay conexion.
     */
    fun runAction(name: String, args: Map<String, Any> = emptyMap(), titulo: String = name) =
        conStore { it.runAction(name, args, titulo) }

    fun rebootPc() = runAction("reboot_pc", titulo = "Reiniciar PC")
    fun shutdownPc() = runAction("shutdown_pc", titulo = "Apagar PC")
    fun cancelShutdown() = runAction("cancel_shutdown", titulo = "Cancelar apagado")

    /** [action]: "allow" ejecuta una vez, "save" ejecuta y guarda, "deny" no ejecuta nada. */
    fun answerPermission(action: String, nombre: String = "") = conStore { it.answerPermission(action, nombre) }

    /** Contesta un AskUserQuestion: [answers] es {pregunta: etiqueta elegida}. */
    fun answerQuestion(reqId: String, answers: Map<String, String>) =
        conStore { it.answerQuestion(reqId, answers) }

    fun send(text: String) = conStore { it.send(text) }

    // --- traspaso: portapapeles (v14) ---------------------------------------

    fun setVigilarClip(valor: Boolean) = conStore { it.setVigilarClip(valor) }
    fun pedirPortapapeles() = conStore { it.pedirPortapapeles() }
    fun setEnPrimerPlano(valor: Boolean) = conStore { it.setEnPrimerPlano(valor) }

    /**
     * Deja [clip] en el portapapeles del teléfono, listo para pegar donde sea.
     *
     * Esto vive en el ViewModel y no en el store porque necesita Context, sí,
     * pero sobre todo porque **sólo funciona con la app delante**: desde Android
     * 10 el portapapeles es inaccesible para una app sin foco (una medida contra
     * las apps que espiaban lo que copiabas). Llamarlo desde el servicio en
     * segundo plano no da error: no hace nada, que es peor. De ahí que lo llame
     * la pantalla, y sólo cuando está en primer plano.
     */
    fun copiarEnTelefono(clip: ClipPc) {
        val app = getApplication<Application>()
        val portapapeles = app.getSystemService(ClipboardManager::class.java)
        if (portapapeles == null) {
            conStore { it.avisoTraspaso("Este teléfono no deja llegar al portapapeles.") }
            return
        }
        try {
            portapapeles.setPrimaryClip(ClipData.newPlainText("Controladora", clip.texto))
        } catch (e: Exception) {
            conStore { it.avisoTraspaso("No se pudo copiar: ${e.javaClass.simpleName}") }
            return
        }
        conStore {
            it.marcarClipCopiado(clip.cuando)
            // Android 13+ enseña su propio aviso al copiar, así que aquí se dice
            // lo justo para que se sepa que fue esto y no otra cosa.
            it.avisoTraspaso("Copiado en el teléfono: ya puedes pegarlo.")
        }
    }

    /** Copia lo último que llegó del PC si todavía estaba esperando. Lo llama la
     * pantalla al volver a primer plano: es el momento exacto en que Android
     * vuelve a dejarnos tocar el portapapeles. */
    fun copiarPendienteSiHay() {
        pendienteCopiar.value?.let { copiarEnTelefono(it) }
    }

    /**
     * Manda al PC lo que tengas copiado en el teléfono, para pegarlo allí.
     *
     * Leer el portapapeles tiene la misma limitación que escribirlo (primer
     * plano), pero aquí no es problema: esto nace de un botón que se acaba de
     * pulsar, así que la app está delante por definición.
     */
    fun mandarPortapapelesAlPc() {
        val app = getApplication<Application>()
        val portapapeles = app.getSystemService(ClipboardManager::class.java)
        val texto = try {
            portapapeles?.primaryClip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(app)?.toString()
        } catch (e: Exception) {
            null
        }
        conStore { it.mandarAlPc(texto.orEmpty()) }
    }

    // --- traspaso: archivos (v14) -------------------------------------------

    /** Los archivos elegidos en el selector del sistema, camino del PC. */
    fun enviarArchivos(uris: List<Uri>) = conStore { it.enviarArchivos(uris) }

    fun limpiarEnvios() = conStore { it.limpiarEnvios() }

    /** Abre en el PC la carpeta donde aterrizan (tool abrir_recibidos). El
     * resultado sale en [actionStatus], como el resto de acciones directas. */
    fun abrirCarpetaEnPc() = runAction("abrir_recibidos", titulo = "Abrir la carpeta en el PC")

    /**
     * Boton "Instalar" de una tarjeta de artifact.ready. Primera pulsacion: baja
     * el APK y, si ya se puede, abre el instalador del sistema. Si el permiso
     * especial "Instalar apps desconocidas" todavia no esta activo para esta
     * app, lleva a Ajustes en vez de fallar en silencio (ApkInstaller.kt) --
     * hay que volver a tocar Instalar despues de activarlo.
     * Si el APK ya estaba bajado (se toco antes y el usuario cerro el
     * instalador sin confirmar), reabre el instalador sin descargar de nuevo.
     *
     * Se queda en el ViewModel (y no en ChatStore) porque necesita la Activity
     * viva igualmente: nace de una pulsacion y termina abriendo el instalador
     * del sistema. Lo unico que toca del historial lo pide al store.
     */
    fun installArtifact(item: Item.Artifact) {
        val app = getApplication<Application>()
        val yaBajado = item.state
        if (yaBajado is ArtifactState.Downloaded) {
            ApkInstaller.install(app, File(yaBajado.path))
            return
        }

        if (!ApkInstaller.canInstall(app)) {
            conStore {
                it.aviso(brain.value, "Activa «Instalar apps desconocidas» para Controladora y vuelve a tocar Instalar.")
            }
            ApkInstaller.requestInstallPermission(app)
            return
        }

        conStore { it.updateArtifact(item.key, ArtifactState.Downloading()) }
        viewModelScope.launch {
            val cliente = _client.filterNotNull().first()
            val store = _store.filterNotNull().first()
            when (
                val resultado = cliente.downloadArtifact(item.artifactId, item.name) { pct ->
                    store.updateArtifact(item.key, ArtifactState.Downloading(pct))
                }
            ) {
                is DownloadResult.Ok -> {
                    store.updateArtifact(item.key, ArtifactState.Downloaded(resultado.file.path))
                    ApkInstaller.install(app, resultado.file)
                }
                is DownloadResult.Failed -> store.updateArtifact(item.key, ArtifactState.Failed(resultado.reason))
            }
        }
    }

    /**
     * OJO: aqui NO se llama a disconnect(). Antes si, y ese era justo el bug:
     * el ViewModel muere (rotacion de pantalla, Activity destruida al cambiar
     * de app) mucho antes de que el usuario quiera cortar la conexion de
     * verdad, y cerrar el socket aqui era indistinguible de pulsar
     * "Desconectar". Solo nos desatamos del servicio; el socket y la
     * conversacion siguen vivos en ConnectionService hasta que el usuario lo
     * pida o el proceso entero muera.
     */
    override fun onCleared() {
        try {
            getApplication<Application>().unbindService(serviceConnection)
        } catch (_: IllegalArgumentException) {
            // Nunca llego a bindear (p.ej. ViewModel destruido a medio crear): nada que desatar.
        }
        super.onCleared()
    }
}
