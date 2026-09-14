package com.controladora.movil.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.controladora.movil.net.ServerMsg
import com.controladora.movil.net.SesionApp

/**
 * El mando de la aplicacion de escritorio de Claude que corre en el PC.
 *
 * Esta pestana NO es un chat con otra IA: lo que escribes se teclea en el
 * compositor de esa aplicacion y lo que ves contestar lo contesta ella. Por eso
 * aqui no hay selector de modelo ni de esfuerzo propios -- los de verdad son los
 * botones de la app, y se pulsan tal cual con [onPulsar].
 *
 * La idea de fondo, y por lo que esto no es un AnyDesk: AnyDesk manda pixeles del
 * PC entero y te obliga a apuntar con el dedo a una interfaz de escritorio. Aqui
 * cada cosa que ves es un control nativo del movil que sabe lo que hace, y el
 * texto es texto de verdad (seleccionable, con el teclado del movil y su
 * dictado), no una imagen escalada.
 *
 * Nada de lo que hay aqui afirma nada por su cuenta: cada boton manda su orden y
 * lo que se repinta es el estado que el PC devuelve despues de leer la app. Si
 * pulsas "Opus 5" y la app no cambia, aqui tampoco cambia.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppPanel(
    estado: ServerMsg.AppState?,
    sesionElegida: String,
    online: Boolean,
    onAbrirSesion: (String) -> Unit,
    onNueva: () -> Unit,
    onPulsar: (String) -> Unit,
    onParar: () -> Unit,
    onRefrescar: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp)) {
        when {
            !online -> Card(
                Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer),
            ) {
                Text(
                    "Sin conexión con el PC: no se puede ver ni manejar la app.",
                    Modifier.padding(10.dp),
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            estado == null -> Text(
                "Leyendo la app del PC…",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            !estado.abierta -> AppCerrada(onAbrir = { onAbrirSesion("") })
            else -> AppAbierta(
                estado = estado,
                sesionElegida = sesionElegida,
                onAbrirSesion = onAbrirSesion,
                onNueva = onNueva,
                onPulsar = onPulsar,
                onParar = onParar,
                onRefrescar = onRefrescar,
            )
        }
    }
}

@Composable
private fun AppCerrada(onAbrir: () -> Unit) {
    Card(
        Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(
                "La aplicación de Claude no está abierta en el PC.",
                style = MaterialTheme.typography.bodySmall,
            )
            OutlinedButton(onClick = onAbrir) { Text("Abrirla") }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AppAbierta(
    estado: ServerMsg.AppState,
    sesionElegida: String,
    onAbrirSesion: (String) -> Unit,
    onNueva: () -> Unit,
    onPulsar: (String) -> Unit,
    onParar: () -> Unit,
    onRefrescar: () -> Unit,
) {
    var verSesiones by rememberSaveable { mutableStateOf(false) }

    // Cual esta trabajando lo dice la barra lateral de la app, que es la unica
    // que lo sabe de verdad. `trabajando == null` significa que el PC no ha
    // reconocido el estado que pinta la app: ahi NO se dice "parada", se enseña
    // el texto crudo y se deja el punto en gris.
    val abierta = estado.sesiones.firstOrNull { it.titulo == estado.titulo }

    Row(
        Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Punto(abierta?.trabajando)
        Column(Modifier.weight(1f)) {
            Text(
                estado.titulo ?: "conversación nueva (aún sin título)",
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Bold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            val detalle = listOfNotNull(
                estado.modelo,
                abierta?.permisos?.ifBlank { null }?.let { "permisos: $it" },
                estado.uso,
            ).joinToString(" · ")
            if (detalle.isNotBlank()) {
                Text(
                    detalle,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        TextButton(onClick = onRefrescar) { Text("↻", fontSize = 14.sp) }
    }

    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        TextButton(onClick = { verSesiones = !verSesiones }) {
            Text(
                if (verSesiones) "Conversaciones ▲" else "Conversaciones (${estado.sesiones.size}) ▼",
                fontSize = 12.sp,
            )
        }
        TextButton(onClick = onNueva) { Text("Nueva", fontSize = 12.sp) }
        Spacer(Modifier.weight(1f))
        // Parar manda Escape a la ventana, igual que si lo pulsaras tu delante
        // del PC. Solo tiene sentido con algo en marcha.
        TextButton(onClick = onParar, enabled = abierta?.trabajando != false) {
            Text("Parar", fontSize = 12.sp)
        }
    }

    if (verSesiones) {
        Column(
            Modifier.fillMaxWidth().heightIn(max = 220.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            if (estado.sesiones.isEmpty()) {
                Text(
                    "Ninguna conversación a la vista. En el PC, la barra lateral de la app " +
                        "puede estar desplazada o plegada.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            estado.sesiones.forEach { s ->
                FilaSesion(
                    sesion = s,
                    abierta = s.titulo == estado.titulo,
                    elegida = s.titulo == sesionElegida,
                    onClick = { onAbrirSesion(s.titulo); verSesiones = false },
                )
            }
        }
    }

    // Los mandos, SIEMPRE a la vista. Estaban detrás de un desplegable y era un
    // coñazo: son lo que más se toca (parar, cambiar de modelo, aprobar lo que
    // saque la app) y esconderlos detrás de dos toques los hacía inútiles.
    MandosApp(estado.mandos, estado.opciones, onPulsar)
}

/**
 * La botonera de la app del PC: una fila que se desliza, siempre visible.
 *
 * En crudo y sin filtrar, a propósito: son los botones que la app tiene en
 * pantalla AHORA. Si saca una tarjeta de permiso, sus botones aparecen aquí
 * solos y se aprueban pulsando el de verdad — sin que ni el PC ni el móvil
 * tengan que conocerla de antemano.
 *
 * [opciones] son las entradas de un menú abierto (el selector de modelo, el de
 * esfuerzo…). Van SEPARADAS y por delante, y esto era un agujero de verdad:
 * antes se podía pulsar "Opus 5", el menú se abría en el PC… y no había forma
 * de elegir nada, porque las opciones no son botones sino `menuitemradio` y no
 * llegaban al móvil. Se abría el menú y ahí se quedaba.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MandosApp(
    mandos: List<String>,
    opciones: List<String>,
    onPulsar: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier.fillMaxWidth()) {
        if (opciones.isNotEmpty()) {
            Text(
                "La app está esperando a que elijas:",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.padding(top = 2.dp),
            )
            Row(
                Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                opciones.forEach { nombre ->
                    // Rellenos y de color, no `AssistChip`: una decisión
                    // pendiente tiene que cantar más que la botonera de siempre.
                    FilledTonalButton(
                        onClick = { onPulsar(nombre) },
                        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp),
                    ) { Text(recortar(nombre), fontSize = 12.sp, maxLines = 1) }
                }
            }
        }

        if (mandos.isNotEmpty()) {
            Row(
                Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                mandos.forEach { nombre ->
                    AssistChip(
                        onClick = { onPulsar(nombre) },
                        label = { Text(recortar(nombre), fontSize = 11.sp, maxLines = 1) },
                    )
                }
            }
        }
    }
}

/**
 * Los nombres largos, a algo que quepa en un chip.
 *
 * La app mete dentro del nombre cosas que no son el nombre: el atajo de teclado
 * ("Opus 5 2") y la letra pequeña ("Fable 5 Requiere créditos de uso…"). Se
 * recorta sólo lo que se PINTA — lo que se manda al PC es el nombre exacto, que
 * es con lo que encuentra el elemento.
 */
