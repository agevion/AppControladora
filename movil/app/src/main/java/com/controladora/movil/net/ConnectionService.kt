package com.controladora.movil.net

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Binder
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.controladora.movil.ChatStore
import com.controladora.movil.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Aloja el [ControladoraClient] fuera del ViewModel: antes vivia atado al
 * `viewModelScope` de ChatViewModel, que muere con la Activity, asi que Android
 * podia matar el proceso (y el socket con el) en cuanto la app pasaba a segundo
 * plano un rato — justo el caso de "cambio a Spotify a poner musica y quiero
 * que Controladora siga conectada".
 *
 * Mientras hay algo que mantener vivo llamamos [android.content.Context.startForegroundService]
 * y esto se pone en foreground con una notificacion persistente: eso sube la
 * prioridad del proceso ante el sistema y evita que lo mate por estar en
 * background. Se para (deja de ser foreground) solo cuando el usuario pulsa
 * "Desconectar" a mano — la reconexion por perdida real de red la sigue
 * gestionando [ControladoraClient] con su propio backoff, sin rendirse nunca.
 */
class ConnectionService : Service() {

    inner class LocalBinder : Binder() {
        val client: ControladoraClient get() = this@ConnectionService.client
        val store: ChatStore get() = this@ConnectionService.store
        val video: VideoCliente get() = this@ConnectionService.video
        fun dejarDeSerPersistente() = this@ConnectionService.dejarDeSerPersistente()
    }

    private val binder = LocalBinder()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private lateinit var client: ControladoraClient
    private lateinit var store: ChatStore
    private lateinit var video: VideoCliente

    override fun onCreate() {
        super.onCreate()
        client = ControladoraClient(applicationContext, scope)
        // El historial vive aqui, no en el ViewModel: si escuchara el ViewModel,
        // todo lo que llegase con la Activity destruida se descartaria en silencio
        // (ControladoraClient.events es un SharedFlow con replay = 0). Ver ChatStore.
        store = ChatStore(applicationContext, client, scope)
        // El video tambien vive aqui y no en el ViewModel, pero por otro motivo:
        // el motor de WebRTC y su contexto de OpenGL son caros de crear y no
        // pueden nacer y morir con cada rotacion de pantalla.
        video = VideoCliente(applicationContext, client, scope)
        createChannel()
        scope.launch {
            client.state.collect { estado ->
                notify(textoPara(estado))
                // Si se cae el socket, la conexion de video tambien esta muerta:
                // su señalizacion iba por ahi. Dejarla "viendo" solo serviria
                // para enseñar una imagen congelada como si fuera lo que hay
                // ahora mismo en el PC.
                if (estado !is Conn.Online) video.parar()
            }
        }
        scope.launch {
            client.events.collect { msg ->
                if (msg is ServerMsg.RtcAnswer) video.recibirRespuesta(msg.sdp, msg.tipo)
                // Texto copiado en el PC con la app guardada en el bolsillo. No se
                // puede meter en el portapapeles desde aquí (Android sólo deja
                // tocarlo en primer plano), así que lo único honrado es avisar:
                // al abrir la app se copia solo. Sin este aviso, el traspaso de
                // texto sólo funcionaría cuando ya estuvieras mirando la app --
                // justo cuando menos falta hace.
                if (msg is ServerMsg.ClipText && msg.text.isNotEmpty() && !store.enPrimerPlano.value) {
                    avisarPortapapeles(msg.text)
                }
            }
        }
    }

    override fun onBind(intent: Intent?): IBinder = binder

    /** Lo llama ChatViewModel.connect() vía startForegroundService(): sube la
     * prioridad del proceso YA, antes de que el socket termine de abrir. */
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(NOTIF_ID, buildNotification("Conectando…"))
        return START_STICKY
    }

    /** Lo llama ChatViewModel.disconnect(): quita la notificacion persistente,
     * el servicio se queda vivo pero deja de proteger el proceso. */
    fun dejarDeSerPersistente() {
        stopForeground(STOP_FOREGROUND_REMOVE)
    }

    override fun onDestroy() {
        client.disconnect()
        video.soltar()
        scope.cancel()
        super.onDestroy()
    }

    private fun textoPara(estado: Conn): String = when (estado) {
        is Conn.Online -> "Conectado al PC"
        is Conn.Connecting -> "Conectando…"
        is Conn.Offline -> "Desconectado"
        is Conn.Failed -> "Sin conexión — reintentando…"
    }

    private fun notify(texto: String) {
        val nm = getSystemService(NotificationManager::class.java) ?: return
        nm.notify(NOTIF_ID, buildNotification(texto))
    }

    private fun buildNotification(texto: String): Notification {
        val openApp = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Controladora")
            .setContentText(texto)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentIntent(openApp)
            .setOngoing(true)
            .setSilent(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    /** El aviso de "hay texto del PC esperando". Se reemplaza a sí mismo (mismo
     * id): lo que interesa es lo último que se copió, no una lista de avisos. */
    private fun avisarPortapapeles(texto: String) {
        val nm = getSystemService(NotificationManager::class.java) ?: return
        val abrir = PendingIntent.getActivity(
            this,
            1,
            Intent(this, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE,
        )
        // Los saltos de linea se aplanan: en una notificacion no se ven, y un
        // texto de varias lineas quedaria cortado en la primera sin decirlo.
        val resumen = texto.lines().joinToString(" ") { it.trim() }.trim().take(120)
        val aviso = NotificationCompat.Builder(this, CANAL_CLIP)
            .setContentTitle("Texto copiado en el PC")
            .setContentText(resumen)
            .setStyle(NotificationCompat.BigTextStyle().bigText(resumen))
            .setSubText("Abre Controladora para tenerlo en el portapapeles")
            .setSmallIcon(android.R.drawable.ic_menu_edit)
            .setContentIntent(abrir)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .build()
        nm.notify(NOTIF_CLIP, aviso)
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val nm = getSystemService(NotificationManager::class.java) ?: return
        val canal = NotificationChannel(
            CHANNEL_ID,
            "Conexión con el PC",
            NotificationManager.IMPORTANCE_LOW,
        ).apply { description = "Aviso persistente mientras Controladora está conectada en segundo plano" }
        nm.createNotificationChannel(canal)

        // Canal aparte y con importancia normal: el de la conexión es LOW a
        // propósito (no debe sonar nunca), pero este sí tiene que verse en el
        // momento -- es lo que convierte "el PC ya te lo mandó" en algo que se
        // nota sin abrir la app. Al ser otro canal, se puede silenciar sin
        // silenciar el otro.
        nm.createNotificationChannel(
            NotificationChannel(
                CANAL_CLIP,
                "Texto copiado en el PC",
                NotificationManager.IMPORTANCE_DEFAULT,
            ).apply { description = "Avisa cuando se copia texto en el PC y está esperando a pasar al portapapeles" },
        )
    }

    companion object {
        private const val NOTIF_ID = 1
        private const val CHANNEL_ID = "conexion"
        private const val NOTIF_CLIP = 2
        private const val CANAL_CLIP = "portapapeles"
    }
}
