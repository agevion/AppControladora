"""Escribe un mensaje en la app de escritorio de Claude y espera su respuesta.

Pide confirmacion SIEMPRE, y no por formalismo: el mensaje va a una sesion que
puede estar en modo automatico, o sea que lo que se escriba aqui puede acabar
ejecutandose en el PC sin mas preguntas. La tarjeta del movil es el sitio donde
se ve el texto exacto antes de que salga.

Ojo con una cosa que no se puede evitar: para escribir hay que traer la ventana
de Claude al primer plano. Si estas usando el PC en ese momento, te la vas a
encontrar delante.
"""

from __future__ import annotations

import time

from controladora.appctl import input as entrada
from controladora.appctl import sessions, uia, window

SPEC = {
    "name": "claude_app_enviar",
    "description": (
        "Escribe un mensaje en la aplicacion de escritorio de Claude (la ventana del PC, "
        "no el CLI) y devuelve lo que conteste. Trae la ventana al primer plano para "
        "poder teclear. Opcionalmente abre antes otra sesion por su titulo."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "texto": {
                "type": "string",
                "description": "El mensaje que se va a escribir en la app, tal cual.",
            },
            "sesion": {
                "type": "string",
                "description": (
                    "Titulo de la sesion que hay que abrir antes de escribir. "
                    "Si se omite, se escribe en la que ya este abierta."
                ),
            },
            "nueva": {
                "type": "boolean",
                "description": "Empezar una conversacion nueva en vez de escribir en la abierta.",
            },
            "espera": {
                "type": "integer",
                "description": "Segundos a esperar la respuesta antes de devolver lo que haya (por defecto 90).",
            },
        },
        "required": ["texto"],
    },
}

CONFIRM = True


def run(texto: str, sesion: str = "", nueva: bool = False, espera: int = 90) -> str:
    v = window.asegurar()
    uia.despertar(v.hwnd)

    if nueva and sesion:
        return "Elige una cosa: o abres una sesion existente ('sesion') o empiezas una nueva."

    if nueva:
        if not entrada.pulsar_conocido(v, "nuevo"):
            return "No encontre el boton de sesion nueva en la app."
        time.sleep(1.5)  # la pantalla se reconstruye entera
    elif sesion:
        if sessions.por_titulo(sesion) is None:
            disponibles = [s.titulo for s in sessions.listar()[:10]]
            return f"No hay ninguna sesion titulada {sesion!r}. Las mas recientes: {disponibles}"
        # El boton de la barra lateral se llama "<estado traducido> <titulo>", asi
        # que se casa por el final: el titulo del disco no esta traducido.
        if not entrada.pulsar(v, sesion, por_el_final=True):
            return (
                f"No pude pulsar la sesion {sesion!r}: no esta a la vista en la barra "
                "lateral (habria que desplazarla)."
            )
        time.sleep(1.0)

    # A donde va esto. Se pregunta a la PANTALLA (que sabe cual se esta viendo) y
    # no al indice de disco (que solo sabe cual se toco mas recientemente). La
    # diferencia muerde con otra sesion trabajando en segundo plano: el indice
    # senalaria a esa, y se leerian sus mensajes como si fueran la respuesta.
    antes = sessions.identificadores()
    vista = uia.vista(v.hwnd, sessions.titulos())
    destino = sessions.por_titulo(vista.titulo_abierto) if vista.titulo_abierto else None

    jsonl = sessions.transcripcion(destino) if destino else None
    # Donde acaba el fichero AHORA: lo que se lea despues sera la respuesta a
    # esto y no el final de la conversacion anterior.
    desde = sessions.tamano(jsonl) if jsonl else 0

    try:
        entrada.enviar(v, texto)
    except entrada.NoSePudoEscribir as e:
        return f"No se envio nada: {e}"

    if destino is None:
        # Sesion recien abierta: no existia en el indice hasta este envio. La app
        # la crea ahora, con su titulo ya puesto.
        destino = sessions.aparecida(antes)
        if destino is None:
            return "Enviado, pero no consigo identificar en que sesion ha caido."
        jsonl, desde = sessions.transcripcion(destino), 0

    if jsonl is None:
        return f"Enviado a '{destino.titulo}', pero aun no hay transcripcion en disco que leer."

    partes: list[str] = []
    herramientas: list[str] = []
    for m in sessions.esperar(jsonl, desde, espera=espera):
        if m.rol != "assistant":
            continue
        if m.tipo == "texto":
            partes.append(m.texto)
        elif m.tipo == "tool":
            herramientas.append(m.nombre)

    if not partes and not herramientas:
        return f"Enviado a '{destino.titulo}'. En {espera}s no contesto nada todavia."

    salida = [f"Enviado a '{destino.titulo}'."]
    if herramientas:
        salida.append(f"Herramientas que uso: {', '.join(herramientas)}")
    if partes:
        salida.append("")
        salida.append("\n\n".join(partes))
    else:
        salida.append("(aun sin texto final: solo herramientas)")
    return "\n".join(salida)
