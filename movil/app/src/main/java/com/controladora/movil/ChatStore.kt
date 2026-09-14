package com.controladora.movil

import android.content.Context
import android.net.Uri
import com.controladora.movil.net.ArchivoElegido
import com.controladora.movil.net.Conn
import com.controladora.movil.net.ControladoraClient
import com.controladora.movil.net.Pantalla
import com.controladora.movil.net.Proyecto
import com.controladora.movil.net.ServerMsg
import com.controladora.movil.net.Stats
import com.controladora.movil.net.UploadResult
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * La conversacion: los dos chats, los turnos, los permisos y el estado que llega
 * del PC. Vive en [com.controladora.movil.net.ConnectionService], NO en el
 * ViewModel.
 *
 * Por que, con nombre y apellidos -- este es el bug que existia y que costo
 * entender: el socket ya se habia sacado del ViewModel al servicio para que
 * sobreviviera a minimizar la app, pero el historial se quedo en el ViewModel,
 * que muere con la Activity. Y los eventos viajan por un MutableSharedFlow con
 * replay = 0 (ver ControladoraClient.events), que DESCARTA lo que se emite
 * cuando no hay ningun collector. Osea:
 *
 *   guardas el movil -> Android destruye la Activity y el ViewModel -> el
 *   servicio mantiene la conexion viva y el PC sigue mandando lo que Claude
 *   dice -> nadie escucha -> se tira a la basura -> vuelves a abrir y el chat
 *   esta vacio -> escribes "sigues ahi?" -> Claude contesta (sigue vivo y con
 *   todo su contexto, en el PC) -> ahora si hay quien escuche -> lo ves.
 *
 * Ese "hasta que no le escribo no veo lo que hace" no era un socket zombie ni
 * hacia falta ningun boton de Actualizar: los mensajes no se perdian por el
 * camino, se descartaban al llegar. No estaban en ningun sitio del que un boton
 * pudiera recuperarlos.
 *
 * Por eso quien escucha los eventos y acumula el historial es esto, que vive en
 * el scope del servicio: mientras haya conexion hay alguien escuchando, exista
 * la pantalla o no. El ViewModel solo dibuja lo que hay aqui.
 *
 * Limite conocido: esto vive en memoria del proceso. Si Android mata el proceso
 * entero (con el servicio en foreground es raro, para eso esta la notificacion),
 * el historial se va. Sobrevivir a eso pide guardarlo en disco, que es otra cosa.
 */
/** Cuántos textos del PC se guardan. Diez cubre "he copiado varias cosas
 * seguidas y ahora cojo el móvil"; más sería un gestor de portapapeles, que es
 * otro programa. */
private const val MAX_CLIPS = 10

