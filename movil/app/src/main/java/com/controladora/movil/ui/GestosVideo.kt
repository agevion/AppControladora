package com.controladora.movil.ui

import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.calculateCentroid
import androidx.compose.foundation.gestures.calculatePan
import androidx.compose.foundation.gestures.calculateZoom
import androidx.compose.runtime.Composable
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.AwaitPointerEventScope
import androidx.compose.ui.input.pointer.PointerId
import androidx.compose.ui.input.pointer.PointerInputChange
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChangeIgnoreConsumed
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import com.controladora.movil.net.Pantalla
import kotlin.math.abs
import kotlin.math.max

/**
 * Tocar la pantalla del PC directamente sobre el vídeo (v16, antes Fase E.1
 * pero atada a la ventana de Claude).
 *
 * Del móvil también se pueden pulsar los botones que el PC sabe nombrar
 * (`app.press`, para la app de Claude). Esto es lo otro, y ahora es genérico:
 * clicar un enlace, seleccionar texto arrastrando, desplazar una lista —
 * cualquier sitio de la pantalla, cualquier ventana que haya ahí, la conozca
 * el PC o no.
 *
 * **Lo que se manda son FRACCIONES del monitor (0 a 1), no píxeles.** El
 * porqué está en `protocol.SCREEN_TAP` del PC, y se resume en que
 * `screens.result` es una foto que se pide una vez, no en cada gesto. Con
 * fracciones, el PC las resuelve contra el rectángulo real del monitor en el
 * instante del gesto y las recorta, así que un toque no puede salirse de la
 * pantalla.
 *
 * **Los tres gestos, con un dedo**, como en cualquier cliente de escritorio remoto
 * táctil:
 * - **tocar** → clic;
 * - **arrastrar** → desplazar (es lo que espera la mano sobre una pantalla);
 * - **mantener pulsado y luego arrastrar** → arrastrar de verdad: seleccionar
 *   texto, mover algo. Avisa con una vibración, porque un modo en el que entras
 *   sin enterarte es un modo que usarás sin querer.
 *
 * Y con **dos dedos**, el zoom sobre la imagen.
 *
 * **Los cuatro gestos viven en UN SOLO `pointerInput`, y eso no es una cuestión
 * de orden.** El zoom estuvo un tiempo en su propia caja `fillMaxSize` puesta
 * encima de ésta, y el resultado fue que no funcionaba **nada** de un dedo: ni
 * tocar, ni desplazar, ni seleccionar. Cuando dos hermanos se solapan, Compose
 * recorre los hijos en orden inverso de dibujado y **para en el primero que
 * acierta** — no reparte el evento entre los dos. Una caja de arriba a abajo con
 * `pointerInput` acierta en toda la superficie, así que la capa de debajo no
 * recibía ni un toque; no es que se los consumiera, es que nunca se los
 * mandaban. Dos detectores solapados no se coordinan cediéndose el turno: sólo
 * existe el de arriba. Por eso arbitra uno solo, aquí, contando dedos.
 */

/** Cuánto dedo cuesta una muesca de rueda. Medido a ojo contra lo que desplaza
 * una muesca en la app: más corto y el desplazamiento se vuelve nervioso, más
 * largo y hay que barrer la pantalla entera para bajar un párrafo. */
private val PX_POR_MUESCA = 42.dp

/**
 * Reparte los toques de esta zona entre `screen.tap`, `screen.drag` y `screen.scroll`.
 *
 * [pantalla] es el rectángulo del monitor que se está viendo; con `null` no se
 * hace nada (sin él no se sabe qué proporción tiene la imagen, y sin la
 * proporción no se puede deshacer el letterbox — ver [aFraccion]).
 *
 * Las coordenadas de los callbacks van todas en fracciones de 0 a 1.
 */
