"""Prueba minima: que el Agent SDK arranca el CLI empaquetado y responde.

    python scripts/test_claude_sdk.py

El CLI no esta en el PATH: lo trae la app de escritorio en una carpeta con la
version dentro. Aqui se comprueba tambien que el resolver de ruta lo encuentra.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query  # noqa: E402

from controladora.claude_cli import find_cli  # noqa: E402


async def main() -> int:
    cli = find_cli()
    if not cli:
        print("MAL: no encuentro el CLI de Claude Code")
        return 1
    print(f"CLI: {cli}")

    options = ClaudeAgentOptions(
        cli_path=cli,
        cwd=str(Path(__file__).resolve().parent.parent.parent),
        max_turns=1,
        # Tope de gasto: esta es una prueba, no debe costar mas que calderilla.
        max_budget_usd=0.10,
    )

    print("\n>>> di solo 'hola' y nada mas")
    respuesta = ""
    try:
        async for message in query(prompt="di solo 'hola' y nada mas", options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        respuesta += block.text
                        print(f"    [texto] {block.text}")
            elif isinstance(message, ResultMessage):
                print(f"    [result] coste=${getattr(message, 'total_cost_usd', 0) or 0:.4f}")
    except Exception as e:
        print(f"MAL: {type(e).__name__}: {e}")
        return 1

    if respuesta.strip():
        print("\nOK: el Agent SDK habla con el CLI empaquetado")
        return 0
    print("\nMAL: respuesta vacia")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
