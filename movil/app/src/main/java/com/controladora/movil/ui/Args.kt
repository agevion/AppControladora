package com.controladora.movil.ui

import org.json.JSONObject

/**
 * Traduce los args crudos de una tool a lo que hay que leer para decidir si la dejas correr.
 *
 * Los args llegan como el JSON tal cual del protocolo. Para la IA local eso era
 * inofensivo (`{"comando": "adb devices"}` cabe en dos lineas), pero Claude manda
 * `Edit` y `Write` con el contenido del fichero DENTRO de los args: volcarlo tal
 * cual pintaba una tarjeta de miles de dp de alto. Eso empujaba los botones y la
 * caja de texto fuera de la pantalla y dejaba la app inservible -- el permiso no se
 * podia ni aceptar ni rechazar, que es exactamente el bloqueo que se vio al pedir
 * un permiso de edicion.
 *
 * Aqui se decide por tool que campos importan de verdad. Lo que no se conoce cae en
 * un volcado generico con cada valor recortado, asi que una tool nueva nunca podra
 * volver a romper el layout aunque nadie se acuerde de tocar esto.
 *
 * OJO CON RECORTAR (ARQUITECTURA.md seccion 9): "lo que lees es exactamente lo que
 * corre" solo se sostiene si lo que se ejecuta se ensena ENTERO. Por eso un comando
 * (`run_shell`, `Bash`) nunca se recorta: es la frontera de seguridad, y ahora el
 * dialogo hace scroll, asi que no hay excusa de espacio. Lo que si se recorta es el
 * CONTENIDO de un fichero en un Edit/Write, que es una vista previa y no un comando:
 * ahi lo que apruebas es "que Claude toque este fichero", no revisar un diff de 800
 * lineas de pie en el gym. Y el recorte siempre se anuncia, nunca es silencioso.
 */
private const val MAX_VALOR = 400

fun resumeArgs(name: String, argsJson: String): String {
    val o = try {
        JSONObject(argsJson)
    } catch (e: Exception) {
        return recorta(argsJson)
    }

    return when (name) {
        "Edit" -> buildString {
            appendLine("fichero: ${o.optString("file_path")}")
            val viejo = o.optString("old_string")
            val nuevo = o.optString("new_string")
            if (viejo.isNotBlank()) {
                appendLine()
                appendLine("QUITA:")
                appendLine(recorta(viejo))
            }
            if (nuevo.isNotBlank()) {
                appendLine()
                appendLine("PONE:")
                appendLine(recorta(nuevo))
            }
        }.trim()

        "Write" -> {
            val cuerpo = o.optString("content")
            "fichero: ${o.optString("file_path")}\n" +
                "escribe ${lineas(cuerpo)} líneas\n\n${recorta(cuerpo)}"
        }

        // Los dos que ejecutan un comando: entero y sin recortar, es lo que apruebas.
        "Bash" -> {
            val cmd = o.optString("command")
            val desc = o.optString("description")
            if (desc.isBlank()) cmd else "$desc\n\n$cmd"
        }

        // La tool del cerebro local: el comando ES el permiso (ARQUITECTURA.md seccion 9).
        "run_shell" -> o.optString("comando").ifBlank { argsJson }

        else -> o.keys().asSequence()
            .filter { it != "motivo" } // ya se pinta aparte, arriba del todo
            .joinToString("\n") { k -> "$k: ${recorta(o.opt(k)?.toString().orEmpty())}" }
            .ifBlank { "(sin argumentos)" }
    }
}

private fun lineas(s: String): Int = if (s.isEmpty()) 0 else s.count { it == '\n' } + 1

private fun recorta(s: String): String =
    if (s.length <= MAX_VALOR) s else s.take(MAX_VALOR) + "\n… (+${s.length - MAX_VALOR} caracteres)"
