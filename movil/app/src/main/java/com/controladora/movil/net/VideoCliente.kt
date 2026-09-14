package com.controladora.movil.net

import android.content.Context
import android.os.SystemClock
import android.util.Log
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import kotlin.coroutines.resume
import org.webrtc.DefaultVideoDecoderFactory
import org.webrtc.DefaultVideoEncoderFactory
import org.webrtc.EglBase
import org.webrtc.IceCandidate
import org.webrtc.MediaConstraints
import org.webrtc.MediaStream
import org.webrtc.PeerConnection
import org.webrtc.PeerConnectionFactory
import org.webrtc.RtpReceiver
import org.webrtc.RtpTransceiver
import org.webrtc.SdpObserver
import org.webrtc.SessionDescription
import org.webrtc.VideoTrack

private const val TAG = "ControladoraVideo"

/** Cada cuánto se le pregunta al motor si la imagen sigue avanzando. */
private const val VIGILANCIA_MS = 2_000L

/**
 * Cuánto se aguanta sin un solo fotograma decodificado antes de dar el vídeo por
 * colgado y renegociar.
 *
 * No confundirlo con "la pantalla del PC no cambia": aunque la ventana esté
 * completamente quieta, el PC sigue mandando fotogramas (repite el último a 30
 * fps) y `framesDecoded` sigue subiendo. Que ese contador se pare significa que
 * no llega imagen o que el decodificador se atascó, y de eso no se sale solo.
 *
 * 8 s es de sobra generoso para un bache de red o un rato en segundo plano, y
 * corto comparado con lo que costaba hasta ahora salir de ahí: levantarse a
 * tocar el PC.
 */
private const val TOPE_CONGELADO_MS = 8_000L

/** Mínimo entre dos renegociaciones seguidas, para no entrar en bucle. */
private const val ENTRE_REINTENTOS_MS = 20_000L

/** En que punto esta el vídeo de la ventana del PC. */
sealed interface Video {
    data object Parado : Video
    data object Negociando : Video
    data class Viendo(val track: VideoTrack) : Video
    data class Fallo(val motivo: String) : Video
}

/**
 * Recibe por WebRTC el vídeo de un monitor del PC (pantalla completa, v16).
 *
 * **Sin servidores ICE, a propósito.** El PC y el móvil ya se ven por su IP
 * `100.x` de Tailscale, así que los candidatos *host* bastan: no hace falta un
 * STUN que descubra la IP pública ni un TURN que retransmita. Es una pieza menos
 * y, sobre todo, ni un byte de esto sale de la red privada.
 *
 * **Sin trickle.** Se espera a que la recolección de candidatos TERMINE antes de
 * mandar la oferta, así que viajan dentro del SDP. El PC hace lo mismo (aiortc
 * los recolecta dentro de `setLocalDescription`). Una oferta, una respuesta y ya:
 * ningún mensaje `rtc.ice` suelto y ningún estado a medias que sincronizar.
 *
 * Sólo se RECIBE vídeo: no se pide cámara ni micrófono, así que la app no
 * necesita esos permisos de Android para nada.
 */
