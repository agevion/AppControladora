"""Copia los secretos del PC a la app Android.

    python scripts/sync_app_secrets.py [--host 192.168.1.50]

Lleva ca.crt y client.p12 a los assets de la app, crea el keystore de release si
no existe, y escribe secrets.properties con el token, el host por defecto y la
password del keystore. Nada de esto va al repo (ver .gitignore).

Ejecutalo cada vez que regeneres certificados o cambies el token.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PC_DIR = Path(__file__).resolve().parent.parent
ROOT = PC_DIR.parent
CERTS = PC_DIR / "certs"
MOVIL = ROOT / "movil"
ASSETS = MOVIL / "app" / "src" / "main" / "assets"

# La password del p12 es simbolica: el fichero viaja dentro del APK, asi que la
# defensa real es la clave privada + el token, no esto.
P12_PASSWORD = "controladora"

# Igual de simbolica: el keystore no sale de este PC y no publicamos la app en
# ninguna store. Solo existe para que el APK vaya firmado, porque Android no
# instala un APK sin firma.
KEYSTORE = MOVIL / "release.jks"
KEYSTORE_PASSWORD = "controladora"
KEY_ALIAS = "controladora"


def find_keytool() -> str | None:
    """keytool sale del JDK de Android Studio: el PATH de este PC no tiene java."""
    paths_file = PC_DIR / "paths.json"
    if paths_file.exists():
        java_home = json.loads(paths_file.read_text(encoding="utf-8")).get("bin", {}).get("java_home")
        if java_home:
            exe = Path(java_home) / "bin" / "keytool.exe"
            if exe.exists():
                return str(exe)
    return shutil.which("keytool")


def ensure_keystore() -> bool:
    """Crea el keystore de release si falta. Sin el, assembleRelease sale sin firmar."""
    if KEYSTORE.exists():
        print(f"  release.jks         (ya existe, no lo toco)")
        return True

    keytool = find_keytool()
    if not keytool:
        print("  AVISO: no encuentro keytool; sin release.jks la release saldra sin firmar")
        return False

    # PKCS12, no JKS: JKS es formato propietario y keytool avisa en cada uso.
    # La extension .jks se queda porque es la que cubre el .gitignore.
    resultado = subprocess.run(
        [
            keytool, "-genkeypair",
            "-keystore", str(KEYSTORE),
            "-storetype", "PKCS12",
            "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
            "-alias", KEY_ALIAS,
            "-storepass", KEYSTORE_PASSWORD,
            "-keypass", KEYSTORE_PASSWORD,
            "-dname", "CN=Controladora, OU=Personal, O=Controladora, L=-, S=-, C=ES",
        ],
        capture_output=True,
        text=True,
    )
    if resultado.returncode != 0:
        print(f"  AVISO: keytool ha fallado, la release saldra sin firmar:\n{resultado.stderr}")
        return False

    print(f"  release.jks         (creado, alias={KEY_ALIAS})")
    return True


def find_sdk() -> str | None:
    for candidate in (
        os.environ.get("ANDROID_HOME"),
        os.environ.get("ANDROID_SDK_ROOT"),
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk"),
    ):
        if candidate and Path(candidate).is_dir():
            return candidate
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", help="host por defecto de la app (IP local, publica o DDNS)")
    args = ap.parse_args()

    config_path = PC_DIR / "config.json"
    if not config_path.exists():
        print("Falta config.json. Ejecuta antes: python scripts/gen_certs.py")
        return 1
    config = json.loads(config_path.read_text(encoding="utf-8"))

    ASSETS.mkdir(parents=True, exist_ok=True)
    for name in ("ca.crt", "client.p12"):
        src = CERTS / name
        if not src.exists():
            print(f"Falta {src}. Ejecuta antes: python scripts/gen_certs.py")
            return 1
        shutil.copy2(src, ASSETS / name)
        print(f"  assets/{name}")

    ensure_keystore()

    host = args.host or "192.168.1.50"
    (MOVIL / "secrets.properties").write_text(
        "\n".join(
            [
                "# Generado por scripts/sync_app_secrets.py. No editar a mano ni commitear.",
                f"host={host}",
                f"port={config['port']}",
                f"token={config['token']}",
                f"p12_password={P12_PASSWORD}",
                f"release_keystore_password={KEYSTORE_PASSWORD}",
                f"release_key_alias={KEY_ALIAS}",
                f"release_key_password={KEYSTORE_PASSWORD}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"  secrets.properties  (host={host}, port={config['port']})")

    local_props = MOVIL / "local.properties"
    if not local_props.exists():
        sdk = find_sdk()
        if sdk:
            # local.properties es un .properties de Java: las barras se escapan.
            escaped = sdk.replace("\\", "\\\\")
            local_props.write_text(f"sdk.dir={escaped}\n", encoding="utf-8")
            print(f"  local.properties    (sdk.dir={sdk})")
        else:
            print("  AVISO: no encuentro el SDK de Android; crea movil/local.properties a mano")

    print("\nListo. Reconstruye el APK para que los cambios entren.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
