package com.controladora.movil.ui

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.controladora.movil.net.Stats
import kotlinx.coroutines.delay

/**
 * Las tres formas de mirar el mismo [Stats]: mismo dato, distinto orden segun
 * que te preocupa ahora mismo. General es la de siempre (un poco de todo);
 * Temperaturas junta las dos lecturas de grados para ver de un vistazo si algo
 * se esta calentando; Cargas junta los porcentajes de uso (CPU/RAM/GPU, por
 * nucleo, VRAM, discos) para ver de un vistazo donde esta el cuello de botella.
 */
enum class VistaMonitor { General, Temperaturas, Cargas }

private fun etiqueta(v: VistaMonitor): String = when (v) {
    VistaMonitor.General -> "General"
    VistaMonitor.Temperaturas -> "Temperaturas"
    VistaMonitor.Cargas -> "Cargas"
}

/**
 * Pestana "Monitor": el estado del PC, dibujado.
 *
 * Antes esto era el parrafo que lee el modelo, volcado tal cual en monoespaciado.
 * Se veia como un `cat` de un fichero y no como una pantalla, y no habia forma de
 * mejorarlo desde aqui: llegaba texto ya formateado, no numeros. Ahora el PC manda
 * la medida en crudo (stats.result → data, ver sysinfo.py) y aqui se dibuja.
 *
 * No pasa por ningun cerebro: un refresco cada 3s no debe gastar tokens ni
 * depender de que un LLM interprete la peticion. Reiniciar y apagar SI piden
 * confirmacion -- reusan la tarjeta de permiso de siempre, porque esas tools
 * llevan CONFIRM = True.
 */
@Composable
fun MonitorPanel(
    stats: Stats?,
    statsText: String,
    actionStatus: String,
    online: Boolean,
    vista: VistaMonitor,
    onVista: (VistaMonitor) -> Unit,
    onRefresh: () -> Unit,
    onReboot: () -> Unit,
    onShutdown: () -> Unit,
    onCancel: () -> Unit,
    modifier: Modifier = Modifier,
) {
    // 3s y no 5: ahora una lectura cuesta ~100ms en el PC en vez de mas de un
    // segundo (se dormia medio segundo a proposito para medir la CPU), asi que
    // refrescar mas a menudo ya no cuesta nada y se nota vivo.
    LaunchedEffect(online) {
        while (online) {
            onRefresh()
            delay(3000)
        }
    }

    Column(
        modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Estado del PC", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
            if (stats != null) {
                Text(
                    "encendido ${uptime(stats.uptimeS)}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        // Cambia el ORDEN y AGRUPACION de las mismas lecturas, no lo que se mide:
        // el mismo Stats de cada 3s se pinta distinto segun a que quieras darle
        // foco ahora mismo, sin volver a pedir nada al PC.
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.fillMaxWidth()) {
            VistaMonitor.entries.forEach { v ->
                FilterChip(
                    selected = vista == v,
                    onClick = { onVista(v) },
                    label = { Text(etiqueta(v), fontSize = 12.sp) },
                )
            }
        }

        if (stats == null) {
            // Sin datos: o no ha llegado el primero, o el PC no pudo medir y solo
            // mando texto. Se ensena lo que haya en vez de una pantalla en blanco.
            Card(
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    statsText.ifBlank { if (online) "midiendo…" else "sin conexión con el PC" },
                    Modifier.padding(14.dp),
                    fontFamily = FontFamily.Monospace,
                    fontSize = 12.sp,
                )
            }
        } else {
            when (vista) {
                VistaMonitor.General -> VistaGeneral(stats)
                VistaMonitor.Temperaturas -> VistaTemperaturas(stats)
                VistaMonitor.Cargas -> VistaCargas(stats)
            }
        }

        if (actionStatus.isNotBlank()) {
            Card(
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.tertiaryContainer),
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(actionStatus, Modifier.padding(10.dp), fontSize = 12.sp, fontFamily = FontFamily.Monospace)
            }
        }

        Text(
            "Reiniciar y apagar piden confirmación antes de ejecutarse.",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 4.dp),
        )

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            Button(
                onClick = onReboot,
                enabled = online,
                modifier = Modifier.weight(1f),
                colors = ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.colorScheme.errorContainer,
                    contentColor = MaterialTheme.colorScheme.onErrorContainer,
                ),
            ) { Text("Reiniciar") }
            Button(
                onClick = onShutdown,
                enabled = online,
                modifier = Modifier.weight(1f),
                colors = ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.colorScheme.errorContainer,
                    contentColor = MaterialTheme.colorScheme.onErrorContainer,
                ),
            ) { Text("Apagar") }
        }
        OutlinedButton(onClick = onCancel, enabled = online, modifier = Modifier.fillMaxWidth()) {
            Text("Cancelar apagado/reinicio")
        }
    }
}