private fun recortar(nombre: String): String =
    nombre.take(28).let { if (nombre.length > 28) "$it…" else it }

@Composable
private fun FilaSesion(
    sesion: SesionApp,
    abierta: Boolean,
    elegida: Boolean,
    onClick: () -> Unit,
) {
    val fondo = when {
        abierta -> MaterialTheme.colorScheme.primaryContainer
        elegida -> MaterialTheme.colorScheme.surfaceVariant
        else -> Color.Transparent
    }
    Row(
        Modifier
            .fillMaxWidth()
            .background(fondo)
            .padding(horizontal = 6.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Punto(sesion.trabajando)
        Column(Modifier.weight(1f)) {
            Text(
                sesion.titulo,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            val pie = listOfNotNull(
                sesion.cwd.substringAfterLast('\\').ifBlank { null },
                // El estado se enseña en crudo cuando no se ha podido traducir a
                // trabajando/parada: mejor la palabra que pinta la app que un
                // icono que se lo invente.
                if (sesion.trabajando == null) sesion.estado.ifBlank { null } else null,
            ).joinToString(" · ")
            if (pie.isNotBlank()) {
                Text(
                    pie,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    fontFamily = FontFamily.Monospace,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        TextButton(onClick = onClick) { Text(if (abierta) "abierta" else "abrir", fontSize = 11.sp) }
    }
}

/** Verde = trabajando, gris = parada, hueco = no se sabe (ver SesionApp.trabajando). */
@Composable
private fun Punto(trabajando: Boolean?) {
    val color = when (trabajando) {
        true -> Color(0xFF4CAF50)
        false -> MaterialTheme.colorScheme.outline
        null -> Color.Transparent
    }
    Box(
        Modifier
            .size(8.dp)
            .background(color, CircleShape),
    )
}
