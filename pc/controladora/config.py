from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

PC_DIR = Path(__file__).resolve().parent.parent
CERTS = PC_DIR / "certs"
CONFIG_PATH = PC_DIR / "config.json"


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    token: str
    san: list[str]

    @property
    def ca_crt(self) -> Path:
        return CERTS / "ca.crt"

    @property
    def server_crt(self) -> Path:
        return CERTS / "server.crt"

    @property
    def server_key(self) -> Path:
        return CERTS / "server.key"


def load() -> Config:
    if not CONFIG_PATH.exists():
        raise SystemExit("Falta config.json. Ejecuta: python scripts/gen_certs.py")

    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg = Config(
        host=raw.get("host", "0.0.0.0"),
        port=int(raw.get("port", 8443)),
        token=raw["token"],
        san=raw.get("san", []),
    )

    for f in (cfg.ca_crt, cfg.server_crt, cfg.server_key):
        if not f.exists():
            raise SystemExit(f"Falta {f.name}. Ejecuta: python scripts/gen_certs.py")

    return cfg