class ChatStore(
    context: Context,
    private val client: ControladoraClient,
    private val scope: CoroutineScope,
) {
    private val prefs = context.getSharedPreferences("controladora", Context.MODE_PRIVATE)

    /**
     * Un historial por cerebro. Antes habia una sola lista y los dos chats escribian
     * en ella, asi que las tools de la IA local y las respuestas de Claude salian
     * mezcladas en la misma conversacion aunque fueran charlas distintas.
     */
    private val _chats = MutableStateFlow(
        mapOf(
            BRAIN_LOCAL to emptyList<Item>(),
            BRAIN_CLAUDE to emptyList(),
            BRAIN_TERMINAL to emptyList(),
            BRAIN_APP to emptyList(),
        ),
    )

    private val _host = MutableStateFlow(prefs.getString("host", null) ?: BuildConfig.DEFAULT_HOST)
    val host: StateFlow<String> = _host.asStateFlow()

    private val _brain = MutableStateFlow(prefs.getString("brain", null) ?: BRAIN_LOCAL)
    val brain: StateFlow<String> = _brain.asStateFlow()

    /** Modo de permisos de Claude Code (ver MODO_ASK/MODO_AUTO/MODO_PLAN). */
    private val _modoClaude = MutableStateFlow(prefs.getString("modo_claude", null) ?: MODO_ASK)
    val modoClaude: StateFlow<String> = _modoClaude.asStateFlow()

    /** Modelo de Claude Code (ver MODELO_DEFECTO/SONNET/OPUS/HAIKU). Vacio =
     * no forzar nada, que decida la CLI. */
    private val _modeloClaude = MutableStateFlow(prefs.getString("modelo_claude", null) ?: MODELO_DEFECTO)
    val modeloClaude: StateFlow<String> = _modeloClaude.asStateFlow()

    /** Esfuerzo de Claude Code (ver ESFUERZO_DEFECTO/LOW/MEDIUM/HIGH/XHIGH/MAX). */
    private val _esfuerzoClaude = MutableStateFlow(prefs.getString("esfuerzo_claude", null) ?: ESFUERZO_DEFECTO)
    val esfuerzoClaude: StateFlow<String> = _esfuerzoClaude.asStateFlow()

    /** Interprete de la ventana Terminal: SHELL_POWERSHELL o SHELL_CMD. */
    private val _shellTerminal = MutableStateFlow(prefs.getString("shell_terminal", null) ?: SHELL_POWERSHELL)
    val shellTerminal: StateFlow<String> = _shellTerminal.asStateFlow()

    /** Solo el chat del cerebro que estas mirando. */
    val items: StateFlow<List<Item>> =
        combine(_chats, _brain) { chats, b -> chats[b].orEmpty() }
            .stateIn(scope, SharingStarted.Eagerly, emptyList())

    private val _aiState = MutableStateFlow("")
    val aiState: StateFlow<String> = _aiState.asStateFlow()

    private val _tools = MutableStateFlow<List<String>>(emptyList())
    val tools: StateFlow<List<String>> = _tools.asStateFlow()

    /** Ultima medida del PC (pestana Monitor). null hasta el primer refresco. */
    private val _stats = MutableStateFlow<Stats?>(null)
    val stats: StateFlow<Stats?> = _stats.asStateFlow()

    /** El texto de la medida, para cuando el PC no manda datos (protocolo viejo)
     * o no ha podido medir: ahi lo unico que hay que ensenar es lo que diga. */
    private val _statsText = MutableStateFlow("")
    val statsText: StateFlow<String> = _statsText.asStateFlow()

    /** paths.json, leido por el PC. Lo pide ChatStore al conectar: la pestana de
     * Acciones rapidas necesita la lista ANTES de que toques nada, y pedirla al
     * abrir la pestana la dejaba en blanco el primer segundo. */
    private val _proyectos = MutableStateFlow<List<Proyecto>>(emptyList())
    val proyectos: StateFlow<List<Proyecto>> = _proyectos.asStateFlow()

    /** Resultado de la ultima accion directa (reboot_pc, shutdown_pc, cancel_shutdown). */
    private val _actionStatus = MutableStateFlow("")
    val actionStatus: StateFlow<String> = _actionStatus.asStateFlow()

    /**
     * El estado de la app de escritorio del PC (pestana App). null hasta el
     * primer app.state. Se refresca solo mientras se mira esa pestana.
     */
    private val _appState = MutableStateFlow<ServerMsg.AppState?>(null)
    val appState: StateFlow<ServerMsg.AppState?> = _appState.asStateFlow()

    /**
     * Los monitores del PC (v16, ver protocol.SCREENS_RESULT). Vacio hasta la
     * primera respuesta. Se pide una vez al abrir la pestana -- no en bucle
     * como [appState]: la geometria de un monitor no cambia sola.
     */
    private val _pantallas = MutableStateFlow<List<Pantalla>>(emptyList())
    val pantallas: StateFlow<List<Pantalla>> = _pantallas.asStateFlow()

    /** El monitor que se esta viendo (o se veria al pulsar "Ver la pantalla").
     * Null hasta que llega la primera [_pantallas] y se elige la principal. */
    private val _pantallaActual = MutableStateFlow<Pantalla?>(null)
    val pantallaActual: StateFlow<Pantalla?> = _pantallaActual.asStateFlow()

    /**
     * La conversacion de la app a la que va lo que escribas. Vacio = "la que
     * este abierta en el PC".
     *
     * Se manda ademas de haberla abierto con app.open porque entre abrirla y
     * escribir puede haber pasado cualquier cosa delante del PC: el PC compara
     * este titulo con la que de verdad esta abierta y solo la cambia si hace
     * falta (ver brain_app.chat). Vale mas repetirse que escribir en la
     * conversacion equivocada.
     */
    private val _sesionApp = MutableStateFlow("")
    val sesionApp: StateFlow<String> = _sesionApp.asStateFlow()

    /** Se pidio empezar conversacion nueva en la app y falta la confirmacion.
     * El chat de la pestana no se vacia hasta que el PC devuelve el estado: es
     * el mismo criterio que con session.new_ok, no afirmar lo que no se ha visto. */
    private var esperandoNuevaApp = false

    /**
     * Los tokens de la CUENTA de Claude cuando NO estan bien; null mientras todo va
     * normal. Es lo que pinta la banda de aviso encima de la caja de texto.
     *
     * Se guarda ademas de escribirse en el chat porque un aviso en el chat se va
     * hacia arriba en cuanto llegan tres mensajes mas, y "no hay tokens hasta las
     * 21:00" es justo lo que tiene que seguir viendose sin buscarlo.
     */
    private val _limite = MutableStateFlow<ServerMsg.Limite?>(null)
    val limite: StateFlow<ServerMsg.Limite?> = _limite.asStateFlow()

    /**
     * Igual que [_limite] pero SIN anularse cuando todo va bien ("allowed").
     * [_limite] solo existe para el banner de aviso ("sin tokens"), que tiene
     * que desaparecer en cuanto se soluciona; esto alimenta la barra continua
     * de uso, que tiene que seguir mostrando el ultimo porcentaje conocido
     * pase lo que pase -- una barra que desaparece en "allowed" no serviria
     * para nada, porque "allowed" es el estado normal el 99% del tiempo.
     */
    private val _ultimoLimiteConocido = MutableStateFlow<ServerMsg.Limite?>(null)
    val ultimoLimiteConocido: StateFlow<ServerMsg.Limite?> = _ultimoLimiteConocido.asStateFlow()

    /** Ultimo `status` que mando el PC, para no repetir el mismo aviso dos veces. */
    private var ultimoLimite: String? = null

    // --- traspaso: portapapeles y archivos (v14) ----------------------------

    /**
     * Lo que se ha ido copiando en el PC, lo último primero. Es una lista y no
     * un solo texto porque el caso real es copiar tres cosas seguidas delante
     * del PC y coger el móvil después: con un solo hueco, las dos primeras se
     * habrían perdido sin que nadie las viera.
     */
    private val _clips = MutableStateFlow<List<ClipPc>>(emptyList())
    val clips: StateFlow<List<ClipPc>> = _clips.asStateFlow()

    /**
     * El texto que ha llegado del PC y todavía NO se ha podido dejar en el
     * portapapeles del teléfono. Sólo el más reciente: recuperar uno viejo es un
     * botón que se toca a mano, no algo que deba pasar solo por abrir la app.
     */
    val pendienteCopiar: StateFlow<ClipPc?> =
        _clips.map { lista -> lista.firstOrNull()?.takeIf { !it.copiado } }
            .stateIn(scope, SharingStarted.Eagerly, null)

    /** Si el PC vigila su portapapeles para mandarnos lo que se copie (clip.watch). */
    private val _vigilarClip = MutableStateFlow(prefs.getBoolean("vigilar_clip", true))
    val vigilarClip: StateFlow<Boolean> = _vigilarClip.asStateFlow()

    /**
     * Si la pantalla está delante del usuario ahora mismo. Lo pone ChatScreen al
     * entrar y salir de primer plano, y decide dos cosas: si se intenta copiar
     * al portapapeles (Android sólo deja hacerlo en primer plano) y si sale el
     * aviso en la barra de notificaciones (avisar de algo que ya se está viendo
     * es ruido).
     */
    private val _enPrimerPlano = MutableStateFlow(false)
    val enPrimerPlano: StateFlow<Boolean> = _enPrimerPlano.asStateFlow()

    /** Última cosa que decir en el panel de Traspaso ("copiado", "el PC no tiene
     * texto copiado", "no hay conexión"). Vacío = no hay nada que decir. */
    private val _avisoTraspaso = MutableStateFlow("")
    val avisoTraspaso: StateFlow<String> = _avisoTraspaso.asStateFlow()

    /** Los archivos que van camino del PC, el último primero. */
    private val _envios = MutableStateFlow<List<Envio>>(emptyList())
    val envios: StateFlow<List<Envio>> = _envios.asStateFlow()

    /**
     * Las subidas van de una en una. No es prudencia de más: son varios MB por
     * un enlace de datos, y lanzarlas a la vez sólo reparte el mismo ancho de
     * banda entre todas -- tardan lo mismo y ninguna termina hasta el final,
     * así que no se puede ir viendo cuáles ya están.
     */
    private val envioEnCurso = Mutex()

    /**
     * Cola, no un hueco de uno. Si llegaban dos permisos seguidos, el segundo
     * machacaba al primero: la tarjeta del primero desaparecia de la pantalla sin
     * que nadie la contestara y su turno se quedaba esperando hasta caducar.
     */
    private val _permisos = MutableStateFlow<List<Pending>>(emptyList())
    val pending: StateFlow<Pending?> = _permisos.map { it.firstOrNull() }
        .stateIn(scope, SharingStarted.Eagerly, null)

    /**
     * La pregunta de Claude (AskUserQuestion) que sigue SIN responder, o null.
     *
     * Se dibuja como recuadro CENTRADO por encima de todo (ver QuestionDialog en
     * ChatScreen), por el mismo motivo que el permiso es un Dialog y no una
     * tarjeta al final del chat: una pregunta metida entre los mensajes se va
     * hacia arriba en cuanto llegan dos respuestas mas, y contestarla a botonazos
     * desde ahi es justo lo que no funcionaba. La pregunta sigue guardada como
     * Item.Question en el historial (para dejar escrito lo que elegiste), pero
     * MIENTRAS esta sin responder lo que manda es este recuadro.
     *
     * Solo una a la vez; si hubiera varias sin responder, la primera. Se saca de
     * _chats.values (todas las conversaciones) porque solo Claude pregunta y su
     * chat no tiene por que ser el que estas mirando en ese instante.
     */
    val pregunta: StateFlow<Item.Question?> =
        _chats.map { chats ->
            chats.values.asSequence().flatten()
                .firstOrNull { it is Item.Question && it.respondido == null } as Item.Question?
        }.stateIn(scope, SharingStarted.Eagerly, null)

    private val _turnos = MutableStateFlow(
        mapOf(
            BRAIN_LOCAL to Turno.Parado as Turno,
            BRAIN_CLAUDE to Turno.Parado,
            BRAIN_TERMINAL to Turno.Parado,
            BRAIN_APP to Turno.Parado,
        ),
    )

    /** El estado del turno del cerebro que estas mirando. */
    val turno: StateFlow<Turno> =
        combine(_turnos, _brain) { t, b -> t[b] ?: Turno.Parado }
            .stateIn(scope, SharingStarted.Eagerly, Turno.Parado)

    /** Turnos vivos por cerebro: el turno vuelve a Parado cuando no queda ninguno. */
    private val vivos = mutableMapOf(
        BRAIN_LOCAL to mutableSetOf<String>(),
        BRAIN_CLAUDE to mutableSetOf(),
        BRAIN_TERMINAL to mutableSetOf(),
        BRAIN_APP to mutableSetOf(),
    )

    /** id de mensaje -> cerebro que lo pidio. Es lo que reparte cada evento a su chat. */
    private val msgBrain = mutableMapOf<String, String>()

    /** Texto en streaming en curso, por id de mensaje. */
    private val streamKeys = mutableMapOf<String, String>()

    /**
     * `key` de la tarjeta ToolCall que esta corriendo AHORA, para saber que
     * tarjeta actualizar cuando llega un tool_progress. Un solo puntero basta:
     * el servidor ejecuta las tools de una en una dentro de un mismo turno
     * (brain_local.py las procesa en un `for` secuencial), nunca en paralelo.
     */
    private var toolKeyEnCurso: String? = null

    init {
        // Empieza a escuchar en cuanto existe el servicio y no para hasta que el
        // servicio muere. Que la pantalla exista o no da igual: es justo el punto.
        scope.launch {
            client.events.collect { msg ->
                when (msg) {
                    is ServerMsg.Hello -> {
                        _tools.value = msg.tools
                        sysBoth("conectado — ${msg.tools.size} herramientas disponibles")
                        client.requestAiStatus()
                        client.requestProjects()
                        // El vigilante del portapapeles vive en el PC atado a
                        // ESTE socket y muere con él (ver Session.parar_clip),
                        // así que hay que volver a encenderlo en cada conexión,
                        // no sólo la primera vez que se toca el interruptor.
                        client.watchClip(_vigilarClip.value)
                    }
                    is ServerMsg.Delta -> appendDelta(msg.id, msg.text)
                    is ServerMsg.End -> {
                        closeStream(msg.id)
                        finTurno(msg.id)
                    }
                    is ServerMsg.ToolCall -> {
                        val key = uniq(msg.id)
                        toolKeyEnCurso = key
                        add(brainOf(msg.id), Item.ToolCall(key, msg.name, msg.args))
                        fase(msg.id, Turno.Ejecutando(msg.name, "", ahora()))
                        // Una tool acaba de correr: el estado de VRAM ha cambiado.
                        client.requestAiStatus()
                    }
                    is ServerMsg.ToolProgress -> {
                        updateToolProgress(msg.text)
                        // El cronometro cuenta la tool entera, no la ultima linea:
                        // si se reiniciara con cada tool_progress, un build marcaria
                        // "0s" para siempre y no dirias nunca si va lento o esta muerto.
                        val previo = _turnos.value[brainOf(msg.id)]
                        val desde = if (previo is Turno.Ejecutando && previo.tool == msg.name) previo.desde else ahora()
                        fase(msg.id, Turno.Ejecutando(msg.name, msg.text, desde))
                    }
                    is ServerMsg.ToolResult -> {
                        toolKeyEnCurso = null
                        add(brainOf(msg.id), Item.ToolResult(uniq(msg.id), msg.name, msg.text))
                        fase(msg.id, Turno.Pensando(ahora()))
                    }
                    is ServerMsg.MissingTool -> add(brainOf(msg.id), Item.Missing(uniq(msg.id), msg.text))
                    is ServerMsg.PermissionRequest -> {
                        _permisos.value += Pending(
                            msg.reqId, msg.brain, msg.name, msg.args, msg.motivo, msg.savable,
                            msg.sugerencia, msg.admin,
                        )
                        faseBrain(msg.brain, Turno.EsperandoPermiso(msg.name, ahora()))
                    }
                    // El permiso caduco o su turno murio: quitar la tarjeta. Si se
                    // dejara puesta, taparia la pantalla esperando una respuesta
                    // que ya no va a escuchar nadie.
                    is ServerMsg.PermissionCancel -> {
                        val muerto = _permisos.value.firstOrNull { it.reqId == msg.reqId }
                        _permisos.value = _permisos.value.filterNot { it.reqId == msg.reqId }
                        muerto?.let { sys(it.brain, "el permiso de ${it.name} caducó — no se ejecutó") }
                        // Un question.request usa el mismo req_id y la misma
                        // caducidad que un permiso: si caduca, hay que apagarle los
                        // botones a la burbuja para que no la contestes en balde.
                        brainDeQuestion(msg.reqId)?.let { b ->
                            marcarQuestion(msg.reqId, "sin responder — caducó")
                            sys(b, "la pregunta de Claude caducó — no se respondió")
                            if (_turnos.value[b] is Turno.EsperandoRespuesta) faseBrain(b, Turno.Pensando(ahora()))
                        }
                    }
                    is ServerMsg.QuestionRequest -> {
                        add(msg.brain, Item.Question(uniq(msg.reqId), msg.reqId, msg.questions))
                        faseBrain(msg.brain, Turno.EsperandoRespuesta(ahora()))
                    }
                    is ServerMsg.ToolSaved ->
                        sys(
                            BRAIN_LOCAL,
                            if (msg.ok) "herramienta guardada: ${msg.name} — ${msg.text}" else "no se guardó: ${msg.text}",
                        )
                    is ServerMsg.AiState -> _aiState.value = msg.text
                    is ServerMsg.Error -> {
                        val b = msg.id?.let { brainOf(it) } ?: _brain.value
                        sys(b, "error: ${msg.message}")
                        // Ojo: NO se cierra el turno aqui. Un error a mitad de turno
                        // no es el final del turno -- el servidor sigue y manda su
                        // chat.end igual. Cerrarlo aqui era lo que hacia que el
                        // indicador se parase con el turno todavia en marcha.
                    }
                    is ServerMsg.ArtifactReady ->
                        add(brainOf(msg.id), Item.Artifact(uniq(msg.id), msg.artifactId, msg.name, msg.size))
                    is ServerMsg.StatsResult -> {
                        _statsText.value = msg.text
                        // Solo se pisa la medida buena si viene otra: si el PC no
                        // manda datos (protocolo viejo, o no pudo medir), es mejor
                        // dejar la ultima que se vio que borrar la pantalla.
                        msg.data?.let { _stats.value = it }
                    }
                    is ServerMsg.ProjectsResult -> _proyectos.value = msg.projects
                    // Los tokens de la cuenta. Siempre al chat de Claude: la IA
                    // local no gasta tokens de nadie, asi que ahi no significa nada.
                    is ServerMsg.Limite -> {
                        // Siempre, a diferencia de _limite: es lo que alimenta
                        // la barra continua (ver el comentario junto al campo).
                        _ultimoLimiteConocido.value = msg
                        val previo = ultimoLimite
                        ultimoLimite = msg.status
                        _limite.value = if (msg.status == "allowed") null else msg
                        when {
                            // El CLI repite el estado de vez en cuando: avisar solo
                            // de los cambios, o el chat se llena de lo mismo.
                            msg.status == previo -> Unit
                            msg.status != "allowed" -> sys(BRAIN_CLAUDE, textoLimite(msg))
                            previo != null -> sys(BRAIN_CLAUDE, "tokens restablecidos — ya puedes seguir")
                        }
                    }
                    is ServerMsg.ActionResult ->
                        // El turno NO se cierra aqui: lo cierra el chat.end que el PC
                        // manda al terminar la accion, igual que en un turno de chat.
                        // Antes se cerraba aqui porque una accion no mandaba chat.end;
                        // ahora si, y cerrarlo dos veces apagaba el indicador antes de
                        // tiempo cuando la tool seguia soltando progreso.
                        _actionStatus.value = if (msg.ok) msg.text else "No se hizo ${msg.name}: ${msg.text}"
                    // Confirmacion de que el PC ya olvido el contexto de ese
                    // cerebro (ver nuevaSesion). Se vacia AQUI, no al pulsar el
                    // boton: no se afirma que se limpio hasta que el PC lo
                    // confirma de verdad (mismo criterio que el resto de esta
                    // clase, ver ARQUITECTURA.md "la interfaz afirmaba cosas
                    // que no habia comprobado").
                    is ServerMsg.SessionNewOk -> {
                        _chats.value = _chats.value + (msg.brain to emptyList())
                        sys(msg.brain, "nueva sesión — sin contexto anterior")
                    }
                    is ServerMsg.AppState -> {
                        _appState.value = msg
                        // La app manda; el movil solo la sigue. Si delante del PC
                        // se cambia de conversacion, la pestana lo refleja en el
                        // siguiente refresco en vez de seguir apuntando a una que
                        // ya no es la abierta.
                        msg.titulo?.let { _sesionApp.value = it }
                        if (esperandoNuevaApp) {
                            esperandoNuevaApp = false
                            _sesionApp.value = ""
                            _chats.value = _chats.value + (BRAIN_APP to emptyList())
                            sys(BRAIN_APP, "conversación nueva en la app del PC")
                        }
                        if (msg.error.isNotBlank()) sys(BRAIN_APP, "la app: ${msg.error}")
                    }
                    // La respuesta de vídeo no es cosa del historial: la recoge
                    // ConnectionService y se la da directamente al motor de
                    // WebRTC (ver VideoCliente). Aquí sólo hay que no ignorarla
                    // en silencio, para que el `when` siga siendo exhaustivo y
                    // el compilador avise si mañana aparece un mensaje nuevo.
                    is ServerMsg.ClipText -> recibirPortapapeles(msg.text, msg.cortado)
                    is ServerMsg.RtcAnswer -> Unit
                    is ServerMsg.ScreensResult -> {
                        _pantallas.value = msg.screens
                        // La primera vez (o si la que se estaba viendo ya no
                        // existe: se desconecto un monitor) se cae a la
                        // principal. Si ya habia una elegida y sigue en la
                        // lista, se respeta -- es la que el usuario tocó.
                        val actual = _pantallaActual.value
                        if (actual == null || msg.screens.none { it.id == actual.id }) {
                            _pantallaActual.value = msg.screens.firstOrNull { it.principal }
                                ?: msg.screens.firstOrNull()
                        }
                    }
                }
            }
        }

        // El otro lado del arreglo del indicador mentiroso.
        //
        // Un turno solo lo cierra el chat.end del PC. Si la conexion se cae a
        // mitad (sales de casa y saltas de WiFi a datos, el PC se apaga, se cierra
        // arrancar.bat), ese chat.end no va a llegar NUNCA: el turno se quedaba
        // vivo y el cronometro contando "ejecutando build_gradle... 14 min" de un
        // build que ya no existe, o del que nadie va a saber nada nunca mas. Es
        // literalmente la app contandote lo que se imagina que estara pasando al
        // otro lado.
        //
        // Se hace aqui y no en la pantalla porque los turnos viven aqui, y esto
        // tiene que pasar exista o no la Activity: si se pierde la conexion con el
        // movil en el bolsillo, al abrirlo tiene que estar ya limpio y no
        // ensenandote un cronometro de mentira.
        scope.launch {
            client.state.collect { estado ->
                if (estado is Conn.Online) return@collect

                val conTurno = _turnos.value.filterValues { it !is Turno.Parado }.keys
                for (b in conTurno) {
                    sys(b, "se perdió la conexión con el PC — este turno ya no se puede seguir desde aquí")
                    vivos.getValue(b).clear()
                    faseBrain(b, Turno.Parado)
                }
                msgBrain.clear()
                toolKeyEnCurso = null

                // Las tarjetas de permiso pendientes tampoco valen ya: su req_id
                // murio con la Session del PC, asi que pulsar Permitir mandaria un
                // "si" por un socket que no existe y el PC, que ya lo dio por
                // denegado al caducar, no se enteraria. Dejarlas puestas solo sirve
                // para taparte la pantalla con una decision que no decide nada.
                if (_permisos.value.isNotEmpty()) {
                    _permisos.value.forEach { sys(it.brain, "el permiso de ${it.name} se cayó con la conexión — no se ejecutó") }
                    _permisos.value = emptyList()
                }

                // Las preguntas sin contestar mueren igual que las tarjetas de
                // permiso: su req_id se fue con la Session del PC, asi que tocar una
                // opcion mandaria la respuesta por un socket que ya no existe.
                val chatsConQ = _chats.value.filterValues { lista ->
                    lista.any { it is Item.Question && it.respondido == null }
                }.keys
                if (chatsConQ.isNotEmpty()) {
                    _chats.value = _chats.value.mapValues { (_, lista) ->
                        lista.map { if (it is Item.Question && it.respondido == null) it.copy(respondido = "sin responder — se cayó la conexión") else it }
                    }
                    chatsConQ.forEach { sys(it, "una pregunta de Claude se cayó con la conexión — no se respondió") }
                }
            }
        }
    }

    fun setHost(value: String) {
        _host.value = value
        prefs.edit().putString("host", value).apply()
    }

    fun setBrain(value: String) {
        _brain.value = value
        prefs.edit().putString("brain", value).apply()
    }

    fun setModoClaude(value: String) {
        _modoClaude.value = value
        prefs.edit().putString("modo_claude", value).apply()
        // Un cambio de modo a mitad de turno no hace nada hasta el proximo
        // mensaje: el PC solo lo aplica al entrar en handle_chat (server.py).
        sys(BRAIN_CLAUDE, when (value) {
            MODO_AUTO -> "modo automático: Claude no pedirá permiso"
            MODO_PLAN -> "modo plan: Claude solo lee y propone"
            else -> "modo preguntar: Claude pedirá permiso como siempre"
        })
    }

    fun setModeloClaude(value: String) {
        _modeloClaude.value = value
        prefs.edit().putString("modelo_claude", value).apply()
        // Igual que el modo: no hace nada hasta el proximo mensaje. Si solo
        // cambia el modelo (no el esfuerzo ni el proyecto), el PC lo aplica en
        // caliente sin perder la conversacion (ver brain_claude.ClaudeBrain).
        sys(BRAIN_CLAUDE, "modelo → ${etiquetaModelo(value)}")
    }

    fun setEsfuerzoClaude(value: String) {
        _esfuerzoClaude.value = value
        prefs.edit().putString("esfuerzo_claude", value).apply()
        // A diferencia del modelo, cambiar el esfuerzo SI reconecta (el SDK no
        // permite cambiarlo en caliente): el proximo turno empieza sin la
        // conversacion anterior. Se avisa para que no sea una sorpresa.
        sys(BRAIN_CLAUDE, "esfuerzo → ${etiquetaEsfuerzo(value)} (la próxima respuesta empieza una conversación nueva)")
    }

    fun setShellTerminal(value: String) {
        _shellTerminal.value = value
        prefs.edit().putString("shell_terminal", value).apply()
        sys(BRAIN_TERMINAL, "intérprete → ${if (value == SHELL_CMD) "cmd" else "PowerShell"}")
    }

    /** Pide al PC olvidar el contexto del cerebro que se esta mirando ahora
     * mismo. No se limpia nada en el movil hasta que llegue session.new_ok. */
    fun nuevaSesion() {
        val b = _brain.value
        // La pestana App no tiene "contexto" que olvidar en el PC: su
        // conversacion vive en la app de escritorio. "Nueva" ahi significa
        // pulsar su boton de conversacion nueva, que es otra cosa.
        if (b == BRAIN_APP) {
            nuevaSesionApp()
            return
        }
        if (!client.newSession(b)) {
            sys(b, "no se pidió nueva sesión: no hay conexión con el PC")
        }
    }

    // --- la app de escritorio (pestana App) ---------------------------------
    //
    // Ninguna de estas afirma nada: mandan la orden y esperan a que el PC
    // devuelva el estado de la app. Lo que se pinta es lo que la app dice de si
    // misma, no lo que el movil supone que habra pasado tras pulsar.

    fun refrescarApp() {
        client.requestAppState()
    }

    fun abrirSesionApp(titulo: String) {
        _sesionApp.value = titulo
        if (!client.openAppSession(titulo)) {
            sys(BRAIN_APP, "no se pudo abrir «$titulo»: no hay conexión con el PC")
        }
    }

    fun nuevaSesionApp() {
        if (!client.newAppSession()) {
            sys(BRAIN_APP, "no se pidió conversación nueva: no hay conexión con el PC")
            return
        }
        esperandoNuevaApp = true
    }

    /** Pulsa un boton de la app por su nombre (ver ServerMsg.AppState.mandos). */
    fun pulsarApp(nombre: String) {
        if (!client.pressApp(nombre)) {
            sys(BRAIN_APP, "no se pulsó «$nombre»: no hay conexión con el PC")
        }
    }

    fun pararApp() {
        if (!client.stopApp()) {
            sys(BRAIN_APP, "no se pidió parar: no hay conexión con el PC")
        }
    }

    /** Pide la lista de monitores del PC (v16). Se llama al abrir la pestaña
     * App y si el vídeo falla -- no en bucle, ver [_pantallas]. */
    fun refrescarPantallas() {
        client.requestScreens()
    }

    /** Elige qué monitor se ve/controla. No para el vídeo por sí sola: quien
     * llama decide si hace falta renegociar (ver ChatViewModel.cambiarPantalla). */
    fun elegirPantalla(p: Pantalla) {
        _pantallaActual.value = p
    }

    /** Botón "Copiar selección" sobre el vídeo (v16). A diferencia de
     * tocar/arrastrar/desplazar, que son gestos continuos y callan si fallan,
     * esto es un botón con nombre propio: su fracaso merece una línea, igual
     * que el resto de mandos de esta pestaña. */
    fun copiarSeleccionApp() {
        val monitor = _pantallaActual.value?.id ?: return
        if (!client.copyScreen(monitor)) {
            sys(BRAIN_APP, "no se pidió copiar: no hay conexión con el PC")
        }
    }

    // -- el puntero y el teclado sobre el vídeo (v16, antes Fase E.1) --------
    //
    // Ninguno escribe en la conversación cuando falla, al revés que los mandos de
    // arriba. Un mando es una orden con nombre y su fracaso merece una línea; un
    // gesto es un dedo sobre una imagen, y sin conexión el vídeo ya está
    // congelado delante de ti — decirlo además una vez por muesca llenaría el
    // chat de ruido sobre algo que ya se está viendo. [ControladoraClient.enviar]
    // lo deja anotado en el log de diagnóstico igualmente.
    //
    // Los cuatro toman el `id` del monitor como parámetro y no de
    // [_pantallaActual] directamente: quien pinta el vídeo (VideoPanel) ya
    // sabe sobre qué [Pantalla] está el dedo -- es la misma que uso para el
    // aspect ratio -- y pasarla evita una carrera si el usuario cambia de
    // monitor justo cuando un gesto está a medias.

    fun tocarApp(monitor: String, fx: Float, fy: Float) {
        client.tapScreen(monitor, fx, fy)
    }

    fun arrastrarApp(monitor: String, fx: Float, fy: Float, fx2: Float, fy2: Float) {
        client.dragScreen(monitor, fx, fy, fx2, fy2)
    }

    fun desplazarApp(monitor: String, fx: Float, fy: Float, muescas: Int) {
        client.scrollScreen(monitor, fx, fy, muescas)
    }

    /** Teclado libre (v16, Fase E.2): teclea [texto] donde esté el foco en el PC. */
    fun escribirEnPantalla(texto: String) {
        val monitor = _pantallaActual.value?.id ?: return
        client.typeScreen(monitor, texto)
    }

    /** Una tecla especial del teclado libre (Intro, Retroceso...). */
    fun teclaEnPantalla(tecla: String) {
        val monitor = _pantallaActual.value?.id ?: return
        client.keyScreen(monitor, tecla)
    }

    /**
     * Manda un mensaje al cerebro seleccionado. Si el socket no lo acepta, NO se
     * abre ningun turno: se dice que no salio y se queda ahi.
     *
     * Esa comprobacion es el arreglo del "se inventa lo que hace": antes esto
     * llamaba a client.send() sin mirar el resultado (que ni existia) y marcaba el
     * turno como vivo pasara lo que pasara. Con el PC apagado, escribir dejaba tu
     * mensaje pintado en el chat como si se hubiera enviado y el indicador contando
     * los segundos que llevaba "pensando" una IA que jamas recibio nada.
     */
    fun send(text: String) {
        if (text.isBlank()) return
        val clean = text.trim()
        val b = _brain.value
        val modo = if (b == BRAIN_CLAUDE) _modoClaude.value else MODO_ASK
        val modelo = if (b == BRAIN_CLAUDE) _modeloClaude.value else ""
        val esfuerzo = if (b == BRAIN_CLAUDE) _esfuerzoClaude.value else ""
        val shell = if (b == BRAIN_TERMINAL) _shellTerminal.value else ""
        val sesion = if (b == BRAIN_APP) _sesionApp.value else ""

        val id = client.send(clean, b, modo, modelo, esfuerzo, shell, sesion)
        if (id == null) {
            // El mensaje se pinta igualmente: lo escribiste, y verlo desaparecer
            // sin mas seria peor. Pero se marca como no enviado y no abre turno.
            add(b, Item.Text(key = "me-fallido-${System.nanoTime()}", mine = true, text = clean))
            sys(b, "no se envió: no hay conexión con el PC")
            return
        }

        msgBrain[id] = b
        add(b, Item.Text(key = "me-$id", mine = true, text = clean))
        vivos.getValue(b) += id
        faseBrain(b, Turno.Pensando(ahora()))
    }

    /**
     * Una accion de un boton: la tool que dice, con los argumentos que dice, sin
     * pasar por ningun cerebro y sin gastar un token.
     *
     * Abre un turno igual que [send] porque para el usuario es lo mismo (algo esta
     * pasando en el PC y quiere ver por donde va), y el PC manda los mismos
     * eventos: tarjeta de tool, progreso en vivo, resultado y chat.end.
     */
    fun runAction(name: String, args: Map<String, Any> = emptyMap(), titulo: String = name) {
        val id = client.runAction(name, args)
        if (id == null) {
            _actionStatus.value = "No se pidió «$titulo»: no hay conexión con el PC"
            return
        }
        _actionStatus.value = ""
        msgBrain[id] = BRAIN_LOCAL
        vivos.getValue(BRAIN_LOCAL) += id
        faseBrain(BRAIN_LOCAL, Turno.Pensando(ahora()))
    }

    /** [action]: "allow" ejecuta una vez, "save" ejecuta y guarda, "deny" no ejecuta nada. */
    fun answerPermission(action: String, nombre: String = "") {
        val p = _permisos.value.firstOrNull() ?: return
        client.replyPermission(p.reqId, action, nombre)
        _permisos.value = _permisos.value.drop(1)
        sys(
            p.brain,
            when (action) {
                "allow" -> "aprobaste ${p.name}"
                "save" -> "aprobaste ${p.name} y pediste guardarlo como «$nombre»"
                else -> "rechazaste ${p.name}"
            },
        )
        // Contestado: el turno vuelve a estar en manos del cerebro.
        faseBrain(p.brain, Turno.Pensando(ahora()))
    }

    /**
     * Contesta un AskUserQuestion: [answers] es {texto de la pregunta: etiqueta
     * elegida}. Manda la respuesta, apaga los botones de la burbuja (para que no la
     * contestes dos veces) y devuelve el turno al cerebro.
     */
    fun answerQuestion(reqId: String, answers: Map<String, String>) {
        // null = ya contestada o caducada: no se reenvia nada.
        val b = brainDeQuestion(reqId) ?: return
        client.replyQuestion(reqId, answers)
        val resumen = answers.values.joinToString(", ")
        marcarQuestion(reqId, resumen)
        sys(b, "respondiste: $resumen")
        faseBrain(b, Turno.Pensando(ahora()))
    }

    /** El cerebro cuyo chat tiene una pregunta con ese req_id AUN sin responder, o null. */
    private fun brainDeQuestion(reqId: String): String? =
        _chats.value.entries.firstOrNull { (_, lista) ->
            lista.any { it is Item.Question && it.reqId == reqId && it.respondido == null }
        }?.key

    /** Deja la burbuja de esa pregunta con [resumen] escrito y sin botones. */
    private fun marcarQuestion(reqId: String, resumen: String) {
        _chats.value = _chats.value.mapValues { (_, lista) ->
            lista.map { if (it is Item.Question && it.reqId == reqId) it.copy(respondido = resumen) else it }
        }
    }

    // --- traspaso: portapapeles (v14) ---------------------------------------

    /**
     * Llegó texto del PC. Se guarda; copiarlo al portapapeles del teléfono es
     * otra cosa y la hace el ViewModel, que es quien tiene Context (y sólo
     * funciona en primer plano, ver ClipPc.copiado).
     *
     * El texto vacío NO se guarda: significa que el PC no tiene texto copiado
     * (habrá copiado una imagen o un archivo). Meterlo en la lista taparía lo
     * anterior, que sí servía, con una entrada en blanco.
     *
     * El repetido tampoco. Al reconectar, el vigilante del PC manda de entrada
     * lo último que haya copiado, que casi siempre es lo mismo que ya teníamos
     * -- y el móvil se reconecta muchas veces al día (wifi a datos, la app al
     * fondo). Sin esto, la lista se llenaría del mismo texto diez veces.
     */
    private fun recibirPortapapeles(texto: String, cortado: Boolean) {
        if (texto.isEmpty()) {
            _avisoTraspaso.value = "En el PC no hay texto copiado ahora mismo (será una imagen o un archivo)."
            return
        }
        if (_clips.value.firstOrNull()?.texto == texto) {
            _avisoTraspaso.value = "Ya tenías ese texto: es lo último copiado en el PC."
            return
        }
        _avisoTraspaso.value = ""
        _clips.value = (listOf(ClipPc(texto, cortado, System.currentTimeMillis())) + _clips.value).take(MAX_CLIPS)
    }

    /** Da por copiado en el teléfono el clip de ese momento (lo llama el
     * ViewModel cuando el portapapeles del sistema lo ha aceptado de verdad). */
    fun marcarClipCopiado(cuando: Long) {
        _clips.value = _clips.value.map { if (it.cuando == cuando) it.copy(copiado = true) else it }
    }

    fun setEnPrimerPlano(valor: Boolean) {
        _enPrimerPlano.value = valor
    }

    fun avisoTraspaso(texto: String) {
        _avisoTraspaso.value = texto
    }

    /** El interruptor de "que el PC vigile su portapapeles". Se manda al PC en
     * el momento: apagarlo tiene que dejar de mirar el portapapeles ya, no en la
     * próxima reconexión. */
    fun setVigilarClip(valor: Boolean) {
        _vigilarClip.value = valor
        prefs.edit().putBoolean("vigilar_clip", valor).apply()
        if (!client.watchClip(valor)) {
            _avisoTraspaso.value = "Sin conexión: el PC se enterará al reconectar."
        } else {
            _avisoTraspaso.value = if (valor) {
                "El PC te mandará lo que copies en él."
            } else {
                "El PC ha dejado de mirar su portapapeles."
            }
        }
    }

    /** Botón "traer lo copiado en el PC ahora" (clip.get). */
    fun pedirPortapapeles() {
        if (!client.getClip()) _avisoTraspaso.value = "No se pidió: no hay conexión con el PC."
    }

    /** Manda [texto] al portapapeles del PC (clip.set), para pegarlo allí. */
    fun mandarAlPc(texto: String) {
        if (texto.isEmpty()) {
            _avisoTraspaso.value = "No hay nada copiado en el teléfono."
            return
        }
        _avisoTraspaso.value = if (client.setClip(texto)) {
            "Copiado en el PC: ya se puede pegar allí con Ctrl+V."
        } else {
            "No se mandó: no hay conexión con el PC."
        }
    }

    // --- traspaso: archivos (v14) -------------------------------------------

    /**
     * Manda al PC los archivos elegidos en el selector. Vive aquí y no en el
     * ViewModel por el mismo motivo que el historial del chat: esto corre en el
     * scope de [com.controladora.movil.net.ConnectionService], así que una
     * subida de 200 MB sigue viva aunque salgas de la app a hacer otra cosa. En
     * el ViewModel moriría al cerrarse la pantalla.
     */
    fun enviarArchivos(uris: List<Uri>) {
        if (uris.isEmpty()) return
        scope.launch {
            val elegidos = uris.map { client.datosDe(it) }
            val nuevos = elegidos.map { Envio(id = "${it.uri}-${System.nanoTime()}", nombre = it.nombre, bytes = it.bytes) }
            _envios.value = nuevos + _envios.value
            _avisoTraspaso.value = ""
            // De una en una y en el orden en que se eligieron, aunque se toque
            // el selector otra vez mientras la primera tanda sigue subiendo.
            envioEnCurso.withLock {
                for ((envio, archivo) in nuevos.zip(elegidos)) subirUno(envio, archivo)
            }
        }
    }

    private suspend fun subirUno(envio: Envio, archivo: ArchivoElegido) {
        marcarEnvio(envio.id, EnvioEstado.Subiendo())
        val resultado = client.uploadFile(archivo) { pct -> marcarEnvio(envio.id, EnvioEstado.Subiendo(pct)) }
        marcarEnvio(
            envio.id,
            when (resultado) {
                is UploadResult.Ok -> EnvioEstado.Hecho(resultado.ruta)
                is UploadResult.Failed -> EnvioEstado.Fallo(resultado.reason)
            },
        )
    }

    private fun marcarEnvio(id: String, estado: EnvioEstado) {
        _envios.value = _envios.value.map { if (it.id == id) it.copy(estado = estado) else it }
    }

    /** Quita de la lista lo que ya terminó (bien o mal). Lo que sigue subiendo
     * se queda: borrar de la pantalla algo que está en marcha no lo para, sólo
     * lo esconde. */
    fun limpiarEnvios() {
        _envios.value = _envios.value.filter { it.estado is EnvioEstado.Esperando || it.estado is EnvioEstado.Subiendo }
    }

    /** Avisos que el ViewModel necesita escribir en el chat (p.ej. permisos de Android). */
    fun aviso(brain: String, text: String) = sys(brain, text)

    /** El aviso de tokens, en una linea y con la hora delante de las narices. */
    private fun textoLimite(msg: ServerMsg.Limite): String {
        val vuelve = horaDeReset(msg.resetsAt)?.let { " — vuelve a haber a $it" } ?: ""
        return if (msg.status == "rejected") {
            "sin tokens: llegaste al ${msg.etiqueta} de tu cuenta$vuelve"
        } else {
            val pct = msg.utilizacion?.let { " (${(it * 100).toInt()}% gastado)" } ?: ""
            "queda poco del ${msg.etiqueta} de tu cuenta$pct$vuelve"
        }
    }

    fun updateArtifact(key: String, state: ArtifactState) {
        _chats.value = _chats.value.mapValues { (_, lista) ->
            lista.map { if (it.key == key && it is Item.Artifact) it.copy(state = state) else it }
        }
    }

    private fun ahora() = System.currentTimeMillis()

    /** A que chat va un evento. Si el id no se conoce (reconexion), al que miras. */
    private fun brainOf(id: String): String = msgBrain[id] ?: _brain.value

    private fun fase(id: String, t: Turno) = faseBrain(brainOf(id), t)

    private fun faseBrain(b: String, t: Turno) {
        _turnos.value = _turnos.value + (b to t)
    }

    private fun finTurno(id: String) {
        val b = brainOf(id)
        vivos.getValue(b) -= id
        msgBrain.remove(id)
        if (vivos.getValue(b).isEmpty()) faseBrain(b, Turno.Parado)
    }

    private fun uniq(id: String): String = "$id-${System.nanoTime()}"

    private fun add(brain: String, item: Item) {
        _chats.value = _chats.value + (brain to _chats.value[brain].orEmpty() + item)
    }

    private fun sys(brain: String, text: String) = add(brain, Item.Sys("sys-${System.nanoTime()}", text))

    /** Avisos de conexion: no son de ningun cerebro, valen para los dos chats. */
    private fun sysBoth(text: String) {
        val item = Item.Sys("sys-${System.nanoTime()}", text)
        _chats.value = _chats.value.mapValues { (_, lista) -> lista + item.copy(key = "${item.key}-${System.nanoTime()}") }
    }

    /** El primer delta crea la burbuja; los siguientes la van rellenando. */
    private fun appendDelta(id: String, chunk: String) {
        fase(id, Turno.Escribiendo(ahora()))
        val key = streamKeys[id]
        if (key == null) {
            val nueva = uniq(id)
            streamKeys[id] = nueva
            add(brainOf(id), Item.Text(key = nueva, mine = false, text = chunk, streaming = true))
            return
        }
        _chats.value = _chats.value.mapValues { (_, lista) ->
            lista.map { if (it.key == key && it is Item.Text) it.copy(text = it.text + chunk) else it }
        }
    }

    /** Actualiza la linea de estado EN LA MISMA tarjeta, no anade una nueva:
     * un build suelta muchas lineas y esto no es un log, es un "por donde va". */
    private fun updateToolProgress(texto: String) {
        val key = toolKeyEnCurso ?: return
        _chats.value = _chats.value.mapValues { (_, lista) ->
            lista.map { if (it.key == key && it is Item.ToolCall) it.copy(progreso = texto) else it }
        }
    }

    private fun closeStream(id: String) {
        val key = streamKeys.remove(id) ?: return
        _chats.value = _chats.value.mapValues { (_, lista) ->
            lista.map { if (it.key == key && it is Item.Text) it.copy(text = it.text.trimEnd(), streaming = false) else it }
        }
    }
}