@Composable
fun Modifier.gestosDeVideo(
    pantalla: Pantalla?,
    onTocar: (Float, Float) -> Unit,
    onArrastrar: (Float, Float, Float, Float) -> Unit,
    onDesplazar: (Float, Float, Int) -> Unit,
    // El zoom vive aquí dentro y no en una caja aparte: ver el docstring de
    // arriba, que explica por qué separarlo dejaba el resto sin funcionar.
    escalaState: MutableState<Float>,
    panState: MutableState<Offset>,
    zoomMax: Float,
): Modifier {
    val haptica = LocalHapticFeedback.current
    // Todo por `rememberUpdatedState` y `pointerInput(Unit)`: si se pusiera
    // `pantalla` como clave, cada monitor nuevo que llegue de la lista (aunque
    // sea el mismo) reiniciaría el detector — y hacerlo a media pulsación larga
    // significa perder el gesto justo cuando el dedo ya está esperando la
    // vibración.
    val ven = rememberUpdatedState(pantalla)
    val tocar = rememberUpdatedState(onTocar)
    val arrastrar = rememberUpdatedState(onArrastrar)
    val desplazar = rememberUpdatedState(onDesplazar)

    return this.pointerInput(Unit) {
        val pxPorMuesca = PX_POR_MUESCA.toPx()

        awaitEachGesture {
            val abajo = awaitFirstDown(requireUnconsumed = false)
            val rect = ven.value
            // Puede salir `null`, y no se sale por eso: el dedo cayó en la banda
            // negra (sobre la banda no hay ventana que tocar, y recortarlo al
            // borde sería clicar en el filo sin que nadie lo pida), o todavía no
            // se sabe qué proporción tiene la imagen. Con un dedo eso no es nada
            // que mandar al PC — pero un pellizco que EMPIEZA ahí sigue siendo un
            // pellizco, así que hay que seguir escuchando.
            val origen = rect?.let { aFraccion(abajo.position, size, it) }
            abajo.consume()

            var ultimo = abajo.position

            // --- ¿qué gesto es? -------------------------------------------
            // Se levanta pronto y sin moverse -> tocar.
            // Se mueve más que el `touchSlop`  -> desplazar.
            // Ni una cosa ni la otra a tiempo  -> pulsación larga: arrastrar.
            val decision = withTimeoutOrNull(viewConfiguration.longPressTimeoutMillis) {
                decidir(abajo.id, abajo.position, viewConfiguration.touchSlop) { ultimo = it }
            }

            when {
                // Dos dedos: es un zoom, y a partir de aquí el gesto entero es
                // suyo. Va lo primero porque manda sobre todo lo demás.
                decision == Decision.PELLIZCO ->
                    pellizcar(escalaState, panState, zoomMax, size)

                // El dedo desapareció sin levantarse (otra vista se llevó el
                // gesto, o el sistema lo canceló). No es ni un toque ni un
                // arrastre: no se manda nada.
                decision == Decision.CANCELADO -> Unit

                // Un dedo sobre la banda negra, o sin saber aún la proporción de
                // la imagen: no hay punto de la ventana del PC que mandar.
                origen == null -> Unit

                decision == Decision.TOCAR -> tocar.value(origen.x, origen.y)

                decision == Decision.DESPLAZAR -> {
                    var resto = ultimo.y - abajo.position.y
                    var emitidas = 0
                    val fin = seguir(abajo.id, abajo.position) { p ->
                        resto += p.positionChangeIgnoreConsumed().y
                        // Se emite cada vez que el dedo cruza una muesca, no al
                        // final: desplazar tiene que ir siguiendo al dedo. El
                        // resto se guarda, así un barrido largo no pierde nada
                        // por el camino.
                        val muescas = (resto / pxPorMuesca).toInt()
                        if (muescas != 0) {
                            resto -= muescas * pxPorMuesca
                            // Dedo hacia ABAJO = hacia el principio del
                            // documento = muescas positivas, igual que empujar
                            // la rueda de un ratón hacia delante.
                            desplazar.value(origen.x, origen.y, muescas)
                            emitidas += muescas
                        }
                    }
                    // `null` = apareció un segundo dedo a mitad del barrido: eso
                    // es un pellizco, no un desplazamiento. Ni se manda la muesca
                    // de propina de aquí abajo, ni se pierde el zoom: el gesto
                    // sigue vivo y pasa a ser suyo.
                    if (fin == null) {
                        pellizcar(escalaState, panState, zoomMax, size)
                    } else {
                        // Un barrido que se pasa del slop pero no llega a una
                        // muesca entera se quedaría en NADA, y un gesto que no
                        // hace nada se lee como que la app se ha colgado. Se
                        // cuenta como una, en el sentido que llevara.
                        //
                        // La condición es `emitidas == 0` y no "el recorrido total
                        // es menor que una muesca": bajar 50 px y volver a subir
                        // 45 deja un recorrido neto pequeño, pero por el camino YA
                        // se emitió una muesca, y sumar otra aquí sería contarla
                        // dos veces.
                        val recorrido = fin.y - abajo.position.y
                        if (emitidas == 0 && abs(recorrido) > viewConfiguration.touchSlop) {
                            desplazar.value(origen.x, origen.y, if (recorrido > 0) 1 else -1)
                        }
                    }
                }

                // decision == null: se agotó el tiempo sin decidirse, o sea
                // pulsación larga.
                else -> {
                    haptica.performHapticFeedback(HapticFeedbackType.LongPress)
                    val fin = seguir(abajo.id, abajo.position) { }
                    // `fin == null`: un segundo dedo interrumpió la pulsación
                    // larga -- era un pellizco, no una selección -- así que no se
                    // manda ni arrastre ni el toque de "no se movió".
                    if (fin == null) {
                        pellizcar(escalaState, panState, zoomMax, size)
                    } else {
                        // El extremo final SÍ se recorta en vez de descartarse: si
                        // has arrastrado hasta salirte de la imagen es que querías
                        // llegar al borde, igual que en cualquier selección de texto.
                        val destino = aFraccionRecortada(fin, size, rect)
                        if (destino != null && (destino - origen).getDistance() > 0.001f) {
                            arrastrar.value(origen.x, origen.y, destino.x, destino.y)
                        } else {
                            // Mantener pulsado y soltar sin mover no es un arrastre
                            // de cero píxeles: es un clic que se ha quedado quieto.
                            tocar.value(origen.x, origen.y)
                        }
                    }
                }
            }
        }
    }
}

