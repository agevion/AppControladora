package com.controladora.movil.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SecondaryTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.controladora.movil.ArtifactState
import com.controladora.movil.BRAIN_LOCAL
import com.controladora.movil.BRAIN_APP
import com.controladora.movil.BRAIN_TERMINAL
import com.controladora.movil.ChatViewModel
import com.controladora.movil.ESFUERZO_DEFECTO
import com.controladora.movil.ESFUERZO_HIGH
import com.controladora.movil.ESFUERZO_LOW
import com.controladora.movil.ESFUERZO_MAX
import com.controladora.movil.ESFUERZO_MEDIUM
import com.controladora.movil.ESFUERZO_XHIGH
import com.controladora.movil.Item
import com.controladora.movil.MODELO_DEFECTO
import com.controladora.movil.MODELO_HAIKU
import com.controladora.movil.MODELO_OPUS
import com.controladora.movil.MODELO_SONNET
import com.controladora.movil.MODO_ASK
import com.controladora.movil.MODO_AUTO
import com.controladora.movil.MODO_PLAN
import com.controladora.movil.Pending
import com.controladora.movil.SHELL_CMD
import com.controladora.movil.SHELL_POWERSHELL
import com.controladora.movil.Turno
import com.controladora.movil.horaDeReset
import com.controladora.movil.net.Conn
import com.controladora.movil.net.ServerMsg
import kotlinx.coroutines.delay

/**
 * Desplazamiento extra al bajar al ultimo mensaje: suficiente para pasarse de largo
 * y quedarse al FINAL de la burbuja, no en su principio.
 *
 * `scrollToItem(indice, desplazamiento)` deja arriba el item y luego baja esos
 * pixeles, topando al final de la lista. Sin esto, una respuesta mas alta que la
 * pantalla se quedaba con la vista en su primera linea y el resto por debajo del
 * borde -- que es justo el fallo que se estaba arreglando. No es Int.MAX_VALUE
 * para no jugarse un desbordamiento en la aritmetica interna de Compose: son ~50
 * pantallas de movil, y de todas formas se topa al final.
 */
