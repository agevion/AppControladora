"""Cerebro D: la app de escritorio. NO habla con ningun modelo.

Los otros tres cerebros mandan texto a algo que razona (Claude Code, la IA local)
o a una shell. Este maneja **la aplicacion de Claude que hay abierta en el PC**:
escribe en su compositor, pulsa Enter y va leyendo lo que Claude contesta. Lo que
pasa, pasa en la ventana que tienes delante -- no hay proxy ni copia headless.

La fontaneria (encontrar la ventana, la accesibilidad, teclear, leer el disco)
vive en `controladora/appctl/`. Aqui solo esta lo que hace falta para que esto se
vea en el movil EXACTAMENTE igual que los otros chats: los mismos eventos
`{"kind": ...}` que emiten brain_local y brain_claude.

De donde sale la respuesta: NO de mirar la pantalla. La app escribe su
transcripcion en `~/.claude/projects/<...>/<cliSessionId>.jsonl` segun trabaja, y
de ahi se lee el texto exacto con sus bloques ya separados. La pantalla solo se
consulta para saber CUANDO ha terminado.

Como se sabe que ha terminado, que es la parte delicada: no hay ningun evento de
"turno acabado" en ningun sitio. Se combinan dos senales y ninguna vale sola:

  - el transcript deja de crecer  -> pero una herramienta larga (un build de
    cinco minutos) no escribe nada mientras corre, asi que el silencio no
    significa que haya acabado;
  - la barra lateral dice "Inactivo" -> pero tarda un momento en cambiar a "En
    ejecucion" nada mas enviar, asi que al principio miente en el otro sentido.

Asi que se exige que se cumplan LAS DOS, y ademas se ignora el "Inactivo" de los
primeros segundos (GRACIA). Si aun asi nadie da senales, corta TIMEOUT.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncIterator

from .appctl import input as entrada
from .appctl import sessions, uia, window

log = logging.getLogger("controladora.app")

# Cada cuanto se relee el transcript. Los bloques llegan enteros (no palabra a
# palabra), asi que bajar de esto no hace el chat mas fluido: solo gasta disco.
INTERVALO = 0.4

# Cada cuanto se pregunta a la pantalla si la sesion sigue trabajando. Es la
# consulta cara de las dos (recorre el arbol de accesibilidad entero), asi que va
# mucho mas espaciada que la lectura del fichero.
INTERVALO_PANTALLA = 2.5

# Margen tras enviar durante el cual un "Inactivo" no cuenta: la barra lateral
# tarda en enterarse de que acaba de empezar un turno.
GRACIA = 8.0

# Silencio necesario para dar el turno por terminado, ADEMAS de que la pantalla
# diga que no trabaja.
SILENCIO = 3.0

# Tope duro. Un turno de la app puede durar muchisimo (Claude compilando algo),
# pero algo tiene que cortar si la ventana se cierra a mitad y nadie avisa.
TIMEOUT = 1800.0


class AppBrain:
    """Una instancia por servidor, como los otros cerebros.

    No guarda conversacion: la conversacion vive en la app, que es justo la
    gracia. Lo unico que se recuerda entre turnos es en que sesion se estaba
    escribiendo, para que el movil no tenga que repetirlo en cada mensaje.
    """

    def __init__(self) -> None:
        self._ultima_sesion: str | None = None

    @property
    def ultima_sesion(self) -> str | None:
        return self._ultima_sesion

    async def estado(self) -> dict[str, Any]:
        """Una foto de la app para el movil (ver protocol.app_state)."""
        v = await asyncio.to_thread(window.buscar)
        if v is None:
            return {"abierta": False}

        try:
            await asyncio.to_thread(uia.despertar, v.hwnd)
            indice = await asyncio.to_thread(sessions.listar)
            titulos = tuple(s.titulo for s in indice[:30] if s.titulo)
            vista = await asyncio.to_thread(uia.vista, v.hwnd, titulos)
        except Exception as e:
            log.exception("no pude leer el estado de la app")
            return {"abierta": True, "error": f"{type(e).__name__}: {e}"}

        # El indice de disco tiene los datos (modelo, esfuerzo, permisos, cwd) y
        # la pantalla tiene el estado en vivo. Se cruzan por titulo para que el
        # movil reciba una sola lista con todo, en vez de dos que tenga que casar.
        por_titulo = {s.titulo: s for s in indice}
        lista = []
        for s in vista.sesiones:
            d = por_titulo.get(s.titulo)
            lista.append(
                {
                    "titulo": s.titulo,
                    "trabajando": s.trabajando,
                    "estado": s.estado_crudo,
                    "modelo": d.modelo if d else "",
                    "esfuerzo": d.esfuerzo if d else "",
                    "permisos": d.modo if d else "",
                    "cwd": d.cwd if d else "",
                }
            )

        return {
            "abierta": True,
            "titulo": vista.titulo_abierto,
            "modelo": vista.modelo,
            "uso": vista.uso,
            # Solo los mandos que rodean al compositor y los de las tarjetas que
            # salgan: la barra lateral entera son decenas de botones de sesion que
            # el movil ya pinta como lista.
            "mandos": [m.nombre for m in vista.barra],
            # Las opciones de un menu abierto (modelo, esfuerzo, permisos...).
            # Sin esto, desde el movil se podia ABRIR el selector de modelo y no
            # elegir nada: el menu se quedaba abierto en el PC esperando.
            "opciones": [m.nombre for m in vista.opciones],
            "sesiones": lista,
        }

    async def abrir(self, titulo: str) -> str:
        """Pulsa una sesion de la barra lateral. Devuelve "" si fue bien.

        Con [titulo] vacio no pulsa nada: solo se asegura de que la app este
        abierta. Es lo que usa el movil cuando la ventana no existe todavia --
        levantarla sin empezar de paso una conversacion que nadie ha pedido.
        """
        try:
            v = await asyncio.to_thread(window.asegurar)
        except window.NoEstaLaApp as e:
            return str(e)
        if not titulo:
            return ""
        await asyncio.to_thread(uia.despertar, v.hwnd)
        # El boton se llama "<estado traducido> <titulo>", asi que se casa por el
        # final: el titulo del indice no esta traducido y el prefijo si.
        ok = await asyncio.to_thread(entrada.pulsar, v, titulo, True)
        if not ok:
            return f"No pude abrir «{titulo}»: no esta a la vista en la barra lateral."
        self._ultima_sesion = titulo
        return ""

    async def nueva(self) -> str:
        try:
            v = await asyncio.to_thread(window.asegurar)
        except window.NoEstaLaApp as e:
            return str(e)
        await asyncio.to_thread(uia.despertar, v.hwnd)
        if not await asyncio.to_thread(entrada.pulsar_conocido, v, "nuevo"):
            return "No encontre el boton de conversacion nueva en la app."
        self._ultima_sesion = None
        return ""

    async def pulsar(self, nombre: str) -> str:
        try:
            v = await asyncio.to_thread(window.asegurar)
        except window.NoEstaLaApp as e:
            return str(e)
        await asyncio.to_thread(uia.despertar, v.hwnd)
        ok = await asyncio.to_thread(entrada.pulsar, v, nombre)
        return "" if ok else f"No encontre el boton «{nombre}» en pantalla."

    async def parar(self) -> str:
        try:
            v = await asyncio.to_thread(window.asegurar)
        except window.NoEstaLaApp as e:
            return str(e)
        try:
            await asyncio.to_thread(entrada.parar, v)
        except entrada.NoSePudoEscribir as e:
            return str(e)
        return ""

    # El puntero sobre el video (tocar/arrastrar/desplazar/copiar) y el propio
    # video se movieron a pantalla completa en v16 -- ver appctl/pantallas.py y
    # appctl/pantalla_input.py, llamados directo desde server.py. Ya no
    # apuntan a la ventana de Claude sino al monitor que el movil este viendo.

    async def chat(
        self,
        text: str,
        sesion: str | None = None,
        nueva: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        """Una vuelta: escribe en la app y emite lo que Claude vaya contestando.

        Mismos eventos que los otros cerebros (ver brain_local.chat).
        """
        if not text.strip():
            return

        try:
            v = await asyncio.to_thread(window.asegurar)
        except window.NoEstaLaApp as e:
            yield {"kind": "error", "text": str(e)}
            return

        try:
            await asyncio.to_thread(uia.despertar, v.hwnd)
        except Exception as e:
            yield {"kind": "error", "text": f"No pude leer la app: {type(e).__name__}: {e}"}
            return

        if nueva:
            fallo = await self.nueva()
            if fallo:
                yield {"kind": "error", "text": fallo}
                return
            await asyncio.sleep(1.5)  # la pantalla se reconstruye entera
        elif sesion and sesion != await self._sesion_abierta(v):
            fallo = await self.abrir(sesion)
            if fallo:
                yield {"kind": "error", "text": fallo}
                return
            await asyncio.sleep(1.0)

        # A donde va esto, y desde que byte hay que leer. Las dos cosas ANTES de
        # enviar: el desplazamiento marca la frontera entre la conversacion vieja
        # y la respuesta a este mensaje.
        antes_ids = await asyncio.to_thread(sessions.identificadores)
        abierta = await self._sesion_abierta(v)
        destino = await asyncio.to_thread(sessions.por_titulo, abierta) if abierta else None
        jsonl = await asyncio.to_thread(sessions.transcripcion, destino) if destino else None
        desde = await asyncio.to_thread(sessions.tamano, jsonl) if jsonl else 0

        try:
            await asyncio.to_thread(entrada.enviar, v, text)
        except entrada.NoSePudoEscribir as e:
            yield {"kind": "error", "text": str(e)}
            return

        if destino is None:
            # Conversacion recien empezada: no existia en el indice hasta este
            # envio. La app la crea ahora, ya con su titulo puesto.
            destino = await asyncio.to_thread(sessions.aparecida, antes_ids)
            if destino is None:
                yield {
                    "kind": "error",
                    "text": "Se envio, pero no consigo identificar en que conversacion ha caido.",
                }
                return
            jsonl = await asyncio.to_thread(sessions.transcripcion, destino)
            desde = 0

        self._ultima_sesion = destino.titulo

        if jsonl is None:
            yield {
                "kind": "error",
                "text": f"Se envio a «{destino.titulo}», pero aun no hay transcripcion que leer.",
            }
            return

        log.info("app: enviado a %r, leyendo %s desde %d", destino.titulo, jsonl.name, desde)

        async for ev in self._seguir(v, destino.titulo, jsonl, desde):
            yield ev

    async def _sesion_abierta(self, v: window.Ventana) -> str | None:
        """El titulo de la sesion que se esta viendo en la app, o None."""
        titulos = await asyncio.to_thread(sessions.titulos)
        vista = await asyncio.to_thread(uia.vista, v.hwnd, titulos)
        return vista.titulo_abierto

    async def _trabajando(self, v: window.Ventana, titulo: str) -> bool | None:
        """Si esa sesion sigue trabajando segun la barra lateral. None = no se sabe."""
        try:
            vista = await asyncio.to_thread(uia.vista, v.hwnd, (titulo,))
        except Exception:
            return None
        s = next((s for s in vista.sesiones if s.titulo == titulo), None)
        return s.trabajando if s else None

    async def _seguir(
        self,
        v: window.Ventana,
        titulo: str,
        jsonl: Any,
        desde: int,
    ) -> AsyncIterator[dict[str, Any]]:
        """Emite lo que aparezca en el transcript hasta que el turno termine.

        El criterio de "termino" esta explicado arriba, en el docstring del
        modulo: hace falta que la pantalla diga que no trabaja Y que el fichero
        lleve un rato callado.
        """
        arranque = time.monotonic()
        limite = arranque + TIMEOUT
        ultimo_mensaje = arranque
        proxima_pantalla = arranque + INTERVALO_PANTALLA
        parada_vista = False
        pos = desde

        while time.monotonic() < limite:
            nuevos, pos = await asyncio.to_thread(sessions.leer, jsonl, pos)
            for m in nuevos:
                if m.rol != "assistant":
                    continue  # el eco de lo que acabas de escribir ya lo pinto el movil
                ultimo_mensaje = time.monotonic()
                parada_vista = False  # si vuelve a hablar, no habia terminado
                if m.tipo == "texto":
                    yield {"kind": "text", "text": m.texto + "\n"}
                elif m.tipo == "tool":
                    # `confirm` False: los permisos de la app los aprueba la app,
                    # no el movil. Si saca una tarjeta, sus botones llegan al movil
                    # por APP_STATE.mandos y se pulsan con APP_PRESS.
                    yield {"kind": "tool", "name": m.nombre, "args": {}, "confirm": False}

            ahora = time.monotonic()

            if ahora >= proxima_pantalla:
                proxima_pantalla = ahora + INTERVALO_PANTALLA
                # Durante los primeros segundos la barra lateral todavia no se ha
                # enterado de que hay un turno en marcha: su "Inactivo" no vale.
                if ahora - arranque > GRACIA:
                    trabajando = await self._trabajando(v, titulo)
                    parada_vista = trabajando is False

            if parada_vista and ahora - ultimo_mensaje > SILENCIO:
                log.info("app: turno de %r terminado tras %.0fs", titulo, ahora - arranque)
                return

            await asyncio.sleep(INTERVALO)

        yield {
            "kind": "error",
            "text": (
                f"Llevo {TIMEOUT / 60:.0f} minutos siguiendo «{titulo}» y no termina. "
                "Dejo de mirar; en la app sigue como este."
            ),
        }
