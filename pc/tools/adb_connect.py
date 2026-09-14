"""Reconecta adb al movil por su IP de Tailscale, en modo TCP/IP fijo.

El descubrimiento inalambrico normal de Android (adb-tls-connect, por mDNS) solo
funciona dentro de la misma LAN: no cruza Tailscale. El modo tcpip con puerto fijo
si es una conexion TCP directa, y esa si viaja por Tailscale igual que el resto
del sistema. Se puede resetear si el movil reinicia o si tocas el interruptor de
depuracion inalambrica; esta tool es para no tener que enchufar el cable otra vez
cuando eso pase.

La IP y el puerto viven en paths.json (clave "phone"), no aqui. Si cambias de
movil o de IP, se edita ahi -- no hay ninguna constante que buscar en este fichero.
"""

from __future__ import annotations

from _util import run_process
from controladora import paths

SPEC = {
    "name": "adb_connect",
    "description": (
        "Reconecta adb al movil por su IP de Tailscale (modo TCP/IP, puerto fijo). "
        "Usalo si adb_devices no ve el movil, o si necesitas comprobar por que no conecta."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "ip": {
                "type": "string",
                "description": "IP de Tailscale del movil. Si no la pasas, se usa la de paths.json (phone.tailscale_ip).",
            },
        },
        "required": [],
    },
}

CONFIRM = False


def run(ip: str = "") -> str:
    adb = paths.binary("adb")
    if not adb:
        return "adb no configurado en paths.json (bin.adb)"

    cfg = paths.phone()
    destino = ip.strip() or cfg.get("tailscale_ip", "")
    puerto = cfg.get("adb_port", 5555)

    if not destino:
        return (
            "No hay IP de movil configurada. Anadela en pc/paths.json, clave "
            '"phone": {"tailscale_ip": "100.x.y.z", ...} -- la ves en el movil en '
            "Tailscale (icono de la app) o en Ajustes de red > VPN > Tailscale."
        )

    # 25s y no menos: el propio timeout de socket de Windows para un host que
    # no responde (WSAETIMEDOUT) se ha medido en ~21s. Con menos margen, esta
    # tool corta el proceso ANTES de que adb imprima su mensaje real (10060),
    # y el usuario ve un generico "no termino a tiempo" en vez del diagnostico.
    code, out = run_process([adb, "connect", f"{destino}:{puerto}"], timeout=25)
    salida = out.strip()
    baja = salida.lower()

    if "connected to" in baja or "already connected" in baja:
        return f"Conectado a {destino}:{puerto}\n\n{salida}"

    # OJO: en Windows en espanol, adb NO devuelve el texto en ingles que
    # documenta todo el mundo ("Connection refused") -- devuelve el mensaje de
    # socket de Windows TRADUCIDO ("...denego expresamente dicha conexion"),
    # y encima con codigo de salida 0 incluso al fallar. Verificado en real:
    #   "...denego expresamente dicha conexion. (10061)"           -> rechazada
    #   "...no ha podido responder... periodo de tiempo. (10060)"  -> timeout
    # El texto cambia con el idioma de Windows; el codigo entre parentesis NO
    # (son codigos WSA de Winsock). Por eso se mira el codigo primero, y las
    # palabras en ingles quedan solo de respaldo por si esto corre en otro SO.
    RECHAZADA = ("(10061)", "refused")
    TIMEOUT = ("(10060)", "(10065)", "(10051)", "timed out", "timeout", "no route to host", "unreachable")

    if any(m in salida for m in RECHAZADA):
        return (
            f"{destino}:{puerto} rechazo la conexion (adb devolvio codigo {code}, pero la "
            f"conexion SI fallo -- no te fies de un 0 aqui).\n\n{salida}\n\n"
            "Esto significa que Tailscale SI llega al movil, pero nadie escucha en "
            "ese puerto: el modo TCP/IP fijo esta apagado (se resetea solo al "
            "reiniciar el movil o al tocar el interruptor de Depuracion inalambrica). "
            "Arreglo: en el movil, Ajustes -> Opciones de desarrollador -> Depuracion "
            "inalambrica -> apaga y enciende el interruptor. Si eso no basta, hace "
            "falta un cable USB una vez y ejecutar en el PC: adb tcpip 5555"
        )

    if any(m in baja for m in TIMEOUT):
        return (
            f"{destino}:{puerto} no responde, ni rechaza ni acepta.\n\n{salida}\n\n"
            "Esto es distinto de 'rechazado': aqui el paquete no llega al movil. "
            "Casi siempre es que Tailscale esta desconectado o dormido EN EL MOVIL "
            "(revisa el icono de Tailscale en el telefono), o que la IP configurada "
            f"en paths.json ({destino}) ya no es la suya -- las IPs de Tailscale no "
            "cambian solas, pero un movil nuevo o reinstalado tiene una distinta."
        )

    return (
        f"No pude conectar a {destino}:{puerto} (codigo {code}):\n\n{salida}\n\n"
        "Si el movil se reinicio, el modo TCP/IP se resetea y hace falta un cable "
        "USB una vez para reactivarlo (adb tcpip 5555), o tocar el interruptor de "
        "Depuracion inalambrica en Opciones de desarrollador."
    )