private const val FINAL_DEL_MENSAJE = 100_000

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(vm: ChatViewModel = viewModel()) {
    val state by vm.state.collectAsStateWithLifecycle()
    val items by vm.items.collectAsStateWithLifecycle()
    val host by vm.host.collectAsStateWithLifecycle()
    val log by vm.log.collectAsStateWithLifecycle()
    val brain by vm.brain.collectAsStateWithLifecycle()
    val aiState by vm.aiState.collectAsStateWithLifecycle()
    val pending by vm.pending.collectAsStateWithLifecycle()
    val pregunta by vm.pregunta.collectAsStateWithLifecycle()
    val turno by vm.turno.collectAsStateWithLifecycle()
    val modoClaude by vm.modoClaude.collectAsStateWithLifecycle()
    val modeloClaude by vm.modeloClaude.collectAsStateWithLifecycle()
    val esfuerzoClaude by vm.esfuerzoClaude.collectAsStateWithLifecycle()
    val shellTerminal by vm.shellTerminal.collectAsStateWithLifecycle()
    val ultimoLimiteConocido by vm.ultimoLimiteConocido.collectAsStateWithLifecycle()
    val stats by vm.stats.collectAsStateWithLifecycle()
    val statsText by vm.statsText.collectAsStateWithLifecycle()
    val proyectos by vm.proyectos.collectAsStateWithLifecycle()
    val actionStatus by vm.actionStatus.collectAsStateWithLifecycle()
    val limite by vm.limite.collectAsStateWithLifecycle()
    val video by vm.video.collectAsStateWithLifecycle()
    val pantallas by vm.pantallas.collectAsStateWithLifecycle()
    val pantallaActual by vm.pantallaActual.collectAsStateWithLifecycle()
    val clips by vm.clips.collectAsStateWithLifecycle()
    val pendienteClip by vm.pendienteCopiar.collectAsStateWithLifecycle()
    val vigilarClip by vm.vigilarClip.collectAsStateWithLifecycle()
    val avisoTraspaso by vm.avisoTraspaso.collectAsStateWithLifecycle()
    val envios by vm.envios.collectAsStateWithLifecycle()

    var draft by remember { mutableStateOf("") }
    var showSettings by remember { mutableStateOf(false) }
    var showDebug by remember { mutableStateOf(false) }
    var tab by remember { mutableStateOf(0) }
    // rememberSaveable y no remember: MonitorPanel se descompone al cambiar de
    // pestana (el if(tab==2) de mas abajo ni lo llama), asi que un remember
    // normal olvidaria la vista elegida cada vez que vuelves a Monitor.
    var vistaMonitor by rememberSaveable { mutableStateOf(VistaMonitor.General) }
    val listState = rememberLazyListState()
    val online = state is Conn.Online
    /** Cuantas veces se ha pulsado Actualizar. Ver el LaunchedEffect de mas abajo. */
    var refrescos by remember { mutableIntStateOf(0) }

    // Una accion rapida llama a la tool y salta a la pestana de Chat: si no, te
    // quedas mirando el panel de botones sin ver que ha pasado. El resultado sale
    // en el chat de la IA local (tarjeta de tool + progreso), aunque no haya
    // pasado por ella: es donde ya sabes mirar.
    val onQuickAction: (String, Map<String, Any>, String) -> Unit = { tool, args, titulo ->
        vm.setBrain(BRAIN_LOCAL)
        vm.runAction(tool, args, titulo)
        tab = 0
    }

    // AQUI estaba el "a veces no veo los mensajes nuevos", y no era de red.
    //
    // Esto era `LaunchedEffect(items.size)`: solo se despertaba cuando la lista
    // CAMBIABA DE TAMANO. Y una respuesta en streaming no cambia el tamano de la
    // lista -- el primer delta crea la burbuja (ahi si, un item nuevo, y bajaba) y
    // todos los demas solo engordan el texto de esa misma burbuja, que ya existe
    // (ver ChatStore.appendDelta). Osea que veias las primeras lineas de la
    // respuesta y el resto se escribia por debajo del borde de la pantalla, con la
    // vista clavada donde estaba. Escribir cualquier cosa metia un item nuevo, el
    // tamano cambiaba, esto se despertaba y de golpe "aparecia todo". No aparecia
    // nada: ya estaba escrito, solo que mas abajo.
    //
    // Por eso pasaba en el chat de Claude y casi nunca en el de la IA local: el
    // system prompt le pide a Claude respuestas de tres lineas, asi que lo normal
    // es que quepan y no se note. Cuando se pasa (un plan, un error largo, varias
    // tarjetas de tool seguidas) es cuando la respuesta no cabe y se ve el fallo.
    //
    // El arreglo es mirar tambien cuanto ha crecido el ultimo mensaje, no solo
    // cuantos hay. Y scrollToItem con un desplazamiento grande en vez de
    // animateScrollToItem a secas: aquel dejaba arriba el PRINCIPIO del ultimo
    // mensaje, asi que una respuesta mas alta que la pantalla seguia saliendo
    // cortada por abajo aunque el scroll hubiera "funcionado".
    val ultimoLargo = (items.lastOrNull() as? Item.Text)?.text?.length ?: 0

    // Seguir el final SOLO si ya estabas mirando el final. Si has subido a releer
    // algo, que el chat te arrastre hacia abajo cada vez que llega un trozo de
    // texto es peor que el bug que arregla.
    val pegadoAbajo by remember {
        derivedStateOf {
            val visibles = listState.layoutInfo.visibleItemsInfo
            visibles.isEmpty() || visibles.last().index >= listState.layoutInfo.totalItemsCount - 1
        }
    }

    LaunchedEffect(items.size, ultimoLargo) {
        if (items.isNotEmpty() && pegadoAbajo) listState.scrollToItem(items.lastIndex, FINAL_DEL_MENSAJE)
    }

    // El boton Actualizar (ver la barra de arriba). Va por su propio contador para
    // que baje del todo SIEMPRE, estes mirando donde estes: es lo que se le pide a
    // un boton que pulsas a proposito, a diferencia del seguimiento automatico.
    LaunchedEffect(refrescos) {
        if (refrescos > 0 && items.isNotEmpty()) {
            listState.animateScrollToItem(items.lastIndex, FINAL_DEL_MENSAJE)
        }
    }

    // Estar en primer plano no es un detalle cosmetico aqui: es LA condicion para
    // poder tocar el portapapeles del telefono (Android 10+ se lo prohibe a las
    // apps sin foco). Se sigue con el ciclo de vida y se le cuenta al store, que
    // vive en el servicio y necesita saberlo para decidir si avisar por la barra
    // de notificaciones o no (avisar de algo que ya estas viendo es ruido).
    var enPrimerPlano by remember { mutableStateOf(false) }
    LifecycleResumeEffect(Unit) {
        enPrimerPlano = true
        vm.setEnPrimerPlano(true)
        onPauseOrDispose {
            enPrimerPlano = false
            vm.setEnPrimerPlano(false)
        }
    }

    // Lo que llega del PC se copia solo, sin tener que tocar nada -- pero solo si
    // la app esta DELANTE. Con la pantalla en pausa, setPrimaryClip no falla: no
    // hace nada y devuelve como si hubiera ido bien, asi que darlo por copiado
    // ahi seria exactamente el tipo de mentira que este proyecto lleva evitando
    // desde la Fase 1. Al volver a primer plano, esto se despierta y lo copia.
    LaunchedEffect(pendienteClip, enPrimerPlano) {
        if (enPrimerPlano) pendienteClip?.let { vm.copiarEnTelefono(it) }
    }

    // Los monitores del PC (v16): una vez al entrar en la pestaña (o al
    // reconectar), no en bucle como app.state -- su geometría no cambia sola.
    LaunchedEffect(brain, tab, online) {
        if (brain == BRAIN_APP && tab == 0 && online) vm.refrescarPantallas()
    }

    ControladoraTheme(brain) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Controladora") },
                actions = {
                    StatusDot(state)
                    // Actualizar = ponerse al dia tras volver de segundo plano, en tres
                    // frentes a la vez (ver ChatViewModel.refrescar): baja al final del
                    // ultimo mensaje (el contador de abajo), se reengancha al servicio si
                    // el bind se solto, y RECONECTA si el socket se cayo estando
                    // minimizado. No gasta tokens. Reconectar es seguro: la charla de
                    // Claude vive en el PC y sobrevive a que el socket muera y nazca otro;
                    // y si ya esta Online, refrescar() no toca el socket para no cortar un
                    // turno en marcha.
                    TextButton(
                        onClick = {
                            refrescos++
                            vm.refrescar()
                        },
                    ) { Text("↻", fontSize = 18.sp) }
                    TextButton(onClick = { showSettings = !showSettings }) { Text(host) }
                    TextButton(onClick = { showDebug = !showDebug }) { Text("Log") }
                },
            )
        },
        bottomBar = {
            // La caja de texto vive AQUI, no como un hijo mas de la Column del
            // chat, y esa es la correccion. Dentro de la Column competia por el
            // alto con los botones de Claude (modelo/esfuerzo/modo, los que se
            // añadieron): al abrir el teclado se quedaba sin sitio y salia por
            // debajo del borde, asi que no veias lo que escribias. Como bottomBar
            // queda anclada abajo SIEMPRE -- encima del teclado (imePadding) y de
            // la barra de navegacion -- pase lo que pase arriba. Y crece hacia
            // arriba al teclear (maxLines 4), sin taparse.
            if (tab == 0) {
                Column(Modifier.navigationBarsPadding().imePadding()) {
                    if (brain != BRAIN_LOCAL) limite?.let { LimiteBar(it) }
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        OutlinedTextField(
                            value = draft,
                            onValueChange = { draft = it },
                            modifier = Modifier.weight(1f),
                            placeholder = {
                                Text(
                                    when (brain) {
                                        BRAIN_LOCAL -> "Ordena algo…"
                                        BRAIN_TERMINAL -> "Escribe un comando…"
                                        BRAIN_APP -> "Escribe en la app del PC…"
                                        else -> "Explica una idea…"
                                    },
                                )
                            },
                            shape = RoundedCornerShape(24.dp),
                            maxLines = 4,
                        )
                        Button(
                            onClick = {
                                vm.send(draft)
                                draft = ""
                            },
                            enabled = state is Conn.Online && draft.isNotBlank(),
                        ) { Text("Enviar") }
                    }
                }
            }
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize(),
        ) {
            if (showSettings) {
                HostBar(host, state, vm::setHost, vm::connect, vm::disconnect, vm::reloadTools)
            }
            if (showDebug) {
                DebugPanel(log, vm::clearLog)
            }

            BrainBar(
                brain = brain,
                aiState = aiState,
                modoClaude = modoClaude,
                modeloClaude = modeloClaude,
                esfuerzoClaude = esfuerzoClaude,
                shellTerminal = shellTerminal,
                utilizacion = ultimoLimiteConocido,
                nuevaSesionHabilitada = turno is Turno.Parado,
                onBrain = vm::setBrain,
                onSleep = vm::sleepAi,
                onRefresh = vm::refreshAiStatus,
                onModoClaude = vm::setModoClaude,
                onModeloClaude = vm::setModeloClaude,
                onEsfuerzoClaude = vm::setEsfuerzoClaude,
                onShellTerminal = vm::setShellTerminal,
                onNuevaSesion = vm::nuevaSesion,
            )

            if (brain == BRAIN_APP && tab == 0) {
                val viendoVideo = video is com.controladora.movil.net.Video.Viendo

                // El panel con el título/modelo/lista de sesiones de la app de
                // Claude (AppPanel) ya no se pinta aquí: desde que este panel
                // controla la pantalla entera (v16), esa tarjeta quedó
                // redundante -- lo que importa ahora es el vídeo, no un
                // listado de conversaciones de una app que ya no es lo único
                // que se ve. El chat con la app de Claude sigue funcionando
                // igual por debajo (caja de texto + LazyColumn más abajo).
                VideoPanel(
                    estado = video,
                    egl = vm.eglVideo,
                    pantalla = pantallaActual,
                    pantallas = pantallas,
                    online = online,
                    onVer = vm::verVideo,
                    onParar = vm::pararVideo,
                    onElegirPantalla = vm::cambiarPantalla,
                    // El `id` del monitor viaja capturado en la lambda, no como
                    // parametro de VideoPanel: es la misma [pantallaActual] que
                    // ya usa para el aspect ratio, asi que un gesto nunca puede
                    // ir a un monitor distinto del que se esta viendo.
                    onTocar = { fx, fy -> pantallaActual?.let { vm.tocarApp(it.id, fx, fy) } },
                    onArrastrar = { fx, fy, fx2, fy2 ->
                        pantallaActual?.let { vm.arrastrarApp(it.id, fx, fy, fx2, fy2) }
                    },
                    onDesplazar = { fx, fy, muescas ->
                        pantallaActual?.let { vm.desplazarApp(it.id, fx, fy, muescas) }
                    },
                    onCopiarSeleccion = vm::copiarSeleccionApp,
                    onEscribir = vm::escribirEnPantalla,
                    onTecla = vm::teclaEnPantalla,
                    // Con el vídeo encendido se lleva TODO lo que queda entre la
                    // fila de cerebros y la caja de texto. El `weight` es lo que
                    // garantiza que no invada hacia arriba: reparte el hueco
                    // sobrante, no lo pide prestado de lo que ya está colocado.
                    modifier = if (viendoVideo) Modifier.weight(1f) else Modifier,
                )
                // Viendo el vídeo no se pintan ni las pestañas ni la
                // conversación: no cabrían, y media pestaña asomando debajo de
                // una imagen es peor que no tenerla. Se vuelve con "Dejar de ver".
                if (viendoVideo) return@Column
            }

            // "Acciones" y no "Acciones rápidas" desde que son cuatro pestañas:
            // SecondaryTabRow reparte el ancho a partes iguales, y con la
            // etiqueta larga las cuatro salían partidas en dos líneas.
            SecondaryTabRow(selectedTabIndex = tab) {
                Tab(selected = tab == 0, onClick = { tab = 0 }, text = { Text("Chat") })
                Tab(selected = tab == 1, onClick = { tab = 1 }, text = { Text("Acciones") })
                Tab(selected = tab == 2, onClick = { tab = 2 }, text = { Text("Monitor") })
                Tab(selected = tab == 3, onClick = { tab = 3 }, text = { Text("Traspaso") })
            }

            if (tab == 1) {
                QuickActionsPanel(
                    proyectos = proyectos,
                    online = online,
                    onAction = onQuickAction,
                    onRefreshProyectos = vm::refreshProjects,
                    modifier = Modifier.weight(1f),
                )
                return@Column
            }

            if (tab == 2) {
                MonitorPanel(
                    stats = stats,
                    statsText = statsText,
                    actionStatus = actionStatus,
                    online = online,
                    vista = vistaMonitor,
                    onVista = { vistaMonitor = it },
                    onRefresh = vm::refreshStats,
                    onReboot = vm::rebootPc,
                    onShutdown = vm::shutdownPc,
                    onCancel = vm::cancelShutdown,
                    modifier = Modifier.weight(1f),
                )
                return@Column
            }

            if (tab == 3) {
                TraspasoPanel(
                    clips = clips,
                    vigilar = vigilarClip,
                    aviso = avisoTraspaso,
                    envios = envios,
                    actionStatus = actionStatus,
                    online = online,
                    onVigilar = vm::setVigilarClip,
                    onPedirDelPc = vm::pedirPortapapeles,
                    onCopiar = vm::copiarEnTelefono,
                    onMandarAlPc = vm::mandarPortapapelesAlPc,
                    onArchivos = vm::enviarArchivos,
                    onLimpiarEnvios = vm::limpiarEnvios,
                    onAbrirCarpeta = vm::abrirCarpetaEnPc,
                    modifier = Modifier.weight(1f),
                )
                return@Column
            }

            TurnoBar(turno, online)

            LazyColumn(
                state = listState,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(items, key = { it.key }) { Entry(it, vm::installArtifact, vm::answerQuestion) }
            }

        }

        // Fuera de la Column y como Dialog: se pinta por encima de todo y centrado,
        // pase lo que pase con el layout de debajo y estes en la pestana que estes.
        pending?.let { PermissionDialog(it, vm::answerPermission) }

        // La pregunta de Claude (AskUserQuestion), tambien centrada y por encima
        // de todo, por el mismo motivo que el permiso (ver QuestionDialog). Solo
        // sale mientras esta sin responder; al contestar, el recuadro se va y en
        // el chat queda la burbuja con lo que elegiste.
        pregunta?.let { QuestionDialog(it, vm::answerQuestion) }
    }
    }
}

