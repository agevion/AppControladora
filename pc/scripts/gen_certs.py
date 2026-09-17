"""Genera la PKI propia de AppControladora: CA, cert de servidor y cert de cliente.

No necesita el binario de openssl. Todo sale de `cryptography`.

    python scripts/gen_certs.py                 # genera lo que falte
    python scripts/gen_certs.py --force-server  # reemitir solo el server (p.ej. al tener DDNS)

La CA es nuestra, asi que reemitir el cert de servidor con nuevos SAN es barato y no
invalida el cert de cliente que ya tenga la app instalada.
"""

from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import json
import os
import secrets
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

PC_DIR = Path(__file__).resolve().parent.parent
CERTS = PC_DIR / "certs"
CONFIG = PC_DIR / "config.json"

CA_YEARS = 10
LEAF_YEARS = 5


def config_secret(key: str, env_var: str) -> str:
    """Secreto que vive en config.json (fuera del repo) o en una variable de entorno.

    Si no existe todavia se genera al azar y se guarda, de modo que el repositorio
    nunca lleve dentro una password real. La del p12 sigue siendo poco relevante
    —el fichero viaja dentro del APK y la defensa real es la clave privada— pero
    publicarla en el codigo no aporta nada.
    """
    del_entorno = os.environ.get(env_var)
    if del_entorno:
        return del_entorno

    data = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    valor = data.get(key)
    if not valor:
        valor = secrets.token_urlsafe(24)
        data[key] = valor
        CONFIG.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return valor


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=4096)


def _name(cn: str) -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "ES"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AppControladora"),
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
        ]
    )


def _write_key(path: Path, key: rsa.RSAPrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def _write_cert(path: Path, cert: x509.Certificate) -> None:
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _load_ca() -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    cert = x509.load_pem_x509_certificate((CERTS / "ca.crt").read_bytes())
    key = serialization.load_pem_private_key((CERTS / "ca.key").read_bytes(), password=None)
    return cert, key


def make_ca() -> None:
    key = _key()
    subject = _name("AppControladora Root CA")
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_now() - dt.timedelta(days=1))
        .not_valid_after(_now() + dt.timedelta(days=365 * CA_YEARS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                key_encipherment=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    _write_key(CERTS / "ca.key", key)
    _write_cert(CERTS / "ca.crt", cert)
    print("  ca.crt / ca.key")


def _san_entries(names: list[str]) -> list[x509.GeneralName]:
    out: list[x509.GeneralName] = []
    for n in names:
        try:
            out.append(x509.IPAddress(ipaddress.ip_address(n)))
        except ValueError:
            out.append(x509.DNSName(n))
    return out


def make_server(sans: list[str]) -> None:
    ca_cert, ca_key = _load_ca()
    key = _key()
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name("controladora-pc"))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_now() - dt.timedelta(days=1))
        .not_valid_after(_now() + dt.timedelta(days=365 * LEAF_YEARS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName(_san_entries(sans)), critical=False)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    _write_key(CERTS / "server.key", key)
    _write_cert(CERTS / "server.crt", cert)
    print(f"  server.crt / server.key   SAN: {', '.join(sans)}")


def make_client() -> None:
    ca_cert, ca_key = _load_ca()
    key = _key()
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name("movil"))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_now() - dt.timedelta(days=1))
        .not_valid_after(_now() + dt.timedelta(days=365 * LEAF_YEARS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    _write_key(CERTS / "client.key", key)
    _write_cert(CERTS / "client.crt", cert)

    password = config_secret("p12_password", "CONTROLADORA_P12_PASSWORD").encode()

    # Android lee PKCS12 nativamente. Usamos cifrado PBESv1/3DES porque el AES-256
    # que sale por defecto no lo tragan todas las versiones de Android.
    try:
        enc = (
            pkcs12.PKCS12Encryption()
            .key_cert_algorithm(pkcs12.PBES.PBESv1SHA1And3KeyTripleDESCBC)
            .hmac_hash(hashes.SHA1())
            .build(password)
        )
    except Exception:
        enc = serialization.BestAvailableEncryption(password)

    p12 = pkcs12.serialize_key_and_certificates(
        name=b"movil",
        key=key,
        cert=cert,
        cas=[ca_cert],
        encryption_algorithm=enc,
    )
    (CERTS / "client.p12").write_bytes(p12)
    print("  client.crt / client.key / client.p12")


def ensure_config(sans: list[str]) -> None:
    """Completa config.json con lo que le falte, sin pisar lo que ya haya dentro.

    No basta con crearlo cuando no existe: `config_secret` puede haberlo creado ya
    con la password del p12 y nada mas.
    """
    data = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    defaults = {
        "host": "0.0.0.0",
        "port": 8443,
        "token": secrets.token_urlsafe(32),
        "san": sans,
    }
    faltan = [clave for clave in defaults if clave not in data]
    if not faltan:
        return

    data.update({clave: defaults[clave] for clave in faltan})
    CONFIG.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"  config.json  ({', '.join(faltan)})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-server", action="store_true", help="reemitir el cert de servidor (nuevos SAN)")
    ap.add_argument("--force-all", action="store_true", help="regenerar TODO, incluida la CA")
    args = ap.parse_args()

    CERTS.mkdir(parents=True, exist_ok=True)

    # Los SAN reales (IP LAN, IP publica o DDNS del PC) se declaran en "san" dentro
    # de config.json, que esta fuera del repo. Aqui solo queda el minimo local.
    config_previa = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    default_sans = ["localhost", "127.0.0.1"]
    sans = config_previa.get("san") or default_sans
    if sans == default_sans:
        print("  AVISO: sin \"san\" en config.json el certificado solo vale para localhost.")

    # Un p12 anterior a que las passwords salieran del codigo: no hay forma de
    # saber con cual se cifro, asi que se reemite en lugar de dejarlo inservible.
    p12_huerfano = (CERTS / "client.p12").exists() and not (
        config_previa.get("p12_password") or os.environ.get("CONTROLADORA_P12_PASSWORD")
    )
    if p12_huerfano:
        print("  client.p12 existe pero su password no consta: se reemite el cliente.")

    print("Generando PKI en", CERTS)

    if args.force_all or not (CERTS / "ca.crt").exists():
        make_ca()
    else:
        print("  ca.crt ya existe (usa --force-all para rehacerla)")

    if args.force_all or args.force_server or not (CERTS / "server.crt").exists():
        make_server(sans)
    else:
        print("  server.crt ya existe (usa --force-server para reemitirlo)")

    if args.force_all or p12_huerfano or not (CERTS / "client.crt").exists():
        make_client()
    else:
        print("  client.crt ya existe")

    ensure_config(sans)
    print("\nListo. Recuerda: certs/ y config.json NO van al repo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