private enum class Decision { TOCAR, DESPLAZAR, PELLIZCO, CANCELADO }

/**
 * El zoom con dos dedos, hasta que quede menos de dos en la pantalla.
 *
 * [caja] es el tamaño de esta capa SIN transformar, que es en lo que se miden
 * los límites del desplazamiento: pasado ese margen la imagen se saldría de la
 * caja sin forma de traerla de vuelta salvo con "Restablecer zoom".
 */
private suspend fun AwaitPointerEventScope.pellizcar(
    escalaState: MutableState<Float>,
    panState: MutableState<Offset>,
    zoomMax: Float,
    caja: IntSize,
) {
    // El pivote de `graphicsLayer` es el centro de la caja (el valor por
    // defecto de `transformOrigin`): `scaleX`/`scaleY` escalan alrededor de
    // este punto, y `translationX`/`translationY` se suman después, ya en
    // píxeles de pantalla. Hace falta este punto para deshacer ese pivote más
    // abajo.
    val centroCaja = Offset(caja.width / 2f, caja.height / 2f)
    while (true) {
        val ev = awaitPointerEvent()
        if (ev.changes.count { it.pressed } < 2) return
        val vieja = escalaState.value
        val nueva = (vieja * ev.calculateZoom()).coerceIn(1f, zoomMax)
        escalaState.value = nueva

        val limiteX = max(0f, (nueva - 1f) * caja.width / 2f)
        val limiteY = max(0f, (nueva - 1f) * caja.height / 2f)
        // `calculatePan` llega en coordenadas LOCALES, o sea ya divididas por la
        // escala: esta capa vive DENTRO del `graphicsLayer` del zoom, y Compose
        // deshace la transformación al convertir el toque a coordenada local
        // (que es justo lo que hace que un toque caiga en el sitio correcto de
        // la ventana del PC esté acercada o no). Pero el desplazamiento del
        // layer se mide en píxeles de pantalla, así que hay que volver a
        // multiplicar. Sin esto, con la imagen al triple, arrastrar la movería a
        // un tercio de la velocidad del dedo.
        //
        // `graphicsLayer` escala siempre desde el CENTRO de la caja: sin nada
        // más, cada muesca de zoom recentraría la imagen aunque los dedos
        // estén en una esquina, y el punto que querías mirar se te escaparía
        // hacia el medio de la pantalla. `ancla` es dónde caen los dedos
        // respecto a ese centro (en las mismas coordenadas de contenido que
        // ya llegan deshechas); multiplicado por lo que ha cambiado la escala
        // da justo el `pan` de más que hace falta para que el punto bajo los
        // dedos se quede quieto en la pantalla mientras la imagen crece o
        // encoge a su alrededor.
        val ancla = ev.calculateCentroid(useCurrent = true) - centroCaja
        val nuevoPan = panState.value + ev.calculatePan() * nueva + ancla * (vieja - nueva)
        panState.value = Offset(
            nuevoPan.x.coerceIn(-limiteX, limiteX),
            nuevoPan.y.coerceIn(-limiteY, limiteY),
        )
        ev.changes.forEach { it.consume() }
    }
}

/**
 * Espera a que el gesto se declare: levantar el dedo (tocar) o pasarse del
 * [slop] (desplazar). Si no hace ninguna de las dos, quien llama lo corta por
 * tiempo y eso es la pulsación larga.
 *
 * Se sigue **el mismo puntero** que empezó el gesto ([id]) y no "el primero de
 * la lista": con un segundo dedo en la pantalla, mirar el primero que venga hace
 * que el gesto salte de un dedo a otro a mitad.
 */