/**
 * Que esta pasando ahora mismo, en una linea.
 *
 * Antes aqui habia una LinearProgressIndicator indeterminada, y era peor que nada:
 * fingia ser una barra de progreso sin poder medir progreso ninguno (ni Claude ni
 * Gradle dicen cuanto les queda), y ademas se paraba con el turno todavia vivo. Lo
 * que si se puede decir con verdad es la fase y el rato que lleva, y eso es lo que
 * de verdad se quiere saber: si toca esperar o si te toca tocar a ti.
 *
 * Pero seguia mintiendo, y esa era la queja de verdad: decia "pensando… 40s" con el
 * PC apagado. No era culpa suya -- pinta el turno que le den, y se lo daban mal: el
 * envio no comprobaba si el socket existia (ver ChatStore.send) y nada cerraba los
 * turnos al caerse la conexion (ver el collect de client.state en ChatStore). Los
 * dos agujeros estan tapados; [online] es el cinturon y tirantes de aqui: sin
 * conexion no hay nada corriendo en el PC que este indicador pueda estar contando,
 * asi que no se pinta y punto.
 */
@Composable
private fun TurnoBar(turno: Turno, online: Boolean) {
    if (turno is Turno.Parado || !online) return

    var segundos by remember(turno.desde) { mutableStateOf(0L) }
    LaunchedEffect(turno.desde) {
        while (true) {
            segundos = (System.currentTimeMillis() - turno.desde) / 1000
            delay(1000)
        }
    }

    val texto = when (turno) {
        is Turno.Pensando -> "pensando…"
        is Turno.Escribiendo -> "escribiendo…"
        is Turno.Ejecutando ->
            if (turno.linea.isBlank()) "ejecutando ${turno.tool}…" else "${turno.tool}: ${turno.linea}"
        is Turno.EsperandoPermiso -> "esperando tu permiso para ${turno.tool}"
        is Turno.EsperandoRespuesta -> "esperando tu respuesta"
        is Turno.Parado -> ""
    }

    // El permiso es el unico estado en el que la pelota esta en tu tejado, asi que
    // se pinta distinto de "espera, que estoy trabajando". Pero NO en rojo: rojo
    // significa administrador y nada mas (ver PermissionDialog). Esperar a que
    // pulses un boton no es un peligro, es un aviso.
    val fondo = if (turno is Turno.EsperandoPermiso || turno is Turno.EsperandoRespuesta) {
        MaterialTheme.colorScheme.primaryContainer
    } else {
        MaterialTheme.colorScheme.surfaceVariant
    }

    Row(
        Modifier
            .fillMaxWidth()
            .background(fondo)
            .padding(horizontal = 12.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        CircularProgressIndicator(Modifier.size(12.dp), strokeWidth = 2.dp)
        Text(
            texto,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f),
        )
        // El cronometro es lo que distingue "va lento" de "se ha muerto".
        Text("${segundos}s", style = MaterialTheme.typography.labelSmall, fontFamily = FontFamily.Monospace)
    }
}

/**
 * Los tokens de la CUENTA: se acabaron, o queda poco.
 *
 * Va pegada a la caja de texto y no como un mensaje mas del chat porque un mensaje
 * se va hacia arriba en cuanto llegan tres mas, y la hora a la que vuelve a haber
 * tokens tiene que seguir viendose sin buscarla. Es lo unico que quieres saber
 * cuando Claude deja de contestar.
 *
 * No desactiva el boton Enviar: puedes seguir usando la IA local, y el aviso ya
 * dice a las claras que Claude no va a contestar.
 */
