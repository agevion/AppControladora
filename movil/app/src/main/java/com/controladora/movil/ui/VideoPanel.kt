package com.controladora.movil.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.calculatePan
import androidx.compose.foundation.gestures.calculateZoom
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.controladora.movil.net.Pantalla
import com.controladora.movil.net.Video
import kotlinx.coroutines.delay
import kotlin.math.max
import org.webrtc.EglBase
import org.webrtc.RendererCommon
import org.webrtc.SurfaceViewRenderer
import org.webrtc.VideoTrack

/** Cuanto se puede acercar la imagen del monitor (ver [gestosDeVideo]). */
private const val ZOOM_MAX = 4f

/**
 * La pantalla del PC, en vivo y a control remoto (v16, como un AnyDesk).
 *
 * Esto es el complemento del panel de arriba, no su sustituto: el chat y los
 * botones nativos son para lo que se puede leer y pulsar como texto; esto es
 * para lo que hay que **ver** — un artefacto, un diff, el navegador integrado,
 * cualquier ventana que haya en el escritorio, o simplemente comprobar que en
 * el PC está pasando lo que crees. A diferencia de antes (hasta v15, sólo la
 * ventana de la app de Claude), aquí se ve y se controla la pantalla que se
 * elija, con ratón y teclado de verdad.
 *
 * Se pide a mano y se suelta al salir, a propósito. Un vídeo permanente costaría
 * batería del móvil y CPU del PC (que está capturando y codificando a 30 fps)
 * todo el rato, para enseñar algo que la mayor parte del tiempo no se mira.
 */
