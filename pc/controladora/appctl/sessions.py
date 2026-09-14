"""Las sesiones de la app y su conversacion, leidas de disco.

Esta es la parte que hace que esto NO sea un scraper. La app de escritorio
escribe dos cosas por su cuenta, y las dos son mucho mejor fuente que la
pantalla:

1. **El indice**, en
   `%APPDATA%\\Claude\\claude-code-sessions\\<cuenta>\\<dispositivo>\\local_*.json`.
   Un fichero por sesion, con el titulo, el cwd, el modelo, el esfuerzo, el modo
   de permisos y cuando se toco por ultima vez. Y, lo que lo ata todo, el
   `cliSessionId`.

2. **La transcripcion**, en `~/.claude/projects/<cwd-con-guiones>/<cliSessionId>.jsonl`,
   que se va escribiendo mientras Claude trabaja.

O sea que para leer lo que dice Claude no hace falta ni OCR ni recorrer el arbol
de accesibilidad: llega el texto exacto, con sus bloques separados (texto,
herramienta, razonamiento) y sin depender de que la UI cambie de sitio. La
pantalla solo hace falta para lo que de verdad es visual.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger("controladora.appctl.sessions")

APPDATA = Path(os.environ.get("APPDATA", ""))
INDICE = APPDATA / "Claude" / "claude-code-sessions"
PROYECTOS = Path.home() / ".claude" / "projects"


@dataclass(frozen=True)
class Sesion:
    id: str            # el que usa la app ("local_<uuid>")
    cli_id: str        # el de Claude Code: es el nombre del .jsonl
    titulo: str
    cwd: str
    modelo: str
    esfuerzo: str
    modo: str          # permissionMode: "auto" | "plan" | "default"...
    ultima: float      # epoch en segundos (el fichero lo trae en milisegundos)
    archivada: bool


@dataclass(frozen=True)
class Mensaje:
    """Un trozo de conversacion, ya masticado para el movil.

    `tipo` es "texto" (lo que dice Claude o lo que dijo Ale), "tool" (una
    herramienta, con su nombre) o "pensando". Se separan porque el movil los
    pinta distinto: el texto es la conversacion, las herramientas son la barra
    de progreso, y el razonamiento se pliega.
    """

    rol: str           # "user" | "assistant"
    tipo: str          # "texto" | "tool" | "pensando"
    texto: str
    nombre: str = ""   # nombre de la herramienta, si tipo == "tool"


def listar(incluir_archivadas: bool = False) -> list[Sesion]:
    """Todas las sesiones, de la mas reciente a la mas antigua."""
    if not INDICE.is_dir():
        log.warning("no existe el indice de sesiones: %s", INDICE)
        return []

    out: list[Sesion] = []
    for f in INDICE.rglob("local_*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            log.debug("indice ilegible %s: %s", f.name, e)
            continue
        if d.get("isArchived") and not incluir_archivadas:
            continue
        out.append(
            Sesion(
                id=d.get("sessionId", ""),
                cli_id=d.get("cliSessionId", ""),
                titulo=(d.get("title") or "").strip(),
                cwd=d.get("cwd", ""),
                modelo=d.get("model", ""),
                esfuerzo=d.get("effort", ""),
                modo=d.get("permissionMode", ""),
                ultima=(d.get("lastActivityAt") or 0) / 1000.0,
                archivada=bool(d.get("isArchived")),
            )
        )

    out.sort(key=lambda s: s.ultima, reverse=True)
    return out


def titulos(n: int = 30) -> tuple[str, ...]:
    """Los titulos mas recientes. Los necesita `uia.vista` para poder partir el
    nombre de los botones de la barra lateral (ver alli el porque)."""
    return tuple(s.titulo for s in listar()[:n] if s.titulo)


def activa() -> Sesion | None:
    """La sesion tocada mas recientemente.

    Es una aproximacion honesta a "la que tienes abierta": la app actualiza
    `lastActivityAt` al enfocarla, asi que acierta salvo que tengas dos ventanas.
    Cuando importa de verdad cual es, se cruza con lo que dice la barra lateral
    (`uia.Vista.sesiones`), que si sabe cual esta seleccionada.
    """
    todas = listar()
    return todas[0] if todas else None


def por_titulo(titulo: str) -> Sesion | None:
    return next((s for s in listar() if s.titulo == titulo), None)


def identificadores() -> set[str]:
    """Los ids de todas las sesiones, archivadas incluidas."""
    return {s.id for s in listar(incluir_archivadas=True)}


def aparecida(antes: set[str], espera: float = 40.0) -> Sesion | None:
    """Espera a que aparezca una sesion que no estaba en `antes`.

    Una sesion recien abierta con el boton "Nuevo" NO existe en el indice hasta
    que se envia el primer mensaje: la app la crea en ese momento, con su titulo
    ya puesto. O sea que preguntar por "la mas reciente" justo despues de enviar
    devuelve la sesion VIEJA, y si esa esta trabajando se leerian sus mensajes
    como si fueran la respuesta. Comparar contra la foto de antes es la unica
    forma de senalar a la de verdad sin ambiguedad.
    """
    limite = time.time() + espera
    while time.time() < limite:
        for s in listar(incluir_archivadas=True):
            if s.id not in antes:
                return s
        time.sleep(0.5)
    return None


def transcripcion(s: Sesion) -> Path | None:
    """El .jsonl de una sesion, o None si todavia no existe.

    El nombre de la carpeta es el cwd con los dos puntos y las barras cambiados
    por guiones ("E:\\App" -> "E--App"). Se construye el esperado y, si no esta,
    se busca por todo el arbol: esa regla es de Claude Code y no nuestra, asi que
    no conviene depender de haberla deducido bien.
    """
    if not s.cli_id:
        return None
    esperado = PROYECTOS / s.cwd.replace(":", "-").replace("\\", "-").replace("/", "-")
    directo = esperado / f"{s.cli_id}.jsonl"
    if directo.exists():
        return directo
    for f in PROYECTOS.rglob(f"{s.cli_id}.jsonl"):
        log.info("el .jsonl de %s no estaba donde tocaba, aparecio en %s", s.cli_id, f.parent)
        return f
    return None


def _bloques(o: dict[str, Any]) -> Iterator[Mensaje]:
    rol = o.get("type")
    contenido = (o.get("message") or {}).get("content") or []

    # Un mensaje puede traer el texto pelado en vez de la lista de bloques. Los
    # dos formatos conviven en el mismo fichero: dar por hecho que siempre es
    # una lista revienta al primer mensaje de usuario escrito a mano.
    if isinstance(contenido, str):
        contenido = [{"type": "text", "text": contenido}]

    for b in contenido:
        if isinstance(b, str):
            b = {"type": "text", "text": b}
        t = b.get("type")
        if t == "text" and (b.get("text") or "").strip():
            yield Mensaje(rol=rol, tipo="texto", texto=b["text"].strip())
        elif t == "tool_use":
            yield Mensaje(rol=rol, tipo="tool", texto="", nombre=b.get("name", "?"))
        elif t == "thinking":
            yield Mensaje(rol=rol, tipo="pensando", texto="")


def leer(jsonl: Path, desde: int = 0) -> tuple[list[Mensaje], int]:
    """Lee lo nuevo del transcript. Devuelve (mensajes, nuevo_desplazamiento).

    Se abre en binario y solo se consumen LINEAS COMPLETAS: el fichero se esta
    escribiendo mientras se lee, y la ultima linea puede estar a medias. Si se
    parsease igualmente, se perderia ese mensaje para siempre -- el
    desplazamiento ya habria pasado de largo. Lo que queda a medias se deja
    fuera y entra en la lectura siguiente.
    """
    try:
        with jsonl.open("rb") as f:
            f.seek(desde)
            crudo = f.read()
    except FileNotFoundError:
        return [], desde

    corte = crudo.rfind(b"\n")
    if corte < 0:
        return [], desde  # aun no hay ninguna linea entera nueva
    completo, avance = crudo[: corte + 1], corte + 1

    mensajes: list[Mensaje] = []
    for linea in completo.splitlines():
        if not linea.strip():
            continue
        try:
            o = json.loads(linea.decode("utf-8", errors="replace"))
        except Exception:
            continue
        if o.get("type") not in ("user", "assistant"):
            continue  # titulos, resumenes y demas anotaciones internas
        if o.get("isSidechain"):
            continue  # subagentes: no van al chat principal
        mensajes.extend(_bloques(o))

    return mensajes, desde + avance


def tamano(jsonl: Path) -> int:
    """El desplazamiento desde el que leer para ver solo lo que venga DESPUES."""
    try:
        return jsonl.stat().st_size
    except OSError:
        return 0


def esperar(jsonl: Path, desde: int, espera: float, intervalo: float = 0.4) -> Iterator[Mensaje]:
    """Va soltando los mensajes nuevos segun aparecen, hasta que se acabe el tiempo.

    Version sincrona y con generador porque asi la puede usar tanto una tool
    (que corre en su hilo) como el cerebro (que la envolvera en to_thread). El
    corte por tiempo lo pone quien llama: aqui no se sabe cuando ha terminado
    Claude, solo cuando deja de escribir.
    """
    limite = time.time() + espera
    pos = desde
    while time.time() < limite:
        nuevos, pos = leer(jsonl, pos)
        for m in nuevos:
            yield m
        if not nuevos:
            time.sleep(intervalo)