@Composable
private fun LimiteBar(limite: ServerMsg.Limite) {
    val agotado = limite.status == "rejected"
    val vuelve = horaDeReset(limite.resetsAt)

    Row(
        Modifier
            .fillMaxWidth()
            .background(
                if (agotado) MaterialTheme.colorScheme.errorContainer
                else MaterialTheme.colorScheme.tertiaryContainer,
            )
            .padding(horizontal = 12.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column {
            Text(
                if (agotado) "Sin tokens — ${limite.etiqueta} de tu cuenta"
                else "Quedan pocos tokens — ${limite.etiqueta} de tu cuenta",
                style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.Bold,
            )
            Text(
                // Sin hora no se inventa ninguna: el CLI no siempre la manda.
                vuelve?.let { "Vuelve a haber a $it" }
                    ?: "El PC no ha dicho a qué hora se restablece",
                style = MaterialTheme.typography.labelSmall,
            )
        }
    }
}

/** Selector de cerebro + estado de la VRAM (o modelo/esfuerzo/modo de permisos, si es Claude). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun BrainBar(
    brain: String,
    aiState: String,
    modoClaude: String,
    modeloClaude: String,
    esfuerzoClaude: String,
    shellTerminal: String,
    utilizacion: ServerMsg.Limite?,
    nuevaSesionHabilitada: Boolean,
    onBrain: (String) -> Unit,
    onSleep: () -> Unit,
    onRefresh: () -> Unit,
    onModoClaude: (String) -> Unit,
    onModeloClaude: (String) -> Unit,
    onEsfuerzoClaude: (String) -> Unit,
    onShellTerminal: (String) -> Unit,
    onNuevaSesion: () -> Unit,
) {
    Column(Modifier.fillMaxWidth()) {
        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 4.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // Los cuatro chips en su propia fila con scroll: en un movil
            // estrecho no caben enteros, y sin scroll el hueco que le "quitan"
            // al boton de Nueva sesion (que va detras, con weight) lo dejaba a
            // 0 de ancho -- Compose entonces parte "Nueva sesión" letra a letra
            // en vertical en vez de recortar el texto, que es el bug que se ve
            // en el movil como una tira de letras en el borde derecho.
            Row(
                Modifier.weight(1f, fill = false).horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                FilterChip(selected = brain == "local", onClick = { onBrain("local") }, label = { Text("IA local") })
                FilterChip(selected = brain == "claude", onClick = { onBrain("claude") }, label = { Text("Claude Code") })
                FilterChip(selected = brain == "terminal", onClick = { onBrain("terminal") }, label = { Text("Terminal") })
                // "App" no es otra IA: maneja la aplicacion de escritorio de Claude
                // que hay abierta en el PC (ver AppPanel y brain_app.py).
                FilterChip(selected = brain == BRAIN_APP, onClick = { onBrain(BRAIN_APP) }, label = { Text("App") })
            }
            // Deshabilitado con un turno en marcha: pedir el reset a mitad de
            // una respuesta es el caso mas confuso (ver ChatStore.nuevaSesion).
            // Fuera de la fila con scroll y sin weight: asi nunca se queda sin
            // ancho, pase lo que pase con los chips de al lado.
            TextButton(onClick = onNuevaSesion, enabled = nuevaSesionHabilitada) {
                Text("Nueva sesión", fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
        if (brain == "local") {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    aiState.ifBlank { "…" },
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f),
                )
                TextButton(onClick = onRefresh) { Text("↻", fontSize = 14.sp) }
                TextButton(onClick = onSleep, enabled = aiState.contains("despierta")) { Text("Dormir") }
            }
        } else if (brain == "terminal") {
            // Selector de interprete + recordatorio de que todo va como admin. El
            // comando lo escribe el usuario y corre directo (sin tarjeta): ver
            // brain_terminal.py.
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                FilterChip(
                    selected = shellTerminal == SHELL_POWERSHELL,
                    onClick = { onShellTerminal(SHELL_POWERSHELL) },
                    label = { Text("PowerShell") },
                )
                FilterChip(
                    selected = shellTerminal == SHELL_CMD,
                    onClick = { onShellTerminal(SHELL_CMD) },
                    label = { Text("cmd") },
                )
                Spacer(Modifier.weight(1f))
                Text(
                    "corre como admin",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
        } else if (brain == BRAIN_APP) {
            // Nada aqui: los mandos de la app son suyos y los pinta AppPanel,
            // justo debajo de esta barra. Poner un selector de modelo propio
            // seria inventarse un ajuste que esta app no tiene -- el modelo lo
            // elige la aplicacion del PC, con su propio boton.
            Unit
        } else {
            // La barra de tokens NUNCA se pliega: es lo unico de aqui que avisa
            // de un problema real (cuenta agotada), y esconderla escondería el
            // aviso justo cuando mas hace falta verlo. Modelo/Esfuerzo/Modo son
            // ajustes que se tocan de vez en cuando, no cada mensaje, y entre
            // los tres ocupan varias filas -- de ahi el plegado: mas chat
            // visible el resto del tiempo.
            TokenUsageBar(utilizacion)
            var mostrarOpciones by rememberSaveable { mutableStateOf(true) }
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 12.dp),
                horizontalArrangement = Arrangement.End,
            ) {
                TextButton(onClick = { mostrarOpciones = !mostrarOpciones }) {
                    Text(
                        if (mostrarOpciones) "Ocultar modelo/esfuerzo ▲" else "Modelo/esfuerzo ▼",
                        fontSize = 12.sp,
                    )
                }
            }
            if (mostrarOpciones) {
                ModeloEsfuerzoBar(modeloClaude, esfuerzoClaude, onModeloClaude, onEsfuerzoClaude)
                ModoClaudeBar(modoClaude, onModoClaude)
            }
        }
    }
}

/**
 * Cuánto se lleva gastado de la ventana de tokens de la CUENTA (no del gasto
 * del turno, ver ChatStore.ultimoLimiteConocido), en una banda de borde a
 * borde -- a diferencia de [LimiteBar], que solo aparece cuando hay un aviso,
 * esta se queda siempre que se conozca algún porcentaje, coloreada según lo
 * llena que esté.
 *
 * Siempre visible en el chat de Claude, coloreada según el nivel desde el
 * primer momento -- verde y vacía mientras no haya cifra. El PC solo manda el
 * porcentaje cuando el estado de la cuenta CAMBIA (ver brain_claude.ClaudeBrain)
 * y el CLI no lo emite por debajo del aviso: hasta entonces no hay número que
 * pintar, así que la barra se queda en 0% verde (que es la verdad: se ha
 * gastado poco) y se rellena en cuanto llega el dato real.
 */
@Composable
private fun TokenUsageBar(limite: ServerMsg.Limite?) {
    val pct = limite?.utilizacion
    val valor = pct ?: 0f
    val color = when {
        valor < 0.6f -> Color(0xFF4CAF50)
        valor < 0.85f -> Color(0xFFFFC107)
        else -> MaterialTheme.colorScheme.error
    }
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Text(
            // Sin cifra no se inventa un "0%" que parezca medido: se dice que
            // aún no hay dato. Con cifra, el porcentaje real y su etiqueta.
            if (pct != null) "${(pct * 100).toInt()}% — ${limite.etiqueta}"
            else "Tokens de la cuenta — aún sin datos",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 12.dp),
        )
        LinearProgressIndicator(
            progress = { valor.coerceIn(0f, 1f) },
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 2.dp)
                .height(6.dp),
            color = color,
            trackColor = MaterialTheme.colorScheme.surfaceVariant,
        )
    }
}

