package com.controladora.movil.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/**
 * Dos paletas, siempre oscuras: no hay modo claro en esta app.
 *
 * - [LocalScheme] es el gris neutro de toda la vida, para cuando el cerebro
 *   es la IA local.
 * - [ClaudeScheme] son los colores de Claude (grisaceo calido + el naranja
 *   terracota de Anthropic) y solo se activa cuando `brain == "claude"`, asi
 *   la ventana avisa con un vistazo de con quien estas hablando.
 */
private val LocalScheme = darkColorScheme(
    primary = Color(0xFF8AB4F8),
    onPrimary = Color(0xFF0B2545),
    primaryContainer = Color(0xFF2A3F5F),
    onPrimaryContainer = Color(0xFFD3E3FD),
    secondary = Color(0xFFB0BEC5),
    background = Color(0xFF121212),
    onBackground = Color(0xFFE3E3E3),
    surface = Color(0xFF1A1A1A),
    onSurface = Color(0xFFE3E3E3),
    surfaceVariant = Color(0xFF2A2A2A),
    onSurfaceVariant = Color(0xFFC7C7C7),
    tertiaryContainer = Color(0xFF2E2E2E),
    onTertiaryContainer = Color(0xFFD8D8D8),
    error = Color(0xFFCF6679),
    errorContainer = Color(0xFF4C2020),
    onErrorContainer = Color(0xFFFFD9D9),
)

private val ClaudeScheme = darkColorScheme(
    primary = Color(0xFFCC785C),
    onPrimary = Color(0xFF2A1710),
    primaryContainer = Color(0xFF4A3327),
    onPrimaryContainer = Color(0xFFF3D6C7),
    secondary = Color(0xFFB5A99C),
    background = Color(0xFF262624),
    onBackground = Color(0xFFE8E4DD),
    surface = Color(0xFF2E2E2B),
    onSurface = Color(0xFFE8E4DD),
    surfaceVariant = Color(0xFF3B3A37),
    onSurfaceVariant = Color(0xFFD1CABF),
    tertiaryContainer = Color(0xFF3B3A37),
    onTertiaryContainer = Color(0xFFE8E4DD),
    error = Color(0xFFE5836A),
    errorContainer = Color(0xFF4C2A20),
    onErrorContainer = Color(0xFFFFDACE),
)

/**
 * [TerminalScheme]: slate oscuro azulado + acento verde menta, estilo terminal
 * moderna (tipo Tokyo Night / One Dark). Sigue distinguiendose de un vistazo de
 * los dos chats de IA, pero sin el verde fosforito que cansaba la vista. El
 * `error` sigue siendo rojo: es lo unico que en toda la app significa
 * "administrador".
 */
private val TerminalScheme = darkColorScheme(
    primary = Color(0xFF5EEAD4),
    onPrimary = Color(0xFF05201C),
    primaryContainer = Color(0xFF134E48),
    onPrimaryContainer = Color(0xFFB8F5EA),
    secondary = Color(0xFF8FA6C4),
    background = Color(0xFF11151C),
    onBackground = Color(0xFFDCE3F0),
    surface = Color(0xFF171C26),
    onSurface = Color(0xFFDCE3F0),
    surfaceVariant = Color(0xFF232A38),
    onSurfaceVariant = Color(0xFF9FB0CC),
    tertiaryContainer = Color(0xFF1E2632),
    onTertiaryContainer = Color(0xFFCBD6EA),
    error = Color(0xFFE5836A),
    errorContainer = Color(0xFF4C2A20),
    onErrorContainer = Color(0xFFFFDACE),
)

@Composable
fun ControladoraTheme(brain: String, content: @Composable () -> Unit) {
    val scheme = when (brain) {
        "claude" -> ClaudeScheme
        "terminal" -> TerminalScheme
        else -> LocalScheme
    }
    MaterialTheme(colorScheme = scheme, content = content)
}