class VideoCliente(
    private val context: Context,
    private val cliente: ControladoraClient,
    private val scope: CoroutineScope,
) {
    private val _estado = MutableStateFlow<Video>(Video.Parado)
    val estado: StateFlow<Video> = _estado.asStateFlow()

    /** El contexto de OpenGL que comparten el decodificador y el `SurfaceViewRenderer`. */
    val egl: EglBase = EglBase.create()

    private var factory: PeerConnectionFactory? = null
    private var pc: PeerConnection? = null

    /** El vigilante de imagen congelada (ver [vigilar]). */
    private var vigilante: Job? = null
    private var ultimoReintento = 0L

    /** El monitor que se está pidiendo, para poder renegociar (vigilante,
     * reconexión) sin que quien llama tenga que repetirlo cada vez. */
    private var monitorActual: String = ""

    private fun factoria(): PeerConnectionFactory =
        factory ?: run {
            PeerConnectionFactory.initialize(
                PeerConnectionFactory.InitializationOptions.builder(context)
                    .createInitializationOptions(),
            )
            PeerConnectionFactory.builder()
                // El de por defecto usa el decodificador por hardware del móvil
                // cuando existe: es la diferencia entre 30 fps sin despeinarse y
                // fundir la batería decodificando H.264 en software.
                .setVideoDecoderFactory(DefaultVideoDecoderFactory(egl.eglBaseContext))
                .setVideoEncoderFactory(DefaultVideoEncoderFactory(egl.eglBaseContext, true, true))
                .createPeerConnectionFactory()
                .also { factory = it }
        }

    /**
     * Empieza (o reinicia) el vídeo de [monitor] (el `id` de una [Pantalla] de
     * `screens.result`). Idempotente: una llamada nueva tira la anterior --
     * incluido cambiar de monitor sin parar antes, que es justo cómo el
     * selector de la pestaña App pide un cambio.
     */
    fun empezar(monitor: String) {
        monitorActual = monitor
        scope.launch {
            parar()
            _estado.value = Video.Negociando
            try {
                negociar()
                vigilar()
            } catch (e: Exception) {
                Log.w(TAG, "no pude arrancar el vídeo", e)
                _estado.value = Video.Fallo("${e.javaClass.simpleName}: ${e.message}")
            }
        }
    }

    /**
     * Renegocia solo si la imagen se queda congelada.
     *
     * **Por qué hace falta.** Una imagen que no avanza no rompe nada de lo que
     * WebRTC vigila por su cuenta: ICE sigue conectado, `onConnectionChange` no
     * dispara y el `SurfaceViewRenderer` sigue enseñando tan tranquilo el último
     * fotograma que le llegó. Desde fuera es indistinguible de una pantalla del
     * PC que no cambia. Hasta ahora la única forma de salir de ahí era ir al PC
     * y tocarlo, y eso convierte a un escritorio remoto en la pieza sin la cual
     * esta aplicación no funciona.
     *
     * `framesDecoded` es el testigo correcto porque sube incluso con la ventana
     * del PC totalmente quieta (ver [TOPE_CONGELADO_MS]). Si deja de subir, el
     * atasco está en el transporte o en el decodificador — y de esos dos sí se
     * sale renegociando de cero.
     *
     * Lo que este vigilante **no** cubre, y es a propósito: que el PC mande
     * fotogramas nuevos pero todos iguales porque su ventana dejó de pintarse.
     * Eso no se ve desde aquí (los contadores suben con normalidad) y se detecta
     * en el PC, que es donde se puede arreglar — `appctl/webrtc.py`.
     */
    private fun vigilar() {
        vigilante?.cancel()
        vigilante = scope.launch {
            var ultimos = -1L
            var desde = SystemClock.elapsedRealtime()

            while (isActive) {
                delay(VIGILANCIA_MS)
                val conexion = pc ?: break
                val ahora = SystemClock.elapsedRealtime()

                // Sin pista todavía (o ya parado) no hay nada que vigilar, y el
                // contador se rearma: si no, el tiempo de la negociación contaría
                // como tiempo congelado.
                if (_estado.value !is Video.Viendo) {
                    ultimos = -1L
                    desde = ahora
                    continue
                }

                val frames = framesDecodificados(conexion) ?: continue
                if (ultimos < 0 || frames != ultimos) {
                    ultimos = frames
                    desde = ahora
                    continue
                }

                if (ahora - desde < TOPE_CONGELADO_MS) continue

                if (ahora - ultimoReintento < ENTRE_REINTENTOS_MS) {
                    // Ya se reintentó hace nada y sigue igual: el problema no es
                    // la conexión. Insistir cada dos segundos sólo cambiaría una
                    // imagen congelada por un parpadeo permanente.
                    Log.w(TAG, "el vídeo sigue congelado tras renegociar; espero antes de repetir")
                    continue
                }

                Log.w(
                    TAG,
                    "vídeo congelado: ${(ahora - desde) / 1000}s sin decodificar un solo " +
                        "fotograma (van $frames). Renegocio.",
                )
                ultimoReintento = ahora
                // Se suelta ANTES de llamar a empezar(): esa llamada pasa por
                // parar(), que cancelaría este mismo Job a media frase.
                vigilante = null
                empezar(monitorActual)
                break
            }
        }
    }

    /** Cuántos fotogramas lleva decodificados la pista de vídeo. null si no se sabe. */
    private suspend fun framesDecodificados(conexion: PeerConnection): Long? =
        withTimeoutOrNull(VIGILANCIA_MS) {
            suspendCancellableCoroutine { cont ->
                conexion.getStats { informe ->
                    val entrante = informe.statsMap.values.firstOrNull {
                        it.type == "inbound-rtp" &&
                            (it.members["kind"] == "video" || it.members["mediaType"] == "video")
                    }
                    val n = entrante?.members?.get("framesDecoded") as? Number
                    if (cont.isActive) cont.resume(n?.toLong())
                }
            }
        }

    private suspend fun negociar() {
        val recolectado = CompletableDeferred<Unit>()

        // Lista de servidores ICE vacía: los candidatos host de Tailscale bastan
        // (ver el comentario de la clase).
        val config = PeerConnection.RTCConfiguration(emptyList()).apply {
            sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
        }

        val conexion = factoria().createPeerConnection(config, object : PeerConnection.Observer {
            override fun onIceGatheringChange(estado: PeerConnection.IceGatheringState) {
                Log.i(TAG, "recolección ICE: $estado")
                if (estado == PeerConnection.IceGatheringState.COMPLETE) recolectado.complete(Unit)
            }

            override fun onTrack(transceiver: RtpTransceiver) {
                val track = transceiver.receiver?.track()
                if (track is VideoTrack) {
                    Log.i(TAG, "pista de vídeo recibida")
                    _estado.value = Video.Viendo(track)
                }
            }

            override fun onConnectionChange(nuevo: PeerConnection.PeerConnectionState) {
                Log.i(TAG, "conexión: $nuevo")
                when (nuevo) {
                    PeerConnection.PeerConnectionState.FAILED ->
                        _estado.value = Video.Fallo("la conexión de vídeo falló")
                    PeerConnection.PeerConnectionState.CLOSED ->
                        if (_estado.value !is Video.Fallo) _estado.value = Video.Parado
                    else -> Unit
                }
            }

            override fun onIceCandidate(candidate: IceCandidate?) = Unit
            override fun onIceCandidatesRemoved(candidates: Array<out IceCandidate>?) = Unit
            override fun onSignalingChange(state: PeerConnection.SignalingState?) = Unit
            override fun onIceConnectionChange(state: PeerConnection.IceConnectionState?) = Unit
            override fun onIceConnectionReceivingChange(receiving: Boolean) = Unit
            override fun onAddStream(stream: MediaStream?) = Unit
            override fun onRemoveStream(stream: MediaStream?) = Unit
            override fun onDataChannel(channel: org.webrtc.DataChannel?) = Unit
            override fun onRenegotiationNeeded() = Unit
            override fun onAddTrack(receiver: RtpReceiver?, streams: Array<out MediaStream>?) = Unit
        }) ?: throw IllegalStateException("no se pudo crear la conexión de vídeo")

        pc = conexion

        // Sólo mirar: ni cámara ni micrófono, así que ni permisos ni ventana de
        // "esta app quiere usar la cámara" que no vendría a cuento.
        conexion.addTransceiver(
            org.webrtc.MediaStreamTrack.MediaType.MEDIA_TYPE_VIDEO,
            RtpTransceiver.RtpTransceiverInit(RtpTransceiver.RtpTransceiverDirection.RECV_ONLY),
        )

        val oferta = crearOferta(conexion)
        fijarLocal(conexion, oferta)

        // Aquí está la clave de "sin trickle": no se manda nada hasta que la
        // recolección termina, para que los candidatos vayan dentro del SDP. Con
        // tope, porque una recolección que no termina nunca no puede dejar el
        // botón colgado para siempre — se manda lo que haya, que en una red
        // local suele estar completo mucho antes.
        withTimeoutOrNull(5_000) { recolectado.await() }

        val sdpFinal = conexion.localDescription?.description
            ?: throw IllegalStateException("la oferta se quedó sin SDP")

        if (!cliente.enviarOfertaVideo(sdpFinal, monitorActual)) {
            throw IllegalStateException("no hay conexión con el PC")
        }
    }

    /** Le pasa al motor la respuesta del PC (llega por `rtc.answer`). */
    fun recibirRespuesta(sdp: String, tipo: String) {
        val conexion = pc ?: return
        val tipoSdp =
            if (tipo.equals("answer", true)) SessionDescription.Type.ANSWER
            else SessionDescription.Type.PRANSWER
        conexion.setRemoteDescription(
            observador("setRemoteDescription") {
                _estado.value = Video.Fallo("el PC contestó algo que no entiendo: $it")
            },
            SessionDescription(tipoSdp, sdp),
        )
    }

    fun parar() {
        vigilante?.cancel()
        vigilante = null
        pc?.let {
            try {
                it.close()
            } catch (e: Exception) {
                Log.w(TAG, "cerrando el vídeo", e)
            }
        }
        pc = null
        if (_estado.value !is Video.Fallo) _estado.value = Video.Parado
        cliente.pararVideo()
    }

    fun soltar() {
        parar()
        factory?.dispose()
        factory = null
        egl.release()
    }

    // -- azúcar sobre la API de callbacks de WebRTC ---------------------------

    private suspend fun crearOferta(conexion: PeerConnection): SessionDescription {
        val hecho = CompletableDeferred<SessionDescription>()
        conexion.createOffer(
            object : SdpObserver {
                override fun onCreateSuccess(sdp: SessionDescription) {
                    hecho.complete(sdp)
                }

                override fun onCreateFailure(error: String?) {
                    hecho.completeExceptionally(IllegalStateException("createOffer: $error"))
                }

                override fun onSetSuccess() = Unit
                override fun onSetFailure(error: String?) = Unit
            },
            MediaConstraints(),
        )
        return hecho.await()
    }

    private suspend fun fijarLocal(conexion: PeerConnection, sdp: SessionDescription) {
        val hecho = CompletableDeferred<Unit>()
        conexion.setLocalDescription(
            object : SdpObserver {
                override fun onSetSuccess() {
                    hecho.complete(Unit)
                }

                override fun onSetFailure(error: String?) {
                    hecho.completeExceptionally(IllegalStateException("setLocalDescription: $error"))
                }

                override fun onCreateSuccess(sdp: SessionDescription?) = Unit
                override fun onCreateFailure(error: String?) = Unit
            },
            sdp,
        )
        hecho.await()
    }

    private fun observador(que: String, alFallar: (String) -> Unit) = object : SdpObserver {
        override fun onSetSuccess() {
            Log.i(TAG, "$que ok")
        }

        override fun onSetFailure(error: String?) {
            Log.w(TAG, "$que falló: $error")
            alFallar(error ?: "sin detalle")
        }
        override fun onCreateSuccess(sdp: SessionDescription?) = Unit
        override fun onCreateFailure(error: String?) = Unit
    }
}