/**
 * Modelo y esfuerzo de Claude Code (ARQUITECTURA.md, protocolo v9). Mismo
 * lenguaje visual que [ModoClaudeBar] (FilterChip), pero en filas con scroll
 * horizontal: entre las 4 opciones de modelo y las 6 de esfuerzo no caben
 * fijas en el ancho de un móvil. El cambio se manda con el próximo mensaje
 * (ChatViewModel.setModeloClaude/setEsfuerzoClaude), no reconecta solo.
 */
@Composable
private fun ModeloEsfuerzoBar(
    modelo: String,
    esfuerzo: String,
    onModelo: (String) -> Unit,
    onEsfuerzo: (String) -> Unit,
) {
    Column(Modifier.fillMaxWidth().padding(top = 4.dp)) {
        Text(
            "Modelo",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Row(
            Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            listOf(
                MODELO_DEFECTO to "Automático",
                MODELO_SONNET to "Sonnet",
                MODELO_OPUS to "Opus",
                MODELO_HAIKU to "Haiku",
            ).forEach { (valor, etiqueta) ->
                FilterChip(
                    selected = modelo == valor,
                    onClick = { onModelo(valor) },
                    label = { Text(etiqueta, fontSize = 12.sp) },
                )
            }
        }
        Text(
            "Esfuerzo",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 4.dp),
        )
        Row(
            Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            listOf(
                ESFUERZO_DEFECTO to "Automático",
                ESFUERZO_LOW to "Bajo",
                ESFUERZO_MEDIUM to "Medio",
                ESFUERZO_HIGH to "Alto",
                ESFUERZO_XHIGH to "Extra",
                ESFUERZO_MAX to "Máximo",
            ).forEach { (valor, etiqueta) ->
                FilterChip(
                    selected = esfuerzo == valor,
                    onClick = { onEsfuerzo(valor) },
                    label = { Text(etiqueta, fontSize = 12.sp) },
                )
            }
        }
    }
}

/**
 * Ask / Auto / Plan, como en la app de escritorio (ARQUITECTURA.md seccion 9).
 * Vive junto al selector de cerebro porque es lo primero que hay que decidir
 * antes de escribir: si quieres ir aprobando cada tool o dejar que Claude corra
 * solo. El cambio se manda con el proximo mensaje (ChatViewModel.setModoClaude),
 * no reconecta ni corta el turno en marcha.
 */
@Composable
private fun ModoClaudeBar(modo: String, onModo: (String) -> Unit) {
    Row(
        Modifier.fillMaxWidth().padding(top = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        FilterChip(
            selected = modo == MODO_ASK,
            onClick = { onModo(MODO_ASK) },
            label = { Text("Preguntar", fontSize = 12.sp) },
        )
        FilterChip(
            selected = modo == MODO_AUTO,
            onClick = { onModo(MODO_AUTO) },
            label = { Text("Automático", fontSize = 12.sp) },
        )
        FilterChip(
            selected = modo == MODO_PLAN,
            onClick = { onModo(MODO_PLAN) },
            label = { Text("Plan", fontSize = 12.sp) },
        )
    }
}

@Composable
private fun Entry(
    item: Item,
    onInstallArtifact: (Item.Artifact) -> Unit,
    onAnswerQuestion: (String, Map<String, String>) -> Unit,
) {
    when (item) {
        is Item.Text -> Bubble(item)
        is Item.Sys -> Centered(item.text, MaterialTheme.colorScheme.onSurfaceVariant)
        is Item.ToolCall -> ToolCard(item.name, item.args, item.progreso)
        is Item.ToolResult -> ResultCard(item.name, item.text)
        is Item.Missing -> MissingCard(item.text)
        is Item.Question -> QuestionCard(item, onAnswerQuestion)
        is Item.Artifact -> ArtifactCard(item, onInstallArtifact)
    }
}

/** Cuantas lineas se ensenan de una burbuja antes de colapsarla tras "ver todo". */
private const val LINEAS_BURBUJA_CORTA = 12

/**
 * Azul de "esto lo decides tu", el mismo tipo de aviso que el rojo de admin en
 * [PermissionDialog]: un color que no existe en ninguna paleta del tema (ver
 * Theme.kt, ninguna de las dos tiene azul) para que no se confunda con nada
 * que ya signifique otra cosa.
 */
private val AzulPregunta = Color(0xFF1565C0)

@Composable
private fun Bubble(item: Item.Text) {
    val texto = item.text + if (item.streaming) "▌" else ""

    // Detectar "esto es una pregunta para ti" no tiene una señal del protocolo
    // -- Claude no manda "esto es una pregunta", solo texto -- asi que se usa
    // la pista mas fiable que hay: si termina en "?" es que el turno se para
    // ahi a esperar que decidas algo. No se aplica mientras streamea (el cursor
    // "▌" tapa el signo) ni a lo que escribes tu.
    val esPregunta = !item.mine && !item.streaming && texto.trimEnd().endsWith("?")

    // Burbujas largas (un plan, un resumen de varios pasos) se comian la
    // pantalla entera y empujaban el resto del chat fuera de vista. Mismo
    // patron que ResultCard: colapsada a las primeras lineas con un boton para
    // desplegar, nunca mientras sigue streameando (cortaria la respuesta en
    // marcha justo cuando mas hace falta verla crecer).
    var expandida by remember(item.key) { mutableStateOf(false) }
    val lineas = texto.lineSequence().count()
    val hayMas = !item.streaming && lineas > LINEAS_BURBUJA_CORTA
    val mostrado = if (hayMas && !expandida) {
        texto.lineSequence().take(LINEAS_BURBUJA_CORTA).joinToString("\n") + "…"
    } else texto

    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (item.mine) Arrangement.End else Arrangement.Start) {
        Card(
            colors = CardDefaults.cardColors(
                containerColor = when {
                    item.mine -> MaterialTheme.colorScheme.primaryContainer
                    esPregunta -> AzulPregunta
                    else -> MaterialTheme.colorScheme.surfaceVariant
                },
                contentColor = if (esPregunta) Color.White else MaterialTheme.colorScheme.onSurfaceVariant,
            ),
            shape = RoundedCornerShape(16.dp),
        ) {
            Column {
                Text(mostrado, Modifier.padding(12.dp), style = MaterialTheme.typography.bodyMedium)
                if (hayMas) {
                    TextButton(onClick = { expandida = !expandida }) {
                        Text(if (expandida) "menos" else "ver todo", fontSize = 11.sp)
                    }
                }
            }
        }
    }
}

/**
 * AskUserQuestion DENTRO del chat: burbuja azul (mismo [AzulPregunta] de "esto lo
 * decides tu") con las preguntas de Claude y sus opciones como botones. Al pulsar
 * se manda la etiqueta EXACTA de la opcion como respuesta (ver ChatStore.answerQuestion).
 *
 * OJO: la via VIVA de contestar es [QuestionDialog], el recuadro centrado que sale
 * por encima de todo mientras la pregunta esta sin responder (ver ChatStore.pregunta).
 * Esta burbuja queda como registro en el historial: mientras esta sin responder vive
 * detras del recuadro (no se llega a ella), y cuando contestas se queda con lo
 * elegido escrito ([item.respondido]) y los botones apagados. Se deja interactiva
 * por si algun dia no hubiera recuadro; answerQuestion ignora el segundo intento.
 *
 * Caso normal (una sola pregunta de opcion unica, que es lo que el prompt del PC
 * empuja): pulsar una opcion la contesta al momento. Con varias preguntas o con
 * multiSelect hace falta ir marcando y pulsar "Enviar", porque el PC espera una
 * respuesta por cada pregunta en un solo envio.
 *
 * [item.respondido] != null = ya contestada o caducada: se apagan los botones y se
 * deja escrito lo elegido, para que no la contestes dos veces.
 */
