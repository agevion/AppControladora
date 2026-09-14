package com.controladora.movil.net

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.core.content.FileProvider
import java.io.File

/**
 * Lanza el instalador del sistema para un APK ya bajado a disco (ver
 * ControladoraClient.downloadArtifact). "Instalar apps desconocidas" es un
 * permiso especial: Android obliga a concederlo a mano en Ajustes, por app,
 * no con un dialogo de permiso normal -- por eso [ensureInstallPermission]
 * existe: si falta, abre esa pantalla en vez de fallar en silencio.
 */
object ApkInstaller {

    /** true si ya se puede instalar sin pasar por Ajustes primero. */
    fun canInstall(context: Context): Boolean =
        context.packageManager.canRequestPackageInstalls()

    /** Lleva a la pantalla de Ajustes donde se activa "Instalar apps desconocidas"
     * para ESTA app en concreto (no es un permiso de todo el sistema). */
    fun requestInstallPermission(context: Context) {
        val intent = Intent(
            Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
            Uri.parse("package:${context.packageName}"),
        ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
    }

    /** Abre el instalador del sistema para [apk]. Necesita [canInstall] == true antes. */
    fun install(context: Context, apk: File) {
        val uri: Uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", apk)
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        context.startActivity(intent)
    }
}
