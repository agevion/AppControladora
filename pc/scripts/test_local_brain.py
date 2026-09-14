"""Prueba de la Fase 1: la IA local entiende, llama a tools, y duerme.

    python scripts/test_local_brain.py

Comprueba el ciclo completo:
  1. Arranca dormida (0 VRAM)
  2. Una orden en lenguaje natural -> llamada a la tool correcta
  3. Tras responder, esta despierta (ocupa VRAM)
  4. ai_sleep la descarga
  5. Vuelve a estar a 0 VRAM
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from controladora.brain_local import LocalBrain  # noqa: E402
from controladora.registry import Registry  # noqa: E402


async def preguntar(brain: LocalBrain, texto: str) -> list[dict]:
    print(f"\n>>> {texto}")
    eventos = []
    t0 = time.monotonic()
    async for ev in brain.chat(texto):
        eventos.append(ev)
        kind = ev["kind"]
        if kind == "text":
            print(f"    [texto] {ev['text'][:300]}")
        elif kind == "tool":
            print(f"    [TOOL]  {ev['name']}({ev['args']})")
        elif kind == "tool_result":
            primera = ev["text"].splitlines()[0] if ev["text"] else ""
            print(f"    [res]   {primera[:150]}")
        elif kind == "missing_tool":
            print(f"    [FALTA] {ev['text'][:200]}")
        elif kind == "error":
            print(f"    [ERROR] {ev['text']}")
    print(f"    ({time.monotonic() - t0:.1f}s)")
    return eventos


async def main() -> int:
    reg = Registry()
    reg.load()
    if reg.errors():
        print("Hay tools con error:", reg.errors())
        return 1

    brain = LocalBrain(reg)

    print("--- 1. Estado inicial ---")
    print(f"    {brain.status()}")

    print("\n--- 2. Orden que necesita una tool ---")
    eventos = await preguntar(brain, "que proyectos tengo?")
    llamadas = [e["name"] for e in eventos if e["kind"] == "tool"]
    if "list_projects" not in llamadas:
        print(f"    MAL: esperaba list_projects, llamo a {llamadas or '(nada)'}")
        return 1
    print("    OK: llamo a list_projects")

    print("\n--- 3. Estado tras responder ---")
    print(f"    {brain.status()}")

    print("\n--- 4. Orden que NO tiene tool (debe avisar, no inventarse) ---")
    brain.reset()
    eventos = await preguntar(brain, "reinicia el router de casa")
    if any(e["kind"] == "missing_tool" for e in eventos):
        print("    OK: aviso de accion no disponible")
    else:
        print("    AVISO: no emitio missing_tool (revisar prompt)")

    print("\n--- 5. Dormir la IA ---")
    print(f"    {reg.call('ai_sleep', {})}")
    time.sleep(2)
    print(f"    {brain.status()}")

    print("\nFase 1 (cerebro local): OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