@Composable
private fun QuestionCard(item: Item.Question, onAnswer: (String, Map<String, String>) -> Unit) {
    val cerrada = item.respondido != null
    // indice de pregunta -> etiquetas elegidas. Un conjunto por si es multiSelect.
    val seleccion = remember(item.key) { mutableStateMapOf<Int, Set<String>>() }
    val unaSimple = item.questions.size == 1 && !item.questions.first().multiSelect

    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Start) {
        Card(
            colors = CardDefaults.cardColors(containerColor = AzulPregunta, contentColor = Color.White),
            shape = RoundedCornerShape(16.dp),
        ) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                item.questions.forEachIndexed { qi, q ->
                    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        if (q.header.isNotBlank()) {
                            Text(q.header.uppercase(), fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        }
                        Text(q.question, style = MaterialTheme.typography.bodyMedium)
                        if (q.multiSelect && !cerrada) {
                            Text("puedes elegir varias", fontSize = 10.sp)
                        }
                        q.options.forEach { op ->
                            val elegido = seleccion[qi]?.contains(op.label) == true
                            OpcionBoton(op.label, op.description, elegido, cerrada) {
                                if (cerrada) return@OpcionBoton
                                when {
                                    q.multiSelect -> {
                                        val actual = seleccion[qi].orEmpty()
                                        seleccion[qi] = if (op.label in actual) actual - op.label else actual + op.label
                                    }
                                    unaSimple -> onAnswer(item.reqId, mapOf(q.question to op.label))
                                    else -> seleccion[qi] = setOf(op.label)
                                }
                            }
                        }
                    }
                }

                when {
                    cerrada -> Text("→ ${item.respondido}", fontSize = 12.sp, fontWeight = FontWeight.Bold)
                    // Con una sola pregunta simple se contesta al pulsar, no hace falta Enviar.
                    !unaSimple -> {
                        val completo = item.questions.indices.all { seleccion[it]?.isNotEmpty() == true }
                        Button(
                            onClick = {
                                val ans = item.questions
                                    .mapIndexed { i, q -> q.question to seleccion[i].orEmpty().joinToString(", ") }
                                    .toMap()
                                onAnswer(item.reqId, ans)
                            },
                            enabled = completo,
                            colors = ButtonDefaults.buttonColors(
                                containerColor = Color.White,
                                contentColor = AzulPregunta,
                            ),
                        ) { Text("Enviar") }
                    }
                }
            }
        }
    }
}

/** Un boton de opcion dentro de [QuestionCard]. Blanco relleno = elegido; blanco
 * translucido = sin elegir. [descripcion] sale en pequeño si la hay. */
@Composable
private fun OpcionBoton(
    etiqueta: String,
    descripcion: String,
    elegido: Boolean,
    cerrada: Boolean,
    onClick: () -> Unit,
) {
    Button(
        onClick = onClick,
        enabled = !cerrada,
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(10.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = if (elegido) Color.White else Color.White.copy(alpha = 0.16f),
            contentColor = if (elegido) AzulPregunta else Color.White,
            disabledContainerColor = if (elegido) Color.White.copy(alpha = 0.85f) else Color.White.copy(alpha = 0.10f),
            disabledContentColor = if (elegido) AzulPregunta else Color.White.copy(alpha = 0.6f),
        ),
    ) {
        Column(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
            Text(etiqueta, fontSize = 14.sp, fontWeight = FontWeight.Bold)
            if (descripcion.isNotBlank()) {
                Text(descripcion, fontSize = 11.sp)
            }
        }
    }
}

/**
 * AskUserQuestion como recuadro CENTRADO por encima de todo, hermano de
 * [PermissionDialog] y por el MISMO motivo: una pregunta metida en la lista del
 * chat se va de la vista en cuanto llegan dos mensajes mas, y contestarla a
 * botonazos desde ahi no habia forma comoda. Aqui:
 *
 *  - va centrada y por encima de todo, en cualquier pestana en la que estes;
 *  - el alto esta topado (85% de pantalla) y lo largo hace scroll DENTRO;
 *  - el boton Enviar (cuando hace falta) vive fuera del scroll, siempre visible.
 *
 * No se cierra tocando fuera ni con Atras: una pregunta se contesta, no se
 * esquiva. Al pulsar se manda la etiqueta EXACTA de la opcion (ver
 * ChatStore.answerQuestion), que es la clave con la que el PC resuelve la tool.
 *
 * Caso normal (una sola pregunta de opcion unica, lo que empuja el prompt del
 * PC): pulsar una opcion la contesta al momento. Con varias preguntas o con
 * multiSelect hay que ir marcando y pulsar "Enviar", porque el PC espera una
 * respuesta por cada pregunta en un solo envio.
 *
 * En cuanto se contesta, [ChatStore.pregunta] pasa a null y este recuadro
 * desaparece; en el chat queda la burbuja ([QuestionCard]) con lo que elegiste.
 */
@Composable
private fun QuestionDialog(item: Item.Question, onAnswer: (String, Map<String, String>) -> Unit) {
    // indice de pregunta -> etiquetas elegidas. Un conjunto por si es multiSelect.
    val seleccion = remember(item.key) { mutableStateMapOf<Int, Set<String>>() }
    val unaSimple = item.questions.size == 1 && !item.questions.first().multiSelect
    val scroll = rememberScrollState()
    val maxAlto = (LocalConfiguration.current.screenHeightDp * 0.85f).dp

    Dialog(
        onDismissRequest = { /* a proposito: hay que elegir una opcion */ },
        properties = DialogProperties(dismissOnBackPress = false, dismissOnClickOutside = false),
    ) {
        Card(
            colors = CardDefaults.cardColors(containerColor = AzulPregunta, contentColor = Color.White),
            shape = RoundedCornerShape(16.dp),
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(max = maxAlto),
        ) {
            Column(Modifier.padding(16.dp)) {
                Text("Claude te pregunta", style = MaterialTheme.typography.labelMedium)

                // fill = false: si la pregunta es corta, el recuadro se encoge en
                // vez de estirarse hasta el tope.
                Column(
                    Modifier
                        .weight(1f, fill = false)
                        .verticalScroll(scroll)
                        .padding(vertical = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    item.questions.forEachIndexed { qi, q ->
                        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            if (q.header.isNotBlank()) {
                                Text(q.header.uppercase(), fontSize = 11.sp, fontWeight = FontWeight.Bold)
                            }
                            Text(q.question, style = MaterialTheme.typography.bodyMedium)
                            if (q.multiSelect) {
                                Text("puedes elegir varias", fontSize = 10.sp)
                            }
                            q.options.forEach { op ->
                                val elegido = seleccion[qi]?.contains(op.label) == true
                                OpcionBoton(op.label, op.description, elegido, cerrada = false) {
                                    when {
                                        q.multiSelect -> {
                                            val actual = seleccion[qi].orEmpty()
                                            seleccion[qi] =
                                                if (op.label in actual) actual - op.label else actual + op.label
                                        }
                                        // Una sola pregunta simple: se contesta al pulsar.
                                        unaSimple -> onAnswer(item.reqId, mapOf(q.question to op.label))
                                        else -> seleccion[qi] = setOf(op.label)
                                    }
                                }
                            }
                        }
                    }
                }

                // El Enviar vive FUERA del scroll para que se vea siempre. Solo
                // hace falta cuando no es una pregunta simple (varias, o multiSelect).
                if (!unaSimple) {
                    val completo = item.questions.indices.all { seleccion[it]?.isNotEmpty() == true }
                    Button(
                        onClick = {
                            val ans = item.questions
                                .mapIndexed { i, q -> q.question to seleccion[i].orEmpty().joinToString(", ") }
                                .toMap()
                            onAnswer(item.reqId, ans)
                        },
                        enabled = completo,
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = Color.White,
                            contentColor = AzulPregunta,
                        ),
                    ) { Text("Enviar") }
                }
            }
        }
    }
}