/** La vista de siempre: un poco de todo, en el orden original. */
@Composable
private fun VistaGeneral(stats: Stats) {
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
        Medidor(
            titulo = "CPU",
            pct = stats.cpuPct,
            centro = "${stats.cpuPct.toInt()}%",
            pie = stats.cpuFreqMhz?.let { "${"%.1f".format(it / 1000f)} GHz" } ?: "${stats.cpuNucleos} núcleos",
            modifier = Modifier.weight(1f),
        )
        Medidor(
            titulo = "RAM",
            pct = stats.ramPct,
            centro = "${stats.ramPct.toInt()}%",
            pie = "%.1f / %.0f GB".format(stats.ramUsadaGb, stats.ramTotalGb),
            modifier = Modifier.weight(1f),
        )
        val gpu = stats.gpu
        Medidor(
            titulo = "GPU",
            pct = gpu?.usoPct ?: 0f,
            centro = gpu?.usoPct?.let { "${it.toInt()}%" } ?: "—",
            pie = gpu?.tempC?.let { "${it.toInt()}°C" } ?: "sin datos",
            modifier = Modifier.weight(1f),
        )
    }

    CpuCard(stats)
    GpuCard(stats)

    if (stats.discos.isNotEmpty()) {
        Bloque("Discos") {
            stats.discos.forEach { d ->
                Linea(etiqueta = d.unidad, valor = "%.0f / %.0f GB".format(d.usadoGb, d.totalGb), pct = d.pct)
            }
        }
    }
}

/**
 * Solo grados: los dos anillos de temperatura arriba (CPU y GPU, misma escala
 * de color que en las demas vistas via [pctTemp]) y, si falta alguna lectura,
 * el motivo exacto debajo -- nunca un hueco en blanco sin explicar.
 */
@Composable
private fun VistaTemperaturas(stats: Stats) {
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
        Medidor(
            titulo = "CPU",
            pct = stats.cpuTempC?.let { pctTemp(it) } ?: 0f,
            centro = stats.cpuTempC?.let { "${it.toInt()}°C" } ?: "—",
            pie = "temperatura",
            modifier = Modifier.weight(1f),
        )
        Medidor(
            titulo = "GPU",
            pct = stats.gpu?.tempC?.let { pctTemp(it) } ?: 0f,
            centro = stats.gpu?.tempC?.let { "${it.toInt()}°C" } ?: "—",
            pie = "temperatura",
            modifier = Modifier.weight(1f),
        )
    }

    val notaCpu = if (stats.cpuTempC == null) stats.cpuTempNota ?: "Temperatura de CPU no disponible." else null
    val notaGpu = when {
        stats.gpu == null -> stats.gpuError ?: "No se pudo leer la GPU."
        stats.gpu.tempC == null -> "Temperatura de GPU no disponible."
        else -> null
    }
    if (notaCpu != null || notaGpu != null) {
        Bloque("Sin dato") {
            notaCpu?.let {
                Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            notaGpu?.let {
                Text(
                    it,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = if (notaCpu != null) 4.dp else 0.dp),
                )
            }
        }
    }
}

/**
 * Solo porcentajes de uso: CPU/RAM/GPU arriba, por nucleo (el mismo bloque que
 * en General, ver [PorNucleoBarras]), VRAM y discos debajo. Nada de grados
 * aqui -- para eso esta la otra vista.
 */
