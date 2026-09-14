package com.controladora.movil.ui

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.controladora.movil.ClipPc
import com.controladora.movil.Envio
import com.controladora.movil.EnvioEstado
import com.controladora.movil.tamanoLegible
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * Pestaña "Traspaso": mover texto y archivos entre el PC y el teléfono sin pasar
 * por WhatsApp ni por el correo, y sin que nada salga de la red de Tailscale.
 *
 * Son dos caminos distintos a propósito:
 *
 *  - **El texto** va por el WebSocket que ya está abierto. Copias algo en el PC
 *    y el PC lo empuja solo (protocol.CLIP_TEXT); no hay que pedir nada ni
 *    preparar nada en el teléfono antes de copiar.
 *  - **Los archivos** van por HTTPS (POST /upload), no por el socket: una foto
 *    son varios MB, y ese socket lleva además el chat en streaming y el
 *    señalizado del vídeo.
 *
 * Lo que esta pantalla NO puede hacer, y por eso cada texto tiene un botón
 * "Copiar" en vez de aparecer por arte de magia en el portapapeles: desde
 * Android 10 una app sólo puede tocar el portapapeles del teléfono mientras está
 * en primer plano. Lo que llega con el móvil en el bolsillo se queda esperando
 * aquí, sale un aviso en la barra de notificaciones, y se copia solo en cuanto
 * abres la app (ver ChatViewModel.copiarPendienteSiHay). Ese es el techo del
 * sistema operativo, no una decisión nuestra.
 */
@Composable
fun TraspasoPanel(
    clips: List<ClipPc>,
    vigilar: Boolean,
    aviso: String,
    envios: List<Envio>,
    actionStatus: String,
    online: Boolean,
    onVigilar: (Boolean) -> Unit,
    onPedirDelPc: () -> Unit,
    onCopiar: (ClipPc) -> Unit,
    onMandarAlPc: () -> Unit,
    onArchivos: (List<Uri>) -> Unit,
    onLimpiarEnvios: () -> Unit,
    onAbrirCarpeta: () -> Unit,
    modifier: Modifier = Modifier,
) {
    // Dos selectores y no uno. El de fotos (el "photo picker" del sistema) no
    // pide NINGÚN permiso y enseña la galería de verdad, con miniaturas: es lo
    // que uno espera al ir a mandar una foto. El de documentos abre el
    // explorador de archivos y sirve para todo lo demás (un PDF, un zip, un
    // log). Con uno solo, o mandar una foto era incómodo o mandar un zip era
    // imposible.
    val selectorFotos = rememberLauncherForActivityResult(
        ActivityResultContracts.PickMultipleVisualMedia(),
    ) { uris -> onArchivos(uris) }

    val selectorArchivos = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenMultipleDocuments(),
    ) { uris -> onArchivos(uris) }

    Column(
        modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        if (!online) {
            Aviso("Sin conexión con el PC. Ni el portapapeles ni los archivos van a ninguna parte hasta que vuelva.")
        }

        // ---------------------------------------------------------- texto ---
        Card(shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Portapapeles", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)

                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text("Traer lo que copie en el PC", style = MaterialTheme.typography.bodyMedium)
                        Text(
                            if (vigilar) {
                                "Cada Ctrl+C del PC aparece aquí abajo."
                            } else {
                                "El PC no está mirando su portapapeles."
                            },
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Switch(checked = vigilar, onCheckedChange = onVigilar)
                }

                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(
                        onClick = onPedirDelPc,
                        enabled = online,
                        modifier = Modifier.weight(1f),
                    ) { Text("Traer del PC", fontSize = 13.sp) }
                    OutlinedButton(
                        onClick = onMandarAlPc,
                        enabled = online,
                        modifier = Modifier.weight(1f),
                    ) { Text("Mandar al PC", fontSize = 13.sp) }
                }

                if (aviso.isNotBlank()) {
                    Text(
                        aviso,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.primary,
                    )
                }

                if (clips.isEmpty()) {
                    Text(
                        "Todavía no ha llegado nada. Copia algo en el PC (Ctrl+C) y aparecerá aquí.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    clips.forEach { ClipCard(it, onCopiar) }
                }
            }
        }

        // ------------------------------------------------------- archivos ---
        Card(shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Archivos al PC", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                Text(
                    "Aterrizan en la carpeta de recibidos del PC (Documentos/ControlaPics, salvo que se " +
                        "haya cambiado en paths.json). No se pisa nada: si ya hay uno con ese nombre, el " +
                        "PC guarda el nuevo como «(2)».",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )

                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(
                        onClick = {
                            selectorFotos.launch(
                                PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageAndVideo),
                            )
                        },
                        enabled = online,
                        modifier = Modifier.weight(1f),
                    ) { Text("Fotos y vídeos", fontSize = 13.sp) }
                    Button(
                        onClick = { selectorArchivos.launch(arrayOf("*/*")) },
                        enabled = online,
                        modifier = Modifier.weight(1f),
                    ) { Text("Otros archivos", fontSize = 13.sp) }
                }

                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    OutlinedButton(
                        onClick = onAbrirCarpeta,
                        enabled = online,
                        modifier = Modifier.weight(1f),
                    ) { Text("Abrir carpeta en el PC", fontSize = 13.sp) }
                    if (envios.any { it.estado is EnvioEstado.Hecho || it.estado is EnvioEstado.Fallo }) {
                        TextButton(onClick = onLimpiarEnvios) { Text("Limpiar", fontSize = 13.sp) }
                    }
                }

                if (actionStatus.isNotBlank()) {
                    Text(
                        actionStatus,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }

                envios.forEach { EnvioCard(it) }
            }
        }
    }
}

