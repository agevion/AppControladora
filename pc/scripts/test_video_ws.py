"""El video de la ventana por WebRTC, haciendo de movil.

    python scripts/test_video_ws.py                # negociacion libre
    python scripts/test_video_ws.py --codec h264   # forzando H.264
    python scripts/test_video_ws.py --frames 90    # cuantos fotogramas recibir

Con el servicio arrancado. Monta la MISMA negociacion que hara la app Android
(oferta recvonly sin trickle, respuesta del PC con los candidatos dentro del
SDP), recibe video de verdad y guarda un fotograma en pc/artifacts/ para poder
mirarlo. Si esto pasa, lo que quede por hacer en Android es la interfaz, no el
transporte.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import ssl
import sys
import time
from pathlib import Path

from aiortc import RTCConfiguration, RTCPeerConnection, RTCRtpReceiver, RTCSessionDescription
from websockets.asyncio.client import connect

PC_DIR = Path(__file__).resolve().parent.parent
CERTS = PC_DIR / "certs"
CONFIG = json.loads((PC_DIR / "config.json").read_text(encoding="utf-8"))
ARTIFACTS = PC_DIR / "artifacts"

URI = f"wss://localhost:{CONFIG['port']}/ws"


def _ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(CERTS / "ca.crt"))
    ctx.load_cert_chain(str(CERTS / "client.crt"), str(CERTS / "client.key"))
    return ctx


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codec", default="", help="forzar un codec: h264 o vp8")
    ap.add_argument("--frames", type=int, default=60, help="cuantos fotogramas recibir")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # Sin iceServers, igual que el PC: por Tailscale (y aqui por localhost) los
    # candidatos host bastan. Si esto necesitara STUN, es que algo esta mal.
    pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    recibidos: list = []
    primer_frame = asyncio.get_running_loop().create_future()

    @pc.on("track")
    def _pista(track) -> None:
        print(f"  pista recibida: {track.kind}")

        async def leer() -> None:
            t0 = None
            while len(recibidos) < args.frames:
                frame = await track.recv()
                if t0 is None:
                    t0 = time.perf_counter()
                    if not primer_frame.done():
                        primer_frame.set_result(frame)
                recibidos.append(frame)
            fin = time.perf_counter()
            if t0 is not None and fin > t0:
                print(f"  {len(recibidos)} fotogramas a {(len(recibidos) - 1) / (fin - t0):.1f} fps")

        asyncio.ensure_future(leer())

    # recvonly: el movil solo mira, no manda camara ni microfono.
    transceptor = pc.addTransceiver("video", direction="recvonly")
    if args.codec:
        disponibles = RTCRtpReceiver.getCapabilities("video").codecs
        elegidos = [c for c in disponibles if args.codec.lower() in c.mimeType.lower()]
        if not elegidos:
            print(f"FALLO: este aiortc no ofrece {args.codec!r}")
            return 1
        transceptor.setCodecPreferences(elegidos)
        print(f"  forzando {[c.mimeType for c in elegidos]}")

    await pc.setLocalDescription(await pc.createOffer())
    # aiortc termina de recolectar candidatos DENTRO de setLocalDescription, asi
    # que este SDP ya los lleva: por eso no hace falta trickle (ver webrtc.py).
    print(f"  oferta lista ({len(pc.localDescription.sdp)} bytes de SDP)")

    async with connect(
        URI, ssl=_ctx(), additional_headers={"Authorization": f"Bearer {CONFIG['token']}"}
    ) as ws:
        hola = json.loads(await ws.recv())
        print(f"hello: version={hola['version']}")

        await ws.send(
            json.dumps({"type": "rtc.offer", "sdp": pc.localDescription.sdp, "tipo": "offer"})
        )

        respuesta = None
        limite = time.time() + 30
        while time.time() < limite:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            if msg["type"] == "error":
                print(f"  [error del PC] {msg['message']}")
                return 1
            if msg["type"] == "rtc.answer":
                respuesta = msg
                break
        if respuesta is None:
            print("FALLO: el PC no contesto con rtc.answer")
            return 1

        print(f"  respuesta recibida ({len(respuesta['sdp'])} bytes de SDP)")
        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=respuesta["sdp"], type=respuesta["tipo"])
        )

        try:
            frame = await asyncio.wait_for(primer_frame, timeout=30)
        except asyncio.TimeoutError:
            print(f"FALLO: no llego ningun fotograma (estado ICE: {pc.iceConnectionState})")
            await ws.send(json.dumps({"type": "rtc.stop"}))
            return 1

        print(f"  primer fotograma: {frame.width}x{frame.height}")

        # A esperar a que se llene la cuenta, para poder medir los fps de verdad.
        limite = time.time() + 30
        while len(recibidos) < args.frames and time.time() < limite:
            await asyncio.sleep(0.2)

        ARTIFACTS.mkdir(exist_ok=True)
        destino = ARTIFACTS / "video_recibido.png"
        recibidos[-1].to_image().save(destino)
        print(f"  ultimo fotograma guardado en {destino}")

        # Que codec acabo usandose de verdad. Importa: si negocia VP8 cuando
        # creiamos que iba H.264, el consumo del movil no sera el esperado.
        for t in pc.getTransceivers():
            if t.receiver and t.receiver.track and t.receiver.track.kind == "video":
                params = t.receiver.getParameters() if hasattr(t.receiver, "getParameters") else None
                if params and params.codecs:
                    print(f"  codec en uso: {params.codecs[0].mimeType}")

        await ws.send(json.dumps({"type": "rtc.stop"}))
        await asyncio.sleep(0.5)

    await pc.close()

    if len(recibidos) < args.frames:
        print(f"\nFALLO: solo llegaron {len(recibidos)} de {args.frames} fotogramas")
        return 1

    print("\nVideo por WebRTC: OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
