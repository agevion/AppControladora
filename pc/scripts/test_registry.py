"""Comprueba que el registry carga las tools y que las inocuas funcionan.

    python scripts/test_registry.py

Solo ejecuta tools sin efectos secundarios (listar, consultar). No abre IDEs ni
compila nada: eso se prueba a mano desde el chat.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from controladora.registry import Registry  # noqa: E402


def main() -> int:
    reg = Registry()
    reg.load()

    print(f"Tools cargadas ({len(reg.names())}):")
    for name in reg.names():
        t = reg.get(name)
        assert t is not None
        marca = "  [PIDE CONFIRMACION]" if t.confirm else ""
        print(f"  {name:<16} {t.source.name:<20}{marca}")

    if reg.errors():
        print("\nTools CON ERROR:")
        for fichero, err in reg.errors().items():
            print(f"  {fichero}: {err}")
        return 1

    print("\n--- Comprobando que los esquemas son validos para Ollama ---")
    for s in reg.schemas():
        fn = s["function"]
        assert s["type"] == "function", s
        assert isinstance(fn["name"], str) and fn["name"], s
        assert isinstance(fn["description"], str) and fn["description"], s
        assert fn["parameters"].get("type") == "object", s
    print(f"  {len(reg.schemas())} esquemas OK")

    print("\n--- Ejecutando tools inocuas ---")
    for name in ("list_projects", "adb_devices"):
        if name not in reg.names():
            continue
        print(f"\n$ {name}()")
        try:
            print(reg.call(name, {}))
        except Exception as e:
            print(f"  FALLO: {e}")
            return 1

    print("\n--- Comprobando que una tool inexistente da error limpio ---")
    try:
        reg.call("no_existo", {})
        print("  MAL: deberia haber lanzado")
        return 1
    except Exception as e:
        print(f"  OK: {e}")

    print("\nRegistry OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