@Composable
private fun Centered(text: String, color: Color) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
        Text(text, style = MaterialTheme.typography.labelSmall, color = color)
    }
}

/**
 * [progreso] es la ULTIMA linea de estado que solto la tool, no un log: se
 * reescribe en el sitio segun van llegando tool_progress (ChatViewModel la
 * actualiza en la misma tarjeta). Antes de esto, entre esta tarjeta y el
 * resultado final habia silencio total -- en un build de varios minutos,
 * parecia un cuelgue.
 */
@Composable
private fun ToolCard(name: String, args: String, progreso: String) {
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.tertiaryContainer),
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(10.dp)) {
            Text("⚙ $name", fontWeight = FontWeight.Bold, fontSize = 13.sp, fontFamily = FontFamily.Monospace)
            if (args != "{}") {
                // Resumido, no el JSON crudo: un Edit de Claude trae el fichero
                // entero dentro y llenaba el chat de ruido ilegible.
                Text(resumeArgs(name, args), fontSize = 11.sp, fontFamily = FontFamily.Monospace)
            }
            if (progreso.isNotBlank()) {
                Text(
                    "… $progreso",
                    fontSize = 11.sp,
                    fontFamily = FontFamily.Monospace,
                    color = MaterialTheme.colorScheme.onTertiaryContainer,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }
        }
    }
}

/**
 * Fase 3: aviso de build_and_send (ARQUITECTURA.md seccion 6). El boton cambia
 * segun [Item.Artifact.state]: primer toque baja el APK y abre el instalador
 * del sistema; si el permiso "Instalar apps desconocidas" no esta activo
 * todavia, el ViewModel manda a Ajustes en vez de esto, y hay que volver a
 * tocar aqui despues.
 */
@Composable
private fun ArtifactCard(item: Item.Artifact, onInstall: (Item.Artifact) -> Unit) {
    val mb = item.size / 1024.0 / 1024.0

    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.tertiaryContainer),
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(10.dp)) {
            Text("⬇ ${item.name}", fontWeight = FontWeight.Bold, fontSize = 13.sp, fontFamily = FontFamily.Monospace)
            Text("%.1f MB".format(mb), fontSize = 11.sp, fontFamily = FontFamily.Monospace)

            when (val state = item.state) {
                is ArtifactState.Failed ->
                    Text(
                        "Fallo la descarga: ${state.reason}",
                        fontSize = 11.sp,
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.padding(top = 4.dp),
                    )
                // Barra DETERMINADA (bytes/total, viene de artifact.ready): a
                // diferencia de TurnoBar aqui si conocemos el tamano de antemano,
                // asi que un porcentaje real no miente. Si el pct aun no ha
                // llegado (primer instante) o el servidor no mando content-length,
                // se pinta indeterminada un momento en vez de nada -- que antes era
                // el bug: parecia colgada y solo era una build grande tardando.
                is ArtifactState.Downloading -> {
                    val pct = state.pct
                    if (pct != null) {
                        LinearProgressIndicator(
                            progress = { pct },
                            modifier = Modifier.fillMaxWidth().padding(top = 6.dp),
                        )
                        Text(
                            "${(pct * 100).toInt()}%",
                            fontSize = 11.sp,
                            fontFamily = FontFamily.Monospace,
                            modifier = Modifier.padding(top = 2.dp),
                        )
                    } else {
                        LinearProgressIndicator(modifier = Modifier.fillMaxWidth().padding(top = 6.dp))
                    }
                }
                else -> {}
            }

            Button(
                onClick = { onInstall(item) },
                enabled = item.state !is ArtifactState.Downloading,
                modifier = Modifier.padding(top = 6.dp),
            ) {
                Text(
                    when (item.state) {
                        is ArtifactState.Downloading -> "Descargando…"
                        is ArtifactState.Downloaded -> "Abrir instalador"
                        is ArtifactState.Failed -> "Reintentar"
                        ArtifactState.Ready -> "Instalar"
                    },
                )
            }
        }
    }
}

@Composable
private fun ResultCard(name: String, text: String) {
    var expanded by remember { mutableStateOf(false) }
    // Los logs de Gradle son enormes: colapsado por defecto, se abre si te interesa.
    val corto = text.lineSequence().take(3).joinToString("\n")
    val hayMas = text.lineSequence().count() > 3

    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(10.dp)) {
            Text("↳ $name", fontSize = 11.sp, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
            Text(
                if (expanded || !hayMas) text else corto,
                fontSize = 11.sp,
                fontFamily = FontFamily.Monospace,
            )
            if (hayMas) {
                TextButton(onClick = { expanded = !expanded }) {
                    Text(if (expanded) "menos" else "ver todo", fontSize = 11.sp)
                }
            }
        }
    }
}

/**
 * El aviso de la via cara (ARQUITECTURA.md seccion 8.2): lo que no se resuelve con un
 * comando. Lo que si, ya no llega hasta aqui — sale como run_shell con boton "Guardar".
 */
@Composable
private fun MissingCard(text: String) {
    Card(
        // Tampoco en rojo: "esto hay que programarlo" no es un peligro, es un
        // desvio hacia Claude Code. El rojo es solo para administrador.
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.tertiaryContainer),
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(12.dp)) {
            Text(text, style = MaterialTheme.typography.bodyMedium)
            Text(
                "Esto necesita escribir código, no un comando. En la Fase 2 este aviso llevará " +
                    "un botón para que lo escriba Claude Code.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onTertiaryContainer,
            )
        }
    }
}

/**
 * El permiso. Esta tarjeta es la frontera de seguridad entera (ARQUITECTURA.md
 * seccion 9): lo que lees aqui es exactamente lo que corre.
 *
 * Es un Dialog y no una tarjeta al final del chat, y eso es un arreglo, no un
 * capricho. Como tarjeta vivia dentro de la Column de la pantalla, asi que su alto
 * salia de su contenido: un `Edit` de Claude trae el fichero dentro de los args, la
 * tarjeta crecia mas que la pantalla, y empujaba fuera de la vista sus propios
 * botones y la caja de texto del chat. El permiso quedaba imposible de contestar y
 * la app entera, bloqueada. Ahora:
 *
 *  - va centrado y por encima de todo, no al final de un mensaje que puede no verse;
 *  - el alto esta topado (85% de pantalla) y lo largo hace scroll DENTRO del cuerpo;
 *  - los botones viven fuera de ese scroll, asi que se ven siempre, pase lo que pase;
 *  - los args se resumen (ver Args.kt) en vez de volcar el JSON crudo.
 *
 * No se cierra tocando fuera ni con Atras: un permiso se contesta, no se esquiva
 * -- y un despiste no debe valer como "si".
 *
 * "Guardar" ejecuta el comando Y lo congela como tool permanente (toolgen.py), asi
 * que la proxima vez no habra tarjeta: por eso el nombre es editable, y por eso el
 * comando se ensena igual de grande que en las otras dos opciones.
 */
