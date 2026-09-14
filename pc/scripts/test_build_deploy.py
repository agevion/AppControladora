"""Prueba dirigida: "compila X y mandalo al movil" debe usar build_and_install,
no build_gradle solo. Y que adb_connect exista como red de seguridad.

    python scripts/test_build_deploy.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from controladora.brain_local import LocalBrain  # noqa: E402
from controladora.registry import Registry  # noqa: E402


async def main() -> int:
    reg = Registry()
    reg.load()
    if "build_and_install" not in reg.names() or "adb_connect" not in reg.names():
        print("MAL: faltan tools nuevas en el registry")
        return 1

    brain = LocalBrain(reg)

    print(">>> compila pokeoverlay y mandalo al movil")
    t0 = time.monotonic()
    llamadas = []
    async for ev in brain.chat("compila pokeoverlay y mandalo al movil"):
        if ev["kind"] == "tool":
            llamadas.append(ev["name"])
            print(f"    [TOOL] {ev['name']}({ev['args']})")
        elif ev["kind"] == "tool_result":
            primera = ev["text"].splitlines()[0] if ev["text"] else ""
            print(f"    [res]  {primera[:150]}")
        elif ev["kind"] == "text":
            print(f"    [texto] {ev['text'][:200]}")
    print(f"    ({time.monotonic() - t0:.1f}s)")

    if llamadas == ["build_and_install"]:
        print("\nOK: uso build_and_install en una sola llamada, como se le pidio")
        return 0
    elif "build_and_install" in llamadas:
        print(f"\nOK (parcial): uso build_and_install, pero tambien: {llamadas}")
        return 0
    else:
        print(f"\nMAL: esperaba build_and_install, llamo a {llamadas}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