@Composable
private fun VistaCargas(stats: Stats) {
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
        Medidor(
            titulo = "CPU",
            pct = stats.cpuPct,
            centro = "${stats.cpuPct.toInt()}%",
            pie = "${stats.cpuNucleos} núcleos",
            modifier = Modifier.weight(1f),
        )
        Medidor(
            titulo = "RAM",
            pct = stats.ramPct,
            centro = "${stats.ramPct.toInt()}%",
            pie = "%.1f / %.0f GB".format(stats.ramUsadaGb, stats.ramTotalGb),
            modifier = Modifier.weight(1f),
        )
        val gpu = stats.gpu
        Medidor(
            titulo = "GPU",
            pct = gpu?.usoPct ?: 0f,
            centro = gpu?.usoPct?.let { "${it.toInt()}%" } ?: "—",
            pie = if (gpu?.usoPct != null) "carga" else "sin datos",
            modifier = Modifier.weight(1f),
        )
    }

    if (stats.porNucleo.isNotEmpty()) {
        Bloque("Por núcleo") { PorNucleoBarras(stats.porNucleo) }
    }

    val gpu = stats.gpu
    if (gpu?.vramUsadaMb != null && gpu.vramTotalMb != null && gpu.vramTotalMb > 0f) {
        Bloque("${gpu.nombre} · VRAM") {
            Linea(
                "VRAM",
                "%.1f / %.1f GB".format(gpu.vramUsadaMb / 1024f, gpu.vramTotalMb / 1024f),
                gpu.vramUsadaMb / gpu.vramTotalMb * 100f,
            )
        }
    }

    if (stats.discos.isNotEmpty()) {
        Bloque("Discos") {
            stats.discos.forEach { d ->
                Linea(etiqueta = d.unidad, valor = "%.0f / %.0f GB".format(d.usadoGb, d.totalGb), pct = d.pct)
            }
        }
    }
}