@Composable
private fun PermissionDialog(p: Pending, onAnswer: (String, String) -> Unit) {
    // remember(p.reqId): si llega otro permiso, el nombre tecleado para el anterior
    // no debe quedarse pegado en el siguiente.
    var nombre by remember(p.reqId) { mutableStateOf(p.sugerencia) }
    val scroll = rememberScrollState()
    val maxAlto = (LocalConfiguration.current.screenHeightDp * 0.85f).dp
    val quien = if (p.brain == "claude") "Claude Code" else "La IA local"

    Dialog(
        onDismissRequest = { /* a proposito: hay que elegir Permitir o Denegar */ },
        properties = DialogProperties(dismissOnBackPress = false, dismissOnClickOutside = false),
    ) {
        Card(
            // Neutra si es un permiso normal; roja SOLO si va como administrador.
            //
            // Antes esta tarjeta era `errorContainer` -- rojo oscuro -- SIEMPRE, para
            // cualquier permiso. Como todo run_shell pide permiso, la pantalla que
            // veias era roja el 100% de las veces, asi que el rojo no significaba
            // nada. Y encima el aviso de administrador que se añadio era una banda
            // roja DENTRO de una tarjeta ya roja: rojo sobre rojo, imposible de
            // distinguir de un vistazo. La primera vez que se probo en el movil, la
            // reaccion fue exactamente esa ("¿es ilusion mia o todas salen rojas?").
            // Un color de alarma que sale siempre no es un color de alarma: es el
            // fondo. Ahora el rojo lo lleva una cosa y solo una.
            colors = CardDefaults.cardColors(
                containerColor = if (p.admin) MaterialTheme.colorScheme.errorContainer
                else MaterialTheme.colorScheme.surfaceVariant,
            ),
            shape = RoundedCornerShape(16.dp),
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(max = maxAlto),
        ) {
            Column(Modifier.padding(16.dp)) {
                Text("$quien pide permiso", style = MaterialTheme.typography.labelMedium)
                Text(p.name, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleMedium)

                // El aviso de administrador va ARRIBA y en rojo fuerte, antes del
                // comando y antes del scroll. Si estuviera debajo del contenido, un
                // comando largo lo dejaria fuera de la pantalla y aprobarias un
                // admin creyendo que era uno normal. Lo que distingue estas dos
                // tarjetas tiene que verse sin desplazar nada.
                if (p.admin) {
                    Card(
                        colors = CardDefaults.cardColors(containerColor = Color(0xFFB3261E)),
                        shape = RoundedCornerShape(8.dp),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 8.dp),
                    ) {
                        Column(Modifier.padding(10.dp)) {
                            Text(
                                "⚠ SE EJECUTA COMO ADMINISTRADOR",
                                color = Color.White,
                                fontWeight = FontWeight.Bold,
                                style = MaterialTheme.typography.labelLarge,
                            )
                            Text(
                                "Puede instalar, desinstalar y cambiar el sistema entero. " +
                                    "Lee el comando antes de aprobarlo.",
                                color = Color.White,
                                style = MaterialTheme.typography.labelSmall,
                            )
                        }
                    }
                }

                // fill = false: si el contenido es corto, el dialogo se encoge en vez
                // de quedarse estirado hasta el tope.
                Column(
                    Modifier
                        .weight(1f, fill = false)
                        .verticalScroll(scroll)
                        .padding(vertical = 8.dp),
                ) {
                    if (p.motivo.isNotBlank()) {
                        Text(p.motivo, style = MaterialTheme.typography.bodyMedium)
                    }
                    Text(
                        resumeArgs(p.name, p.args),
                        fontFamily = FontFamily.Monospace,
                        fontSize = 11.sp,
                        modifier = Modifier.padding(top = 6.dp),
                    )

                    if (p.savable) {
                        OutlinedTextField(
                            value = nombre,
                            onValueChange = { nombre = it },
                            label = { Text("Nombre si la guardas") },
                            singleLine = true,
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(top = 8.dp),
                        )
                        Text(
                            "Guardar = ejecutarlo ahora y dejarlo como herramienta fija. " +
                                "No volverá a pedir permiso, pero solo podrá correr este comando tal cual.",
                            style = MaterialTheme.typography.labelSmall,
                            modifier = Modifier.padding(top = 4.dp),
                        )
                    }
                }

                Row(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    // El boton tambien cambia, no solo el fondo: el color de la
                    // tarjeta se ve de reojo, pero el boton es lo que estas
                    // mirando cuando decides. Y dice "Permitir como ADMIN" con
                    // todas las letras, que no depende de distinguir dos rojos.
                    if (p.admin) {
                        Button(
                            onClick = { onAnswer("allow", "") },
                            colors = ButtonDefaults.buttonColors(
                                containerColor = Color(0xFFB3261E),
                                contentColor = Color.White,
                            ),
                        ) { Text("Permitir como ADMIN") }
                    } else {
                        Button(onClick = { onAnswer("allow", "") }) { Text("Permitir") }
                    }
                    OutlinedButton(onClick = { onAnswer("deny", "") }) { Text("Denegar") }
                    if (p.savable) {
                        Button(
                            onClick = { onAnswer("save", nombre.trim()) },
                            enabled = nombre.isNotBlank(),
                        ) { Text("Guardar") }
                    }
                }
            }
        }
    }
}

@Composable
private fun HostBar(
    host: String,
    state: Conn,
    onHostChange: (String) -> Unit,
    onConnect: () -> Unit,
    onDisconnect: () -> Unit,
    onReloadTools: () -> Unit,
) {
    Column(Modifier.padding(12.dp)) {
        OutlinedTextField(
            value = host,
            onValueChange = onHostChange,
            label = { Text("Host del PC (IP de Tailscale)") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = onConnect, enabled = state !is Conn.Online) { Text("Conectar") }
            TextButton(onClick = onDisconnect) { Text("Desconectar") }
            TextButton(onClick = onReloadTools, enabled = state is Conn.Online) { Text("Recargar tools") }
        }
        if (state is Conn.Failed) {
            Text(
                "Sin conexión: ${state.reason}",
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun StatusDot(state: Conn) {
    val color = when (state) {
        is Conn.Online -> Color(0xFF4CAF50)
        is Conn.Connecting -> Color(0xFFFFC107)
        is Conn.Failed -> MaterialTheme.colorScheme.error
        is Conn.Offline -> Color.Gray
    }
    Box(
        Modifier
            .padding(end = 4.dp)
            .size(10.dp)
            .clip(CircleShape)
            .background(color),
    )
}

/**
 * Log persistente en pantalla: no logcat. El movil no siempre esta enchufado a un
 * PC con adb, asi que el diagnostico tiene que quedarse dibujado y ser copiable.
 */
@Composable
private fun DebugPanel(lines: List<String>, onClear: () -> Unit) {
    val clipboard = LocalClipboardManager.current
    val listState = rememberLazyListState()

    LaunchedEffect(lines.size) {
        if (lines.isNotEmpty()) listState.animateScrollToItem(lines.lastIndex)
    }

    Column(
        Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 4.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Diagnóstico de conexión", style = MaterialTheme.typography.labelMedium)
            Row {
                TextButton(onClick = { clipboard.setText(AnnotatedString(lines.joinToString("\n"))) }) {
                    Text("Copiar")
                }
                TextButton(onClick = onClear) { Text("Limpiar") }
            }
        }
        LazyColumn(
            state = listState,
            modifier = Modifier
                .fillMaxWidth()
                .height(160.dp)
                .padding(horizontal = 12.dp),
        ) {
            items(lines) { line ->
                Text(
                    line,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 11.sp,
                    color = if ("FALLO" in line || "->" in line) MaterialTheme.colorScheme.error
                    else MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}