private suspend fun AwaitPointerEventScope.decidir(
    id: PointerId,
    origen: Offset,
    slop: Float,
    onMovido: (Offset) -> Unit,
): Decision {
    while (true) {
        val ev = awaitPointerEvent()
        // Un segundo dedo en pantalla es un pellizco de zoom, no un gesto sobre
        // el PC: se declara aquí mismo, antes de que el movimiento del primer
        // dedo durante el pellizco se lea como un arrastre o un scroll que nadie
        // ha pedido.
        if (ev.changes.count { it.pressed } > 1) return Decision.PELLIZCO
        // Que nuestro puntero no venga en el evento significa que ya no existe:
        // el gesto se canceló. Seguir esperándolo aquí sería quedarse colgado
        // hasta que salte el tiempo de la pulsación larga, y entonces mandar un
        // arrastre que nadie ha hecho.
        val p = ev.changes.firstOrNull { it.id == id } ?: return Decision.CANCELADO
        p.consume()
        if (!p.pressed) return Decision.TOCAR
        if ((p.position - origen).getDistance() > slop) {
            onMovido(p.position)
            return Decision.DESPLAZAR
        }
    }
}

/**
 * Sigue el puntero [id] hasta que se levante, llamando a [enCadaPaso] por el
 * camino. Devuelve dónde acabó, o `null` si a mitad apareció un segundo dedo
 * (pellizco de zoom, ver VideoPanel.pellizcoZoom): quien llama tiene que saber
 * distinguir "no se movió" de "esto ya no es el gesto que creía seguir", porque
 * lo primero puede seguir siendo un toque válido y lo segundo no es nada.
 *
 * [inicio] no es un valor por defecto cualquiera: es lo que se usa si el
 * puntero desaparece sin llegar a levantarse. Con `Offset.Zero` en su lugar, un
 * arrastre cancelado acabaría mandando un arrastre hasta la esquina superior
 * izquierda de la ventana — una selección enorme que nadie ha pedido.
 */
private suspend fun AwaitPointerEventScope.seguir(
    id: PointerId,
    inicio: Offset,
    enCadaPaso: (PointerInputChange) -> Unit,
): Offset? {
    var ultimo = inicio
    while (true) {
        val ev = awaitPointerEvent()
        if (ev.changes.count { it.pressed } > 1) return null
        val p = ev.changes.firstOrNull { it.id == id } ?: return ultimo
        ultimo = p.position
        if (!p.pressed) {
            p.consume()
            return ultimo
        }
        enCadaPaso(p)
        p.consume()
    }
}

/**
 * Punto de la vista -> fracción del monitor, deshaciendo el letterbox.
 * `null` si cae en la banda negra.
 *
 * El renderizador va en `SCALE_ASPECT_FIT` (ver [VideoPanel]), o sea que casi
 * siempre sobra hueco por arriba y abajo o por los lados. Dividir el toque entre
 * el tamaño de la vista da un punto desplazado, y cuanto peor cuadre la caja,
 * más.
 *
 * La proporción del vídeo **es** la de [pantalla] porque `webrtc.py` escala
 * conservándola, así que con eso basta para reconstruir el rectángulo dibujado y
 * sus bandas — sin preguntarle nada al decodificador ni saber a qué tamaño se
 * está emitiendo.
 */
private fun aFraccion(p: Offset, vista: IntSize, pantalla: Pantalla): Offset? {
    val f = sinRecortar(p, vista, pantalla) ?: return null
    return if (f.x < 0f || f.x > 1f || f.y < 0f || f.y > 1f) null else f
}

/** Igual, pero un punto de fuera se pega al borde en vez de descartarse. */
private fun aFraccionRecortada(p: Offset, vista: IntSize, pantalla: Pantalla): Offset? {
    val f = sinRecortar(p, vista, pantalla) ?: return null
    return Offset(f.x.coerceIn(0f, 1f), f.y.coerceIn(0f, 1f))
}

private fun sinRecortar(p: Offset, vista: IntSize, pantalla: Pantalla): Offset? {
    if (vista.width <= 0 || vista.height <= 0) return null
    if (pantalla.ancho <= 0 || pantalla.alto <= 0) return null
    // Una regla de tres y ya está: [vista] ES la imagen, sin bandas.
    //
    // Aquí había antes una cuenta de letterbox (calcular la escala, el
    // rectángulo dibujado y media banda a cada lado). Sobraba, y encima estaba
    // mal: daba por hecho que el renderizador centra la imagen dentro de su
    // vista, y no lo hace -- recorta el fotograma para llenarla. Medido en el
    // móvil: con la vista a 1356x2079 y la ventana a 1874x1096, la cuenta situaba
    // la imagen en local y 643..1436 mientras el renderizador la pintaba de 0 a
    // 2079. Los toques de la mitad de arriba daban fracción negativa y se
    // descartaban en silencio: "los clics no funcionan".
    //
    // Ahora quien pone la proporción es el layout (`aspectRatio` en VideoPanel),
    // así que vista e imagen son el mismo rectángulo por construcción y no hay
    // nada que deshacer. Si alguien quita ese `aspectRatio`, esto vuelve a estar
    // mal -- por eso están comentados el uno al otro.
    return Offset(p.x / vista.width, p.y / vista.height)
}
