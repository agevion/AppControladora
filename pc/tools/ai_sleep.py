"""Duerme la IA local: la descarga de la VRAM.

Este es el requisito central del proyecto: la IA no reside en memoria. Ollama lo
resuelve nativamente con keep_alive=0, no hay que inventar nada. La GPU queda
libre para Unity, y despertarla es solo volver a hablarle (3-5 s en la 1080 Ti).
"""

from __future__ import annotations

import json
import time
import urllib.request

from controladora import paths

SPEC = {
    "name": "ai_sleep",
    "description": (
        "Duerme la IA local descargandola de la memoria de la grafica, liberando la "
        "VRAM para otras cosas (Unity, juegos). No hace falta despertarla a mano: "
        "vuelve sola en cuanto le hables otra vez."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

CONFIRM = False

# Ollama acepta la peticion y descarga en segundo plano, asi que preguntar por el
# estado justo despues devuelve "despierta" todavia. Esperamos a verlo de verdad:
# una tool no debe afirmar que ha hecho algo que no ha comprobado.
UNLOAD_TIMEOUT = 15.0
POLL_EVERY = 0.3


def _vram_en_uso(url: str) -> float:
    with urllib.request.urlopen(f"{url}/api/ps", timeout=10) as resp:
        data = json.loads(resp.read())
    return sum(m.get("size_vram", 0) for m in (data.get("models") or []))


def run() -> str:
    cfg = paths.ollama()
    url = cfg.get("url", "http://127.0.0.1:11434")
    model = cfg.get("model", "qwen3:8b")

    # Una generacion vacia con keep_alive=0 es la forma que da Ollama de
    # descargar un modelo sin matar el servidor.
    payload = json.dumps({"model": model, "keep_alive": 0}).encode()
    req = urllib.request.Request(
        f"{url}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except Exception as e:
        return f"No pude dormir la IA: {type(e).__name__}: {e}"

    limite = time.monotonic() + UNLOAD_TIMEOUT
    while time.monotonic() < limite:
        try:
            if _vram_en_uso(url) == 0:
                return f"IA local ({model}) descargada de la VRAM. Vuelve sola cuando le hables."
        except Exception:
            break
        time.sleep(POLL_EVERY)

    return (
        f"Pedi descargar {model}, pero sigue en VRAM despues de {UNLOAD_TIMEOUT:.0f}s. "
        "Puede que estuviera respondiendo algo; reintentalo."
    )