@Composable
private fun CpuCard(stats: Stats) {
    Bloque("CPU · ${stats.cpuNucleos} núcleos lógicos") {
        // La temperatura de CPU: o el numero, o EXACTAMENTE por que no esta.
        //
        // Aqui ponia "sin sensor de temperatura de fabrica", que ademas de sonar a
        // excusa era falso: el sensor existe (Tctl/Tdie), lo que no hay es quien lo
        // lea sin un driver en anillo 0, y este servicio corre como usuario normal
        // a proposito. Si abres LibreHardwareMonitor, el PC la lee solo y esto pasa
        // a ensenar el numero sin tocar nada mas (ver sysinfo._leer_temp_wmi).
        if (stats.cpuTempC != null) {
            Linea("Temperatura", "${stats.cpuTempC.toInt()}°C", pctTemp(stats.cpuTempC))
        } else {
            Text(
                stats.cpuTempNota ?: "Temperatura de CPU no disponible.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(bottom = 6.dp),
            )
        }

        if (stats.porNucleo.isNotEmpty()) {
            Text(
                "Por núcleo",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            PorNucleoBarras(stats.porNucleo)
        }
    }
}

/** Una columna por nucleo, como el Administrador de tareas: de un vistazo se ve
 * si hay un hilo comiendose un nucleo o si el trabajo esta repartido. Vive
 * fuera de CpuCard porque VistaCargas tambien la pinta, sin el resto de la
 * tarjeta de CPU (temperatura incluida, que ahi no toca). */
@Composable
private fun PorNucleoBarras(porNucleo: List<Float>) {
    Row(
        Modifier
            .fillMaxWidth()
            .height(40.dp)
            .padding(top = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(3.dp),
        verticalAlignment = Alignment.Bottom,
    ) {
        porNucleo.forEach { pct ->
            val alto by animateFloatAsState((pct / 100f).coerceIn(0.04f, 1f), label = "nucleo")
            Box(
                Modifier
                    .weight(1f)
                    .fillMaxHeight(alto)
                    .clip(RoundedCornerShape(2.dp))
                    .background(colorCarga(pct)),
            )
        }
    }
}

@Composable
private fun GpuCard(stats: Stats) {
    val gpu = stats.gpu
    if (gpu == null) {
        Bloque("GPU") {
            Text(
                stats.gpuError ?: "No se pudo leer la GPU.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.error,
            )
        }
        return
    }

    Bloque(gpu.nombre) {
        gpu.usoPct?.let { Linea("Carga", "${it.toInt()}%", it) }
        gpu.tempC?.let { Linea("Temperatura", "${it.toInt()}°C", pctTemp(it)) }
        if (gpu.vramUsadaMb != null && gpu.vramTotalMb != null && gpu.vramTotalMb > 0f) {
            Linea(
                "VRAM",
                "%.1f / %.1f GB".format(gpu.vramUsadaMb / 1024f, gpu.vramTotalMb / 1024f),
                gpu.vramUsadaMb / gpu.vramTotalMb * 100f,
            )
        }
        gpu.potenciaW?.let {
            Text(
                "${it.toInt()} W",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun Bloque(titulo: String, contenido: @Composable () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(14.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(12.dp)) {
            Text(
                titulo,
                style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.padding(bottom = 6.dp),
            )
            contenido()
        }
    }
}

/** Una fila: nombre a la izquierda, valor a la derecha, barra debajo. */
@Composable
private fun Linea(etiqueta: String, valor: String, pct: Float) {
    Column(Modifier.padding(vertical = 3.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(etiqueta, style = MaterialTheme.typography.labelSmall)
            Text(
                valor,
                style = MaterialTheme.typography.labelSmall,
                fontFamily = FontFamily.Monospace,
                color = colorCarga(pct),
            )
        }
        Barra(pct)
    }
}

@Composable
private fun Barra(pct: Float) {
    val objetivo by animateFloatAsState((pct / 100f).coerceIn(0f, 1f), label = "barra")
    Box(
        Modifier
            .fillMaxWidth()
            .height(5.dp)
            .padding(top = 2.dp)
            .clip(RoundedCornerShape(3.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Box(
            Modifier
                .fillMaxHeight()
                .fillMaxWidth(objetivo)
                .clip(RoundedCornerShape(3.dp))
                .background(colorCarga(pct)),
        )
    }
}

/** El anillo de porcentaje. Es lo primero que se ve al abrir la pestana. */
@Composable
private fun Medidor(titulo: String, pct: Float, centro: String, pie: String, modifier: Modifier = Modifier) {
    val objetivo by animateFloatAsState((pct / 100f).coerceIn(0f, 1f), label = "medidor")
    val color = colorCarga(pct)
    val pista = MaterialTheme.colorScheme.surfaceVariant

    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(14.dp),
        modifier = modifier,
    ) {
        Column(
            Modifier
                .fillMaxWidth()
                .padding(vertical = 10.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(titulo, style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold)
            Box(Modifier.padding(vertical = 6.dp), contentAlignment = Alignment.Center) {
                Canvas(Modifier.size(64.dp)) {
                    val grosor = 7.dp.toPx()
                    val lado = size.minDimension - grosor
                    val tamano = Size(lado, lado)
                    val esquina = androidx.compose.ui.geometry.Offset(grosor / 2, grosor / 2)
                    // Empieza arriba (-90°) y solo da 3/4 de vuelta: el hueco de
                    // abajo es lo que hace que se lea como un medidor y no como una
                    // rueda de "cargando".
                    drawArc(
                        color = pista,
                        startAngle = 135f,
                        sweepAngle = 270f,
                        useCenter = false,
                        topLeft = esquina,
                        size = tamano,
                        style = Stroke(width = grosor, cap = StrokeCap.Round),
                    )
                    drawArc(
                        color = color,
                        startAngle = 135f,
                        sweepAngle = 270f * objetivo,
                        useCenter = false,
                        topLeft = esquina,
                        size = tamano,
                        style = Stroke(width = grosor, cap = StrokeCap.Round),
                    )
                }
                Text(centro, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
            }
            Text(
                pie,
                style = MaterialTheme.typography.labelSmall,
                fontSize = 10.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/** Verde tranquilo → ambar → rojo. El color hace el trabajo de leer el numero. */
private fun colorCarga(pct: Float): Color = when {
    pct >= 90f -> Color(0xFFE45749)
    pct >= 70f -> Color(0xFFE0A33E)
    else -> Color(0xFF57A773)
}

/** Una temperatura no es un porcentaje: 60°C no es "60% de calor". Se mapea a la
 * franja que de verdad importa (40°C tranquilo → 90°C preocupante) para que el
 * color signifique lo mismo que en las demas barras. */
private fun pctTemp(grados: Float): Float = ((grados - 40f) / 50f * 100f).coerceIn(0f, 100f)

private fun uptime(segundos: Long): String {
    val dias = segundos / 86400
    val horas = (segundos % 86400) / 3600
    val minutos = (segundos % 3600) / 60
    return when {
        dias > 0 -> "${dias}d ${horas}h"
        horas > 0 -> "${horas}h ${minutos}m"
        else -> "${minutos}m"
    }
}