/** Un texto llegado del PC: lo que dice, cuándo llegó, y el botón que lo deja en
 * el portapapeles del teléfono. */
@Composable
private fun ClipCard(clip: ClipPc, onCopiar: (ClipPc) -> Unit) {
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
        shape = RoundedCornerShape(10.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(
                clip.texto,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 4,
                overflow = TextOverflow.Ellipsis,
            )
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    buildString {
                        append(hora(clip.cuando))
                        append(" · ${clip.texto.length} caracteres")
                        // Este aviso importa: pegar medio texto creyéndolo entero
                        // es peor que no tenerlo, porque no se nota hasta después.
                        if (clip.cortado) append(" · RECORTADO por el PC")
                        if (clip.copiado) append(" · copiado")
                    },
                    style = MaterialTheme.typography.labelSmall,
                    color = if (clip.cortado) {
                        MaterialTheme.colorScheme.error
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
                TextButton(onClick = { onCopiar(clip) }) { Text("Copiar", fontSize = 13.sp) }
            }
        }
    }
}

/** Un archivo camino del PC, con su barra mientras sube. */
@Composable
private fun EnvioCard(envio: Envio) {
    val estado = envio.estado
    Card(
        colors = CardDefaults.cardColors(
            containerColor = if (estado is EnvioEstado.Fallo) {
                MaterialTheme.colorScheme.errorContainer
            } else {
                MaterialTheme.colorScheme.surfaceVariant
            },
        ),
        shape = RoundedCornerShape(10.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(
                envio.nombre,
                style = MaterialTheme.typography.bodySmall,
                fontWeight = FontWeight.Bold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            when (estado) {
                is EnvioEstado.Esperando -> Linea("en cola · ${tamanoLegible(envio.bytes)}")
                is EnvioEstado.Subiendo -> {
                    // Con porcentaje si el proveedor del archivo dijo el tamaño; si
                    // no, barra indeterminada: mejor "está pasando algo" que un
                    // porcentaje inventado sobre un total que no conocemos.
                    if (estado.pct != null) {
                        LinearProgressIndicator(progress = { estado.pct }, modifier = Modifier.fillMaxWidth())
                        Linea("subiendo ${(estado.pct * 100).toInt()}% de ${tamanoLegible(envio.bytes)}")
                    } else {
                        LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                        Linea("subiendo…")
                    }
                }
                is EnvioEstado.Hecho -> Linea("en el PC: ${estado.ruta}")
                is EnvioEstado.Fallo -> Linea("no se pudo: ${estado.razon}")
            }
        }
    }
}

@Composable
private fun Linea(texto: String) {
    Text(
        texto,
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
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

private val FORMATO_HORA = DateTimeFormatter.ofPattern("HH:mm:ss")

private fun hora(epochMillis: Long): String =
    Instant.ofEpochMilli(epochMillis).atZone(ZoneId.systemDefault()).format(FORMATO_HORA)
