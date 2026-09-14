package com.controladora.movil

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import com.controladora.movil.ui.ChatScreen

class MainActivity : ComponentActivity() {

    // No hace nada con el resultado a proposito: si el usuario dice que no, el
    // socket sigue funcionando igual (ver ConnectionService), solo que sin
    // notificacion visible. No merece la pena bloquear ni insistir por eso.
    private val pedirNotificaciones =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        // Sin este permiso (API 33+) ConnectionService puede llamar a
        // startForeground() pero el aviso persistente no se veria: Android igual
        // deja correr el foreground service, solo oculta la notificacion.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED
        ) {
            pedirNotificaciones.launch(Manifest.permission.POST_NOTIFICATIONS)
        }

        setContent {
            ChatScreen()
        }
    }
}
