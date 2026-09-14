"""La carpeta donde aterrizan los ficheros que manda el movil.

La ruta la manda paths.json ("recibidos"), no una constante aqui: el sitio donde
uno quiere sus cosas es del usuario, no del codigo. Si falta, se usa
Documentos/ControlaPics, que es la "ruta facil" que se pidio -- se llega a ella
desde el Explorador sin buscar nada.

Todo lo demas de este fichero existe por una razon: **el nombre del fichero lo
elige el movil**, o sea que viene de fuera. Un nombre puede traer una ruta
dentro (dos puntos, barra, y a subir hasta System32), caracteres que Windows no acepta,
o ser uno de los nombres reservados del MS-DOS que siguen vivos hoy (CON, NUL,
COM1...). Nada de eso puede acabar decidiendo donde se escribe: por eso se
reduce a un nombre pelado, se limpia, y ademas se comprueba que el resultado
cae DENTRO de la carpeta (cinturon y tirantes: si algo se colara por la
limpieza, el guardado se niega igual).
"""

from __future__ import annotations

import re
from pathlib import Path

from . import paths

POR_DEFECTO = Path.home() / "Documents" / "ControlaPics"

# Los que Windows no admite en un nombre de fichero. La barra y la contrabarra
# no estan aqui porque se quitan antes (son separadores de ruta, no caracteres
# raros: ver nombre_seguro).
PROHIBIDOS = '<>:"|?*'

# Nombres de dispositivo del MS-DOS. Siguen reservados en Windows 11: un fichero
# llamado "CON.txt" no se puede crear, y el error que da no dice por que.
RESERVADOS = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}

# Un nombre de fichero de Windows no puede pasar de 255 caracteres, y la ruta
# entera tampoco de 260 por defecto. Se corta bastante antes: el nombre lo pone
# el movil y un nombre absurdamente largo es siempre mas sintoma que intencion.
MAX_NOMBRE = 120


def carpeta() -> Path:
    """La carpeta de destino, creada si no existia."""
    configurada = paths.recibidos()
    destino = Path(configurada) if configurada else POR_DEFECTO
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def nombre_seguro(bruto: str) -> str:
    """Un nombre de fichero pelado y utilizable a partir de lo que mande el movil.

    Nunca devuelve vacio: si no queda nada aprovechable, "archivo".
    """
    # Lo primero, quitar cualquier ruta: nos quedamos SOLO con el ultimo tramo.
    # Se parten las dos barras porque el movil es Linux por dentro y el PC
    # Windows, asi que pueden llegar de los dos tipos.
    base = bruto.replace("\\", "/").split("/")[-1]
    # Caracteres prohibidos y de control (un \n o un \0 dentro de un nombre).
    base = "".join(c for c in base if c not in PROHIBIDOS and ord(c) >= 32)
    # Windows ignora los puntos y espacios del final al abrir un fichero, asi que
    # "algo.txt." y "algo.txt" acaban siendo el mismo: se quitan aqui para que no
    # haya dos nombres que parezcan distintos y no lo sean.
    base = base.strip(" .")
    if not base:
        return "archivo"
    raiz = base.split(".")[0].upper()
    if raiz in RESERVADOS:
        base = "_" + base
    return base[:MAX_NOMBRE]


def hueco(nombre: str) -> Path:
    """Donde escribir [nombre] sin pisar nada: anade " (2)", " (3)"... si hace falta.

    No se sobrescribe NUNCA. Mandar dos fotos que el movil llama igual
    ("image.jpg" pasa constantemente) tiene que dar dos ficheros, no uno.
    """
    destino = carpeta()
    limpio = nombre_seguro(nombre)
    candidato = destino / limpio
    if not _dentro(candidato, destino):
        # No deberia poder pasar tras nombre_seguro: si pasa, es un fallo nuestro
        # y lo correcto es no escribir nada.
        raise ValueError(f"nombre de fichero no permitido: {nombre!r}")
    if not candidato.exists():
        return candidato

    tronco = candidato.stem
    extension = candidato.suffix
    # Si ya venia con " (n)" de una vez anterior, se cuenta desde ahi en vez de
    # acabar con "foto (2) (2) (2).jpg".
    m = re.fullmatch(r"(.*) \((\d+)\)", tronco)
    if m:
        tronco, n = m.group(1), int(m.group(2))
    else:
        n = 1
    while True:
        n += 1
        candidato = destino / f"{tronco} ({n}){extension}"
        if not candidato.exists():
            return candidato


def _dentro(ruta: Path, base: Path) -> bool:
    """True si [ruta] cae dentro de [base]. La ultima red contra un salto de carpeta que se cuele."""
    try:
        ruta.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False
