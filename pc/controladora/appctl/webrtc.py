"""Mandar la pantalla del PC al movil por WebRTC.

Hasta v15 esto mandaba solo la ventana de la app de escritorio de Claude, a
proposito: "no se manda el escritorio entero como haria un AnyDesk". Esa
decision se revirtio en v16 -- Ale la pidio explicitamente como "de toda la
pantalla, como si fuese un AnyDesk" -- asi que ahora si se manda el monitor
entero que el movil elija, con el mismo derecho a moverse a otro. Ver
appctl/pantallas.py (la lista de monitores) y appctl/pantalla_input.py (el
control global que va con este video).

**Sin STUN y sin TURN, a proposito.** ARQUITECTURA.md 3 decia que el P2P iria
directo por la IP publica; eso se escribio antes de que Tailscale sustituyera al
port forward (4.1). Con Tailscale los dos extremos ya se ven por su IP `100.x`,
asi que a aiortc le basta con sus candidatos *host*: no hace falta un servidor
STUN que descubra nada ni un TURN que retransmita. Menos piezas, y ninguna fuera
de la red privada.

**Senalizacion sin trickle.** aiortc termina de recolectar candidatos DENTRO de
`setLocalDescription`, asi que la respuesta que sale de aqui ya lleva todos los
candidatos dentro del SDP. Si el movil hace lo mismo (esperar a que su
recoleccion termine antes de mandar la oferta), sobran los mensajes `rtc.ice`
sueltos: una oferta, una respuesta y a correr. Menos estados que sincronizar y
menos formas de quedarse a medias.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import numpy as np
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import VideoStreamTrack
from av import VideoFrame
from av.video.reformatter import Interpolation

from . import capture, despierto, pantallas

log = logging.getLogger("controladora.appctl.webrtc")

# A cuanto se reduce el monitor antes de codificar. Se conserva la proporcion,
# asi que lo que se ve es la pantalla entera, no un recorte.
#
# Estaba en 1280 con el argumento de que "para leer texto en un movil sobra".
# No sobraba: la ventana son 1936 px, o sea que se tiraba un tercio del ancho
# ANTES de codificar, y ese tercio es justo el detalle que distingue una letra de
# otra cuando acercas la imagen. Medido en este PC, subirlo cuesta poco:
#
#     ancho 1280 -> 13,5 ms/fotograma (techo 74 fps)
#     ancho 1600 -> 15,4 ms/fotograma (techo 65 fps)
#     ancho 1920 -> 17,2 ms/fotograma (techo 58 fps)
#
# 1600 es el punto medio: casi 2 ms mas que antes, con techo de sobra sobre los
# 30 fps del objetivo. Y el gasto solo se paga cuando la imagen CAMBIA -- una
# pantalla quieta esta quieta casi siempre y esos fotogramas ni se reconvierten
# (ver _PistaCaptura.recv).
ANCHO_MAX = 1600

# Lo que de verdad hacia que el video se viera "como una tele vieja" no era la
# resolucion: era el bitrate. aiortc arranca H.264 a 1 Mbps y no pasa de 3, unos
# valores pensados para una webcam por internet. Esto no es una webcam: es TEXTO,
# que es lo que peor lleva la compresion (los bordes duros se deshacen en
# bloques), y no va por internet sino por Tailscale, casi siempre por la red de
# casa. Ahi 6 Mbps no se notan.
#
# Se toca subiendo las constantes del modulo del codec porque es el unico mando
# que aiortc expone: el bitrate real lo decide su estimador a partir del REMB que
# manda el movil, y lo unico que se puede hacer desde fuera es mover el SUELO y
# el TECHO entre los que ese estimador se mueve (`target_bitrate` recorta contra
# MIN/MAX en cada ajuste). Subir el suelo es lo que evita que se quede clavado
# abajo al arrancar, que es cuando se ve peor.
#
# El riesgo, dicho claro: son constantes internas de aiortc, no una API publica.
# Si una version futura las renombra, esto deja de aplicarse -- por eso va en un
# try/except que no rompe el video, solo lo deja como estaba.
BITRATE_MIN = 3_000_000
BITRATE_INICIAL = 6_000_000
BITRATE_MAX = 10_000_000


def _subir_bitrate() -> None:
    """Ensancha la horquilla de bitrate del codec. Ver BITRATE_* arriba."""
    try:
        from aiortc.codecs import h264, vpx

        h264.MIN_BITRATE = BITRATE_MIN
        h264.DEFAULT_BITRATE = BITRATE_INICIAL
        h264.MAX_BITRATE = BITRATE_MAX
        # Por si la negociacion acaba en VP8: sus topes son aun mas bajos que los
        # de H.264 (500 kbps de salida, 1,5 Mbps de tope).
        vpx.MIN_BITRATE = BITRATE_MIN
        vpx.DEFAULT_BITRATE = BITRATE_INICIAL
        vpx.MAX_BITRATE = BITRATE_MAX
        log.info(
            "bitrate de video: %.1f-%.1f Mbps (arranca en %.1f)",
            BITRATE_MIN / 1e6,
            BITRATE_MAX / 1e6,
            BITRATE_INICIAL / 1e6,
        )
    except Exception as e:
        log.warning(
            "no pude subir el bitrate de aiortc (%s: %s). El video seguira "
            "funcionando, pero con la calidad de fabrica.",
            type(e).__name__,
            e,
        )

# Bilineal y no bicubica: se midieron las cinco que ofrece swscale y todas salen
# igual (~30 fps), porque lo caro no es el filtro sino pasar de BGRA a YUV. Entre
# iguales, la bilineal es la que mejor deja el texto pequeno sin costar mas.
INTERPOLACION = Interpolation.BILINEAR


# Los codificadores de video trabajan en bloques: una dimension impar hace que
# H.264 falle o recorte una fila. Todo se redondea a par.
def _par(n: int) -> int:
    return n - (n % 2)


class PistaPantalla(VideoStreamTrack):
    """Un monitor del PC como pista de video.

    `VideoStreamTrack.next_timestamp` ya marca el ritmo de 30 fps (duerme lo que
    haga falta), asi que aqui no hay que temporizar nada a mano.

    Mas simple que la vieja `PistaVentana` que sustituye: una ventana se podia
    minimizar, ocultar o cerrar y volver a abrirse con otro HWND, asi que hacia
    falta un vigilante que la persiguiera. Un monitor no hace nada de eso -- como
    mucho se desconecta, y entonces solo hay que repetir el ultimo fotograma y
    avisar en el log, no perseguir nada.
    """

    kind = "video"

    def __init__(self, p: pantallas.Pantalla) -> None:
        super().__init__()
        self._p = p
        self._captura = capture.abrir(p)
        self._ultimo_crudo: np.ndarray | None = None
        self._ultimo_frame: VideoFrame | None = None
        self._quieta_desde = time.monotonic()
        self._ultima_parte = 0.0
        self._quieta_avisada = False

    async def recv(self) -> VideoFrame:
        pts, base = await self.next_timestamp()

        # La captura es GDI: bloquea. Fuera del bucle de eventos, o se atasca
        # todo lo demas que atiende el servidor.
        arr = await asyncio.to_thread(self._captura.frame)

        if arr is None:
            # El monitor se desconecto o el BitBlt fallo por lo que sea. NO es
            # motivo para cortar el video: se repite el ultimo fotograma bueno
            # (o negro si aun no hay ninguno) y se sigue.
            arr = self._ultimo_crudo
            self._avisar_quieta("no pude capturar %s" % self._p.id, grave=True)

        # Una pantalla de escritorio esta QUIETA la mayor parte del tiempo, y
        # convertir de BGRA a YUV cuesta ~12 ms tanto si ha cambiado algo como
        # si no -- mas que la captura y muchisimo mas que codificar. Comparar
        # los dos bufers cuesta ~1 ms y ahorra todo eso cuando no hay nada
        # nuevo. El fotograma se reemite igual (WebRTC necesita su ritmo); lo
        # que se salta es rehacer el que ya estaba hecho.
        if (
            arr is not None
            and self._ultimo_frame is not None
            and self._ultimo_crudo is not None
            and arr.shape == self._ultimo_crudo.shape
            and np.array_equal(arr, self._ultimo_crudo)
        ):
            self._avisar_quieta("", grave=False)
            self._ultimo_frame.pts = pts
            self._ultimo_frame.time_base = base
            return self._ultimo_frame

        if self._quieta_avisada:
            log.info("el video de %s volvio a moverse", self._p.id)
            self._quieta_avisada = False
        self._quieta_desde = time.monotonic()

        if arr is None:
            arr = np.zeros((720, 1280, 4), dtype=np.uint8)

        # "bgra" y no "bgr24": la captura entrega el bufer de GDI entero y
        # contiguo justamente para poder entrar por aqui sin copiar nada. El
        # canal de relleno lo tira swscale al pasar a YUV. Ver capture.frame().
        frame = VideoFrame.from_ndarray(arr, format="bgra")

        alto, ancho = arr.shape[:2]
        if ancho > ANCHO_MAX:
            nuevo_alto = _par(round(alto * ANCHO_MAX / ancho))
            frame = frame.reformat(
                width=ANCHO_MAX, height=nuevo_alto, interpolation=INTERPOLACION
            )
        elif ancho % 2 or alto % 2:
            frame = frame.reformat(width=_par(ancho), height=_par(alto))

        # `arr` apunta al bufer que GDI reescribe en la siguiente captura, asi
        # que hay que quedarse con una COPIA para poder compararla. Sin esto la
        # comparacion de arriba seria siempre cierta y el video se congelaria.
        self._ultimo_crudo = arr.copy()
        self._ultimo_frame = frame

        frame.pts = pts
        frame.time_base = base
        return frame

    def _avisar_quieta(self, que: str, grave: bool) -> None:
        """Deja constancia en el log si lleva rato quieta, sin inundarlo.

        Una pantalla de escritorio quieta es lo normal, asi que no se avisa
        hasta que pasa un rato (ver despierto.inactividad como referencia de lo
        que es "normal"), y despues solo una vez por minuto.
        """
        ahora = time.monotonic()
        if ahora - self._quieta_desde < 5.0:
            return
        if self._quieta_avisada and ahora - self._ultima_parte < 60.0:
            return
        self._quieta_avisada = True
        self._ultima_parte = ahora
        log.log(
            logging.WARNING if grave else logging.INFO,
            "video de %s quieto %.0fs%s | inactividad del PC=%.0fs",
            self._p.id,
            ahora - self._quieta_desde,
            f" | {que}" if que else "",
            despierto.inactividad(),
        )

    def stop(self) -> None:  # lo llama aiortc al cerrar la conexion
        try:
            self._captura.cerrar()
        finally:
            super().stop()


class Emisor:
    """El video de UNA conexion del movil. Una instancia por Session.

    Solo hay una conexion viva a la vez: pedir una oferta nueva tira la anterior.
    Es lo correcto -- si el movil renegocia (cambio de red, cambio de monitor, la
    app volvio de segundo plano), lo que quiere es empezar de cero, no acumular
    emisores codificando video para un socket que ya no existe.
    """

    def __init__(self) -> None:
        self._pc: RTCPeerConnection | None = None
        # Si esta conexion tiene pedido que la pantalla no se apague. Se lleva
        # aqui y no dentro de `despierto` porque lo que hay que soltar al cerrar
        # es EXACTAMENTE lo que se pidio al abrir, ni mas ni menos: dos moviles
        # mirando a la vez son dos peticiones, y que se vaya uno no puede apagar
        # la pantalla al otro.
        self._despierto = False

    @property
    def activo(self) -> bool:
        return self._pc is not None

    async def oferta(self, sdp: str, tipo: str, monitor: str | None) -> dict[str, Any]:
        """Recibe la oferta del movil y devuelve la respuesta, ya con candidatos.

        [monitor] es el `id` de `pantallas.listar()` a capturar; si no llega o
        ya no existe, se cae al monitor principal (ver `pantallas.buscar`).
        """
        p = await asyncio.to_thread(pantallas.buscar, monitor)
        if p is None:
            raise RuntimeError("no hay ningun monitor que capturar")

        await self.cerrar()

        # Antes de crear la conexion: el codificador lee estas constantes al
        # construirse, asi que tocarlas despues no serviria de nada.
        _subir_bitrate()

        # Sin iceServers: los candidatos host que da Tailscale bastan (ver el
        # docstring del modulo). Poner un STUN publico aqui seria mandar trafico
        # fuera de la red privada para descubrir algo que ya sabemos.
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self._pc = pc

        @pc.on("connectionstatechange")
        async def _estado() -> None:
            log.info("video: conexion %s", pc.connectionState)
            if pc.connectionState in ("failed", "closed"):
                await self.cerrar()

        pc.addTrack(PistaPantalla(p))

        # Mientras el movil mire, el PC cuenta como en uso. Sin esto, Windows
        # apaga la pantalla por inactividad -- los toques del movil no cuentan
        # como actividad -- y con la pantalla apagada deja de haber nada que
        # capturar. Ver despierto.py, que lo explica entero.
        #
        # Va aqui y no en un hilo aparte porque el flag es POR HILO: esto corre
        # en el bucle de eventos, que vive lo que vive el servidor.
        despierto.pedir()
        self._despierto = True

        await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=tipo))
        respuesta = await pc.createAnswer()
        # Aqui dentro es donde aiortc termina de recolectar los candidatos, asi
        # que el SDP que se lee DESPUES ya los lleva todos.
        await pc.setLocalDescription(respuesta)

        log.info("video: emitiendo la pantalla %r", p.id)
        return {"sdp": pc.localDescription.sdp, "tipo": pc.localDescription.type}

    async def cerrar(self) -> None:
        if self._despierto:
            # Antes de nada: si la conexion se fue, el motivo para tener la
            # pantalla encendida se fue con ella, falle lo que falle mas abajo.
            self._despierto = False
            despierto.soltar()

        pc, self._pc = self._pc, None
        if pc is None:
            return
        try:
            await pc.close()
        except Exception as e:
            log.debug("cerrando el video: %s", e)
