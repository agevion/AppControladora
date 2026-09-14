package com.controladora.movil.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.controladora.movil.net.Proyecto

/**
 * Pestana "Acciones rapidas": botones que hacen la cosa, no botones que le
 * escriben un recado a una IA para que la haga.
 *
 * Esto era casi todo mentira y por eso "la mayoria ni funcionan". Habia una caja
 * de texto donde escribias el nombre de un proyecto y el boton le mandaba a
 * Claude Code el mensaje "busca el proyecto «X» en pc/paths.json y dime su ruta".
 * Dos cosas mal, las dos gordas:
 *
 *  1. **No podia funcionar.** El cwd de Claude es la carpeta del proyecto, no la
 *     raiz del repo, asi que "pc/paths.json" no existe desde ahi. De ahi la
 *     respuesta de "no existe pc/paths.json en este sistema, ¿seguro que ese
 *     fichero vive en esta maquina?": Claude buscaba donde le habiamos puesto, y
 *     ahi de verdad no estaba. Y como el boton de "los demas proyectos" pedia lo
 *     mismo del mismo fichero, caia igual.
 *  2. **Aunque hubiera funcionado, estaba mal.** paths.json vive en el disco del
 *     PC, en el mismo proceso que atiende el WebSocket. Pagarle tokens a Claude
 *     Code para que abra un JSON de cien lineas que tenemos delante es
 *     exactamente lo que este proyecto existe para no hacer.
 *
 * Ahora el PC manda la lista el (projects.request, ver server.py) y cada boton
 * llama a la tool directamente con sus argumentos (action.request). Cero tokens,
 * cero interpretacion, y no hay nada que "encontrar": eliges el proyecto de la
 * lista de los que hay de verdad.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun QuickActionsPanel(
    proyectos: List<Proyecto>,
    online: Boolean,
    onAction: (String, Map<String, Any>, String) -> Unit,
    onRefreshProyectos: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var elegido by remember { mutableStateOf<String?>(null) }
    val proyecto = proyectos.firstOrNull { it.nombre == elegido }

    Column(
        modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        if (!online) {
            // Antes los botones se pulsaban igual sin conexion: el mensaje se
            // evaporaba y el indicador se ponia a contar un turno inexistente.
            // Ahora se dice, y ademas no se dejan pulsar (enabled = online).
            Aviso("Sin conexión con el PC. Los botones no harán nada hasta que vuelva.")
        }

        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Proyectos", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
            TextButton(onClick = onRefreshProyectos, enabled = online) { Text("↻ recargar", fontSize = 12.sp) }
        }

        if (proyectos.isEmpty()) {
            Text(
                if (online) "pidiéndole la lista al PC…" else "la lista la manda el PC al conectar",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            // Los proyectos que de verdad hay en paths.json, no un campo de texto
            // donde adivinar el nombre exacto de memoria estando en el gym.
            FlowChips(proyectos, elegido) { elegido = if (elegido == it) null else it }
        }

        proyecto?.let { p ->
            Card(
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(Modifier.padding(10.dp)) {
                    Text(p.descripcion.ifBlank { p.nombre }, style = MaterialTheme.typography.bodySmall)
                    Text(
                        p.path,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    if (!p.existe) {
                        Text(
                            "⚠ Esa carpeta ya no existe en el PC.",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                    // Que va a salir de darle al boton, dicho ANTES de esperar
                    // tres minutos: el PC ya ha mirado el build.gradle. En rojo
                    // solo si lo que sale es una debug (una app mas lenta de lo
                    // que deberia); que un mod de Java no genere APK no es un
                    // problema, es lo normal, y no merece pintarse como error.
                    if (p.varianteNota.isNotBlank()) {
                        Text(
                            p.varianteNota,
                            style = MaterialTheme.typography.labelSmall,
                            color = if (p.variante == "assembleDebug") {
                                MaterialTheme.colorScheme.error
                            } else {
                                MaterialTheme.colorScheme.onSurfaceVariant
                            },
                        )
                    }
                }
            }

            val activo = online && p.existe
            if (p.tipo == "gradle") {
                // Los botones de arriba NO mandan `tarea`: el PC elige la mejor
                // variante mirando el build.gradle del proyecto (variantes.py), y
                // por defecto es release. Antes esto compilaba siempre debug --
                // una app con el flag `debuggable`, que apaga optimizaciones de
                // ART y va notablemente mas lenta que la de verdad. El de debug
                // sigue estando, pero abajo y como lo que es: la excepcion.
                val sufijo = if (p.esRelease) " (release)" else ""
                Boton("Compilar y enviarme el APK$sufijo", activo) {
                    onAction("build_and_send", mapOf("proyecto" to p.nombre), "Compilar y enviar")
                }
                Boton("Solo compilar$sufijo", activo) {
                    onAction("build_gradle", mapOf("proyecto" to p.nombre), "Compilar")
                }
                // Solo donde hay dos variantes que elegir. En un mod de Java
                // (tarea "build") no existe assembleDebug y el boton seria un
                // fallo garantizado.
                if (p.esRelease) {
                    Secundario("Compilar debug y enviármelo", activo) {
                        onAction(
                            "build_and_send",
                            mapOf("proyecto" to p.nombre, "tarea" to "assembleDebug"),
                            "Compilar debug y enviar",
                        )
                    }
                }
                Secundario("Abrir en Android Studio", activo) {
                    onAction("open_app", mapOf("app" to "android_studio", "proyecto" to p.nombre), "Abrir Android Studio")
                }
                Secundario("Abrir en IntelliJ", activo) {
                    onAction("open_app", mapOf("app" to "intellij", "proyecto" to p.nombre), "Abrir IntelliJ")
                }
            } else {
                // Unity no compila desde aqui a proposito: unity_build necesita un
                // metodo de build dentro del proyecto (ARQUITECTURA.md seccion 11)
                // y ese nombre no se puede adivinar desde un boton. Para eso esta
                // el chat, que si puede preguntarte cual.
                Secundario("Abrir en Unity Hub", activo) {
                    onAction("open_app", mapOf("app" to "unity_hub", "proyecto" to p.nombre), "Abrir Unity Hub")
                }
                Text(
                    "Compilar en Unity necesita el nombre del método de build: pídelo por el chat.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/**
 * Los chips de proyecto, en filas que se parten solas.
 *
 * A mano y no con FlowRow: FlowRow sigue siendo experimental en el Compose de este
 * proyecto y no merece la pena arrastrar un opt-in mas por un envoltorio de tres
 * lineas. Los nombres de proyecto son cortos; tres por fila entran de sobra.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FlowChips(proyectos: List<Proyecto>, elegido: String?, onElegir: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        proyectos.chunked(3).forEach { fila ->
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.fillMaxWidth()) {
                fila.forEach { p ->
                    FilterChip(
                        selected = elegido == p.nombre,
                        onClick = { onElegir(p.nombre) },
                        label = { Text(p.nombre, fontSize = 11.sp, maxLines = 1) },
                        modifier = Modifier.weight(1f),
                    )
                }
                // Rellena el hueco de la ultima fila para que los chips no se
                // estiren al doble de ancho que los de arriba.
                repeat(3 - fila.size) { Spacer(Modifier.weight(1f)) }
            }
        }
    }
}

@Composable
private fun Boton(texto: String, enabled: Boolean, onClick: () -> Unit) {
    Button(onClick = onClick, enabled = enabled, modifier = Modifier.fillMaxWidth()) { Text(texto) }
}

@Composable
private fun Secundario(texto: String, enabled: Boolean, onClick: () -> Unit) {
    OutlinedButton(onClick = onClick, enabled = enabled, modifier = Modifier.fillMaxWidth()) { Text(texto) }
}

@Composable
private fun Aviso(texto: String) {
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer),
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Text(texto, Modifier.padding(10.dp), style = MaterialTheme.typography.labelSmall)
    }
}