@Composable
fun VideoPanel(
    estado: Video,
    egl: EglBase.Context?,
    pantalla: Pantalla?,
    pantallas: List<Pantalla>,
    online: Boolean,
    onVer: () -> Unit,
    onParar: () -> Unit,
    onElegirPantalla: (Pantalla) -> Unit,
    // El puntero sobre la imagen. Todo en fracciones del monitor, de 0 a 1:
    // ver [gestosDeVideo].
    onTocar: (Float, Float) -> Unit,
    onArrastrar: (Float, Float, Float, Float) -> Unit,
    onDesplazar: (Float, Float, Int) -> Unit,
    // "Copiar selección" (v15): Ctrl+C global. Ver el botón flotante más abajo,
    // que aparece justo tras una selección de verdad (mantener + arrastrar) y
    // desaparece con un toque o pasados unos segundos.
    onCopiarSeleccion: () -> Unit,
    // Teclado libre (v16, Fase E.2): [onEscribir] manda texto imprimible tal
    // cual se teclea, [onTecla] manda una tecla especial (Intro, Retroceso...).
    onEscribir: (String) -> Unit,
    onTecla: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    // Aparece exactamente cuando `onArrastrar` dispara por una selección real
    // (mantener pulsado + arrastrar, ver GestosVideo.decidir): el desplazamiento
    // normal usa `onDesplazar`, no este callback, así que no hay falsos
    // positivos por deslizar una lista.
    var mostrarCopiar by remember { mutableStateOf(false) }
    val onArrastrarInterno: (Float, Float, Float, Float) -> Unit = { fx, fy, fx2, fy2 ->
        mostrarCopiar = true
        onArrastrar(fx, fy, fx2, fy2)
    }
    val onTocarInterno: (Float, Float) -> Unit = { fx, fy ->
        // Un toque normal significa "ya no estoy seleccionando": si el botón
        // seguía puesto de una selección anterior, se quita solo.
        mostrarCopiar = false
        onTocar(fx, fy)
    }
    Column(modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp)) {
        // Los mandos de encender sólo se pintan cuando NO se está viendo: con el
        // vídeo en marcha ocuparían una fila entera para nada, y el de apagar va
        // ENCIMA de la imagen (ver más abajo), que es donde siempre se ve.
        if (estado !is Video.Viendo) {
            Row(
                Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                when (estado) {
                    is Video.Parado ->
                        OutlinedButton(onClick = onVer, enabled = online && pantalla != null) {
                            Text("Ver la pantalla")
                        }
                    is Video.Negociando -> {
                        CircularProgressIndicator(Modifier.padding(4.dp))
                        Text("conectando el vídeo…", style = MaterialTheme.typography.labelSmall)
                    }
                    is Video.Fallo -> {
                        OutlinedButton(onClick = onVer, enabled = online && pantalla != null) {
                            Text("Reintentar")
                        }
                        Text(
                            estado.motivo,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                    is Video.Viendo -> Unit
                }
                if (pantallas.size > 1) {
                    SelectorPantalla(pantalla, pantallas, onElegirPantalla)
                }
            }
        }

        if (estado is Video.Viendo) {
            // Ocupa TODO el hueco que le den, ni más ni menos. Nada de calcular
            // el alto a partir de la proporción: con `aspectRatio`, cuando el
            // alto no daba, Compose reajustaba por el otro lado y la SurfaceView
            // acababa ocupando la pantalla entera — tapando la fila de cerebros,
            // que es justo por donde se sale de aquí. Quien decide el hueco es
            // quien llama (ChatScreen le pasa el `weight`), y aquí sólo se
            // rellena: así no hay forma de comerse lo que no toca.
            // La pantalla del PC casi siempre es panorámica (un monitor) y el
            // móvil casi siempre está en vertical: con SCALE_ASPECT_FIT eso dejaba
            // una tira horizontal minúscula en medio de dos bandas negras enormes,
            // y no había forma de acercarse a leer nada. `escala`/`pan` son el
            // zoom con dos dedos que arregla eso (lo lleva [gestosDeVideo]);
            // arrancan en 1/cero y se reinician al apagar el vídeo o al pulsar
            // "Restablecer zoom".
            // Estados guardados como referencia (no sólo con `by`) para poder
            // pasárselos a [gestosDeVideo] tal cual: ese gesto vive dentro de un
            // `pointerInput(Unit)` que NO se reinicia en cada recomposición, así
            // que una lambda o un valor sueltos capturados ahí se quedarían con
            // la foto del primer frame. El objeto `MutableState` en cambio sigue
            // siendo el mismo de principio a fin; sólo cambia su `.value`.
            val escalaState = remember { mutableFloatStateOf(1f) }
            val panState = remember { mutableStateOf(Offset.Zero) }
            var escala by escalaState
            var pan by panState
            LaunchedEffect(estado) { escala = 1f; pan = Offset.Zero }
            var mostrarTeclado by remember { mutableStateOf(false) }

            Box(
                Modifier
                    .fillMaxSize()
                    .background(Color.Black),
            ) {
                // El vídeo y la capa táctil van JUNTOS dentro del mismo
                // `graphicsLayer`: así, cuando se acerca la imagen con el
                // pellizco, Compose deshace la transformación sola al convertir
                // un toque de pantalla a coordenada local -- gestosDeVideo sigue
                // viendo el mismo `size` de siempre y el tap cae en el sitio
                // correcto del monitor, acercada o no.
                Box(
                    Modifier
                        // La caja de la IMAGEN, con la proporción exacta del
                        // monitor y centrada en el hueco negro. Esto es lo que
                        // quita de en medio el problema que traía loco a todo
                        // esto: el renderizador de WebRTC NO hace letterbox
                        // dentro de su vista. `SCALE_ASPECT_FIT` sólo influye en
                        // su `onMeasure`, y en cuanto se le dan medidas exactas
                        // (`fillMaxSize`) recorta el fotograma para llenarlas.
                        //
                        // Se probaron las dos formas obvias y las dos fallan:
                        //  - `fillMaxWidth`: proporción correcta, pero la vista
                        //    queda ARRIBA de la caja y la capa táctil, que ocupa
                        //    la caja entera, calculaba las bandas centradas;
                        //  - `fillMaxSize`: vista = caja, y entonces recorta.
                        //
                        // Dándole la proporción del monitor, la vista y la
                        // imagen son el MISMO rectángulo: no hay bandas que
                        // deshacer y el gesto es una regla de tres directa (ver
                        // aFraccion). El hueco sobrante queda fuera, en negro, y
                        // ahí no hay nada que tocar.
                        .align(Alignment.Center)
                        .aspectRatio(pantalla?.let { it.ancho.toFloat() / it.alto } ?: (16f / 9f))
                        .graphicsLayer(
                            scaleX = escala,
                            scaleY = escala,
                            translationX = pan.x,
                            translationY = pan.y,
                            // `clip` vale FALSE por defecto en graphicsLayer, y
                            // dejarlo así fue un fallo de verdad: con la imagen
                            // acercada, todo lo de dentro de esta caja -- el
                            // vídeo Y la capa táctil -- se sale de sus límites y
                            // se dibuja y se toca ENCIMA del resto de la
                            // pantalla. O sea que al hacer zoom, la fila de
                            // cerebros y lo que hubiera alrededor dejaban de
                            // responder, porque los tapaba una capa invisible
                            // que ya no cabía en su sitio.
                            clip = true,
                        ),
                ) {
                    // El renderizador hace letterbox (SCALE_ASPECT_FIT): si la caja
                    // no cuadra exactamente, salen bandas negras — nunca una imagen
                    // deformada ni recortada por los bordes.
                    VistaWebRtc(estado.track, egl)

                    // La capa táctil va en su propia caja transparente ENCIMA del
                    // renderizador, y no como modificador de él: el renderizador
                    // es una `View` de Android metida con `AndroidView`, y poner
                    // los gestos ahí dependería de que esa View no se coma los
                    // toques, que no lo controlamos nosotros.
                    //
                    // **Una sola caja para los cuatro gestos**, zoom incluido. El
                    // pellizco tuvo un tiempo su propia caja `fillMaxSize` puesta
                    // encima de ésta, y el efecto fue que no funcionaba NADA de un
                    // dedo: entre hermanos que se solapan, Compose para el
                    // hit-testing en el primero que acierta, así que esta capa no
                    // recibía ni un toque. Lo cuenta con detalle el docstring de
                    // [gestosDeVideo]. No volver a partirla.
                    //
                    // Se pinta siempre, aunque `pantalla` sea null: sin ella no se
                    // puede situar un toque en el monitor, pero el zoom sigue
                    // teniendo sentido.
                    Box(
                        Modifier
                            .fillMaxSize()
                            .gestosDeVideo(
                                pantalla = pantalla,
                                onTocar = onTocarInterno,
                                onArrastrar = onArrastrarInterno,
                                onDesplazar = onDesplazar,
                                escalaState = escalaState,
                                panState = panState,
                                zoomMax = ZOOM_MAX,
                            ),
                    )
                }

                // Que se puede tocar la imagen no se ve por ningún sitio, y una
                // función que no se ve es una función que no existe. Se dice una
                // vez al encender el vídeo y se quita sola: un cartel permanente
                // encima de lo que has venido a mirar sería peor que el problema.
                //
                // Va ANTES que la fila de controles de más abajo (zoom, selector
                // de pantalla, teclado, cerrar) y con el ancho limitado a
                // propósito: Compose pinta los hijos de un Box en el orden en que
                // se declaran y el último tapa a los de antes, así que este
                // aviso -- de texto largo -- se comía la fila de controles
                // enteros mientras duraba, y ni se veían ni se podían tocar.
                if (pantalla != null && online) {
                    var pista by remember { mutableStateOf(true) }
                    LaunchedEffect(Unit) {
                        delay(6_000)
                        pista = false
                    }
                    if (pista) {
                        Text(
                            "toca = clic  ·  arrastra = desplazar  ·  mantén y arrastra = seleccionar",
                            Modifier
                                .align(Alignment.TopStart)
                                .fillMaxWidth(0.6f)
                                .padding(8.dp)
                                .background(
                                    MaterialTheme.colorScheme.surface.copy(alpha = 0.85f),
                                    RoundedCornerShape(12.dp),
                                )
                                .padding(horizontal = 8.dp, vertical = 4.dp),
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }

                // Apagar el vídeo, el selector de pantalla y el teclado van
                // ENCIMA de la imagen, no en una fila aparte. El vídeo es grande
                // y tapa lo que tenga debajo, así que un botón fuera de él acaba
                // escondido justo cuando hace falta. Sobre fondo propio, porque
                // encima de una captura clara no se leería.
                Row(
                    Modifier
                        .align(Alignment.TopEnd)
                        .padding(8.dp)
                        .background(
                            MaterialTheme.colorScheme.surface.copy(alpha = 0.85f),
                            RoundedCornerShape(16.dp),
                        )
                        .padding(horizontal = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    // El % de zoom sustituye a la resolución del monitor: la
                    // resolución es un dato para depurar, no algo que se use
                    // viendo el vídeo. El porcentaje sí — es la referencia de
                    // "cuánto he acercado" que tiene sentido tanto para quien
                    // mira como para quien lee un mensaje sobre ello. No hace
                    // falta que sea exacto al píxel: es `escala` tal cual,
                    // redondeada, sin pretender ser una medida de nada.
                    Text(
                        "${(escala * 100).toInt()}%",
                        Modifier.padding(start = 8.dp),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    // Solo aparece con zoom de verdad: un icono que casi nunca
                    // hace falta y sale siempre es sitio robado a "Dejar de ver".
                    if (escala > 1.01f) {
                        IconButton(onClick = { escala = 1f; pan = Offset.Zero }) {
                            Icon(Icons.Default.Refresh, contentDescription = "Restablecer zoom")
                        }
                    }
                    if (pantallas.size > 1) {
                        SelectorPantalla(pantalla, pantallas, onElegirPantalla)
                    }
                    IconButton(onClick = { mostrarTeclado = !mostrarTeclado }) {
                        // "⌨" y no un Icon vectorial a propósito: `Keyboard` no
                        // está en el set básico de Compose (como `RestartAlt`,
                        // ver el comentario de más arriba sobre el zoom), y no
                        // compensa tirar de material-icons-extended por uno.
                        Text("⌨", style = MaterialTheme.typography.titleMedium)
                    }
                    IconButton(onClick = onParar) {
                        Icon(Icons.Default.Close, contentDescription = "Dejar de ver")
                    }
                }

                // Sin conexión con el PC, tocar la imagen NO HACE NADA: el
                // gesto no sale del móvil. Pero el vídeo es P2P y sigue
                // pintando lo último que le llegó, así que la pantalla parece
                // viva y lo único que notas es que "no responde".
                //
                // Que eso no se avisara es el peor fallo que ha tenido esto:
                // aquí se decidió que los gestos no dijeran nada al fallar, para
                // no llenar el chat de ruido con cada muesca de scroll. La
                // consecuencia fue que un enlace caído se ve EXACTAMENTE igual
                // que un clic roto, y no hay forma de distinguirlos desde el
                // sofá. El aviso va aquí, encima de la imagen y mientras dure:
                // no es ruido en el chat, es el estado de lo que estás mirando.
                if (!online) {
                    Text(
                        "sin conexión con el PC — la imagen está congelada y los toques no llegan",
                        Modifier
                            .align(Alignment.BottomStart)
                            .padding(8.dp)
                            .background(
                                MaterialTheme.colorScheme.errorContainer,
                                RoundedCornerShape(12.dp),
                            )
                            .padding(horizontal = 8.dp, vertical = 4.dp),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onErrorContainer,
                    )
                }

                // "Copiar selección": aparece justo tras seleccionar texto de
                // verdad (mantener + arrastrar) y no antes, para no ocupar sitio
                // encima del vídeo el resto del tiempo. Se pinta en su propia
                // fila, algo más arriba del centro, para no montarse con el
                // teclado cuando los dos coinciden.
                if (mostrarCopiar) {
                    LaunchedEffect(mostrarCopiar) {
                        // Se apaga solo si nadie lo toca: un botón que se queda
                        // puesto para siempre encima de la imagen es peor que la
                        // molestia de tener que volver a seleccionar si tardas.
                        delay(8_000)
                        mostrarCopiar = false
                    }
                    Row(
                        Modifier
                            .align(Alignment.BottomEnd)
                            .padding(bottom = if (mostrarTeclado) 64.dp else 8.dp, end = 8.dp)
                            .background(MaterialTheme.colorScheme.primaryContainer, RoundedCornerShape(16.dp)),
                    ) {
                        TextButton(
                            onClick = {
                                mostrarCopiar = false
                                onCopiarSeleccion()
                            },
                        ) { Text("Copiar selección") }
                    }
                }

                // Teclado libre (v16, Fase E.2): una fila de texto encima del
                // vídeo. No sustituye al chat con Claude (eso sigue siendo la
                // pestaña de arriba) -- esto es para escribir en CUALQUIER sitio
                // de la pantalla que tenga el foco: un formulario web, una
                // barra de direcciones, lo que sea.
                if (mostrarTeclado) {
                    TecladoLibre(
                        Modifier.align(Alignment.BottomCenter),
                        onEscribir = onEscribir,
                        onTecla = onTecla,
                    )
                }
            }
        }
    }
}

/**
 * El selector de monitor: el nombre del que se está viendo, con un menú
 * desplegable para elegir otro. Sólo se pinta si hay más de uno -- con un
 * único monitor no hay nada que elegir y sería un botón que no hace nada.
 */
@Composable
private fun SelectorPantalla(
    actual: Pantalla?,
    pantallas: List<Pantalla>,
    onElegir: (Pantalla) -> Unit,
) {
    var abierto by remember { mutableStateOf(false) }
    Box {
        TextButton(onClick = { abierto = true }) {
            // "🖥" y no un Icon vectorial: `Monitor` tampoco está en el set
            // básico (ver el comentario del botón de teclado, más abajo).
            Text("🖥 ${actual?.nombre ?: "pantalla"}", style = MaterialTheme.typography.labelSmall)
        }
        DropdownMenu(expanded = abierto, onDismissRequest = { abierto = false }) {
            pantallas.forEach { p ->
                DropdownMenuItem(
                    text = { Text(if (p.principal) "${p.nombre} (principal)" else p.nombre) },
                    onClick = {
                        abierto = false
                        onElegir(p)
                    },
                )
            }
        }
    }
}

/**
 * La fila de teclado libre sobre el vídeo (v16, Fase E.2).
 *
 * No hay teclado propio dibujado a mano: se apoya en el `OutlinedTextField` y
 * el teclado del sistema de Android, y sólo reenvía lo que se teclea ahí. Cada
 * carácter NUEVO se manda en cuanto aparece (comparando contra el valor
 * anterior) y el campo se vacía justo después -- así el texto nunca se
 * acumula ni hay que "enviarlo" aparte, es transparente como escribir
 * directamente en el PC. Un borrado se manda como la tecla Retroceso, no como
 * texto: es lo que espera cualquier campo del otro lado.
 */
@Composable
private fun TecladoLibre(
    modifier: Modifier = Modifier,
    onEscribir: (String) -> Unit,
    onTecla: (String) -> Unit,
) {
    var texto by remember { mutableStateOf("") }
    Row(
        modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.95f))
            .padding(8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        OutlinedTextField(
            value = texto,
            onValueChange = { nuevo ->
                when {
                    nuevo.length > texto.length && nuevo.startsWith(texto) ->
                        onEscribir(nuevo.substring(texto.length))
                    nuevo.length < texto.length ->
                        repeat(texto.length - nuevo.length) { onTecla("retroceso") }
                    nuevo != texto -> {
                        // Autocompletado/predictivo que sustituye el texto entero
                        // (no es un simple "se añadió al final"): más simple y
                        // fiable mandarlo tal cual que intentar adivinar el diff.
                        onEscribir(nuevo)
                    }
                }
                texto = nuevo
            },
            modifier = Modifier.fillMaxWidth().weight(1f),
            placeholder = { Text("Escribe en el PC…") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
            keyboardActions = KeyboardActions(onSend = { onTecla("intro"); texto = "" }),
        )
        IconButton(onClick = { onTecla("intro") }) {
            Text("⏎", style = MaterialTheme.typography.titleMedium)
        }
    }
}

/**
 * El `SurfaceViewRenderer` de WebRTC dentro de Compose.
 *
 * `DisposableEffect` no es adorno: si la pista no se desengancha al salir de la
 * pantalla, el renderizador sigue recibiendo fotogramas de una superficie que ya
 * no existe. Eso son fugas de memoria nativa y, en algunos móviles, un cierre
 * en seco sin traza que lo explique.
 */
@Composable
private fun VistaWebRtc(track: VideoTrack, egl: EglBase.Context?) {
    if (egl == null) return
    // La vista creada, para poder engancharle y desengancharle la pista desde un
    // efecto en vez de desde `update` (ver más abajo).
    var renderizador by remember { mutableStateOf<SurfaceViewRenderer?>(null) }
    AndroidView(
        // `fillMaxSize` y NO `fillMaxWidth`, y esto es lo que hacía que no
        // funcionara clicar. Con `fillMaxWidth` la vista sólo es tan alta como
        // la imagen, así que el renderizador la coloca ARRIBA de la caja y el
        // negro queda todo debajo. La capa de gestos, en cambio, ocupa la caja
        // entera y calcula el letterbox suponiendo que la imagen está CENTRADA
        // (media banda arriba, media abajo), que es lo que hace
        // SCALE_ASPECT_FIT dentro de sus propios límites.
        //
        // Las dos cuentas no cuadraban: los toques del tercio de arriba de la
        // imagen daban fracción NEGATIVA y se descartaban en silencio -- no
        // pasaba nada -- y los de más abajo caían desplazados hacia arriba. Se
        // veía exactamente como "los clics no funcionan".
        //
        // Ocupando toda la caja, los límites del renderizador y los de la capa
        // táctil son el mismo rectángulo, y entonces sí: lo que centra el
        // renderizador es lo que descentra la cuenta. No volver a poner
        // `fillMaxWidth` aquí sin arreglar también [aFraccion].
        modifier = Modifier.fillMaxSize(),
        factory = { ctx ->
            SurfaceViewRenderer(ctx).apply {
                init(egl, null)
                // FIT y no FILL: la pantalla entera tiene que caber. Recortar los
                // bordes de un escritorio es perder justo la barra de tareas o la
                // ventana que está tocando el borde.
                setScalingType(RendererCommon.ScalingType.SCALE_ASPECT_FIT)
                // Hardware scaler DESACTIVADO, y no por rendimiento sino por
                // geometría. Activado, el renderizador llama a `setFixedSize` y
                // redimensiona la SUPERFICIE al tamaño del vídeo escalado, así
                // que lo que se pinta dentro de la vista deja de coincidir con
                // el rectángulo de la vista. La capa de gestos calcula el
                // letterbox a partir de ESE rectángulo, o sea que en cuanto los
                // dos dejan de ser lo mismo, los toques caen desplazados.
                // Apagado, el renderizador dibuja la imagen centrada dentro de
                // sus límites -- exactamente lo que supone [aFraccion].
                setEnableHardwareScaler(false)
                renderizador = this
            }
        },
        // `update` corre en CADA recomposición, y aquí había un `addSink` suelto:
        // o sea que cada vez que cambiaba cualquier cosa de la pantalla (el
        // estado de la app llega cada pocos segundos) se volvía a enganchar la
        // misma pista al mismo renderizador. `addSink` no es idempotente al otro
        // lado del JNI: se acumulan entregas del mismo fotograma, que es trabajo
        // de GPU y de batería tirado, y deja tantos enganches vivos como
        // recomposiciones hubo -- de los que `removeSink` sólo quita uno.
        //
        // Engancharse es un efecto, no parte de pintar, así que va en un
        // DisposableEffect con la pista y la vista como claves: una sola vez
        // mientras las dos sean las mismas, y se suelta al cambiar cualquiera.
        update = { },
        onRelease = { vista -> vista.release() },
    )

    DisposableEffect(track, renderizador) {
        val vista = renderizador
        if (vista != null) track.addSink(vista)
        onDispose { if (vista != null) track.removeSink(vista) }
    }
}
