"""Saber si un APK esta firmado, antes de mandarlo o instalarlo.

Un APK sin firmar se instala mal en el movil con un mensaje que no dice nada
util ("parece que el paquete no es valido"), asi que el fallo hay que cazarlo
aqui, en el PC, donde si se puede explicar que ha pasado.

Filtrar por variante (debug/release) no basta: es una convencion, no un hecho.
Un `release` con signingConfig sale firmado y es perfectamente mandable, y un
`debug` raro podria no estarlo. Lo que decide es si el fichero lleva firma, y
eso se mira leyendo el propio APK.
"""

from __future__ import annotations

import re
import struct
import zipfile
from pathlib import Path

# Marca del APK Signing Block (firma v2/v3), justo antes del directorio central.
MAGIC = b"APK Sig Block 42"

# Firma v1 (jarsigner): el esquema viejo, por ficheros dentro de META-INF/.
V1 = re.compile(r"^META-INF/.*\.(RSA|DSA|EC|SF)$", re.IGNORECASE)


def _tiene_bloque_de_firma(f, path: Path) -> bool:
    """Firma v2/v3: los 16 bytes anteriores al directorio central son la marca."""
    tam = path.stat().st_size
    cola = min(tam, 64 * 1024)  # el EOCD vive al final, dentro de estos 64K
    f.seek(tam - cola)
    buf = f.read(cola)

    fin = buf.rfind(b"PK\x05\x06")
    if fin < 0:
        return False

    # En el EOCD, el offset del directorio central son 4 bytes a partir del +16.
    (offset_directorio,) = struct.unpack("<I", buf[fin + 16 : fin + 20])
    if offset_directorio < len(MAGIC):
        return False

    f.seek(offset_directorio - len(MAGIC))
    return f.read(len(MAGIC)) == MAGIC


def is_signed(path: Path) -> bool:
    """True si el APK lleva firma v1, v2 o v3. False si no, o si no es un zip."""
    try:
        with path.open("rb") as f:
            if _tiene_bloque_de_firma(f, path):
                return True
        with zipfile.ZipFile(path) as z:
            return any(V1.match(n) for n in z.namelist())
    except (OSError, zipfile.BadZipFile, struct.error):
        return False


def signing_error(path: Path) -> str:
    """El mensaje que ve la IA local cuando intenta mover un APK sin firmar."""
    return (
        f"{path.name} esta SIN FIRMAR: el movil lo rechazaria con 'parece que el paquete "
        f"no es valido'. Me paro aqui.\n\n"
        f"Ruta: {path}\n\n"
        "Un build de release sale sin firmar si el proyecto no tiene signingConfig. "
        "Compila con assembleDebug (sale firmado con la clave de debug y se instala), "
        "o dile al usuario que ese proyecto necesita un keystore para poder hacer "
        "releases instalables."
    )
