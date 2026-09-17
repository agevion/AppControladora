"""Copia los secretos del PC a la app Android.

    python scripts/sync_app_secrets.py --host 192.168.1.X

Lleva ca.crt y client.p12 a los assets de la app, crea el keystore de release si
no existe, y escribe secrets.properties con el token, el host por defecto y la
password del keystore. Nada de esto va al repo (ver .gitignore).

El host se puede fijar de una vez en "lan_host" dentro de config.json, o en la
variable de entorno CONTROLADORA_HOST, en lugar de pasarlo en cada ejecucion.

Ejecutalo cada vez que regeneres certificados o cambies el token.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

PC_DIR = Path(__file__).resolve().parent.parent
ROOT = PC_DIR.parent
CERTS = PC_DIR / "certs"
CONFIG = PC_DIR / "config.json"
MOVIL = ROOT / "movil"
ASSETS = MOVIL / "app" / "src" / "main" / "assets"
SECRETS_PROPERTIES = MOVIL / "secrets.properties"

# El keystore no sale de este PC y la app no se publica en ninguna store: solo
# existe para que el APK vaya firmado, porque Android no instala uno sin firma.
# Aun asi las passwords se generan y se guardan en config.json, que esta fuera
# del repo, en vez de ir escritas aqui.
KEYSTORE = MOVIL / "release.jks"
KEY_ALIAS = "controladora"


def _secrets_properties(clave: str) -> str | None:
    """Recupera un valor del secrets.properties generado la vez anterior.

    Es lo que evita dejar tirado un release.jks creado cuando las passwords
    estaban en el codigo: si la suya sigue ahi, se reutiliza en lugar de inventar
    otra que no abriria ese keystore.
    """
    if not SECRETS_PROPERTIES.exists():
        return None
    for linea in SECRETS_PROPERTIES.read_text(encoding="utf-8").splitlines():
        if linea.startswith(f"{clave}="):
            return linea.split("=", 1)[1].strip() or None
    return None


def keystore_password(config: dict) -> str:
    """Password del keystore de release: entorno, config.json, o una nueva."""
    del_entorno = os.environ.get("CONTROLADORA_KEYSTORE_PASSWORD")
    if del_entorno:
        return del_entorno

    valor = config.get("keystore_password") or _secrets_properties("release_keystore_password")
    if not valor:
        valor = secrets.token_urlsafe(24)
        if KEYSTORE.exists():
            print(
                "  AVISO: release.jks ya existe y su password no consta en ningun sitio.\n"
                "         Si la firma falla, borra movil/release.jks para rehacerlo, o\n"
                "         exporta CONTROLADORA_KEYSTORE_PASSWORD con la de siempre."
            )
    if config.get("keystore_password") != valor:
        config["keystore_password"] = valor
        CONFIG.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return valor


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


def ensure_keystore(password: str) -> bool:
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
            "-storepass", password,
            "-keypass", password,
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

    p12_password = os.environ.get("CONTROLADORA_P12_PASSWORD") or config.get("p12_password")
    if not p12_password:
        print(
            "config.json no tiene p12_password: ese certificado se genero cuando la\n"
            "password estaba escrita en el codigo. Ejecuta antes:\n"
            "    python scripts/gen_certs.py"
        )
        return 1

    ks_password = keystore_password(config)
    ensure_keystore(ks_password)

    host = args.host or os.environ.get("CONTROLADORA_HOST") or config.get("lan_host")
    if not host:
        print(
            "Falta el host de la app. Pasalo con --host 192.168.1.X, exporta\n"
            "CONTROLADORA_HOST, o anade \"lan_host\" a config.json."
        )
        return 1

    SECRETS_PROPERTIES.write_text(
        "\n".join(
            [
                "# Generado por scripts/sync_app_secrets.py. No editar a mano ni commitear.",
                f"host={host}",
                f"port={config['port']}",
                f"token={config['token']}",
                f"p12_password={p12_password}",
                f"release_keystore_password={ks_password}",
                f"release_key_alias={KEY_ALIAS}",
                f"release_key_password={ks_password}",
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
