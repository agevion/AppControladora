"""Registry de tools: descubre, valida y ejecuta los modulos de pc/tools/.

Los dos cerebros (IA local y Claude Code) llaman a las MISMAS tools desde aqui.
Escribes `build_gradle` una vez y aparece en los dos chats gratis.

Contrato de un modulo de tool (pc/tools/<algo>.py):

    SPEC = {
        "name": "build_gradle",
        "description": "Que hace, en una linea. Lo lee el modelo: se claro.",
        "parameters": {                       # JSON Schema
            "type": "object",
            "properties": {"proyecto": {"type": "string", "description": "..."}},
            "required": ["proyecto"],
        },
    }

    CONFIRM = False   # True -> pide Si/No en el movil antes de ejecutar

    def run(**kwargs) -> str:
        "Devuelve texto plano. Lo lee el modelo Y el humano."

Recarga en caliente: los modulos se cargan por ruta de fichero, no por import
normal, asi que `load()` los relee de verdad sin reiniciar el servicio ni
pelearse con sys.modules. Esto es lo que cierra el bucle de auto-ampliacion
(ver ARQUITECTURA.md seccion 8).
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("controladora.registry")

PC_DIR = Path(__file__).resolve().parent.parent
TOOLS_DIR = PC_DIR / "tools"


def _ensure_importable() -> None:
    """Deja que las tools importen `controladora.*` y `_util` sin ceremonia.

    Se cargan por ruta de fichero (para la recarga en caliente), asi que no
    heredan el contexto de imports de un paquete. Se resuelve aqui una vez y
    no en cada tool: cuanto menos boilerplate tenga el contrato, mas dificil
    es que Claude Code lo escriba mal al ampliar el sistema.
    """
    for d in (PC_DIR, TOOLS_DIR):
        s = str(d)
        if s not in sys.path:
            sys.path.insert(0, s)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    confirm: bool
    run: Callable[..., str]
    source: Path

    def schema(self) -> dict[str, Any]:
        """Formato de tool calling compatible con OpenAI, que es el que usa Ollama."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolError(Exception):
    """Fallo al ejecutar una tool. El mensaje va al modelo Y al usuario."""


class Registry:
    def __init__(self, tools_dir: Path = TOOLS_DIR) -> None:
        self.tools_dir = tools_dir
        self._tools: dict[str, Tool] = {}
        self._errors: dict[str, str] = {}

    # -- carga ---------------------------------------------------------------

    def load(self) -> None:
        """(Re)escanea el directorio. Idempotente: se puede llamar en caliente."""
        self._tools = {}
        self._errors = {}
        _ensure_importable()

        if not self.tools_dir.is_dir():
            log.warning("no existe %s; sin tools", self.tools_dir)
            return

        for path in sorted(self.tools_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                tool = self._load_one(path)
                if tool.name in self._tools:
                    raise ToolError(f"nombre duplicado: {tool.name} (ya en {self._tools[tool.name].source.name})")
                self._tools[tool.name] = tool
            except Exception as e:
                # Una tool rota no debe tumbar el servicio ni las demas: se
                # registra el error y se sigue. El movil puede mostrarlo.
                self._errors[path.name] = f"{type(e).__name__}: {e}"
                log.error("tool %s no carga: %s\n%s", path.name, e, traceback.format_exc())

        log.info("registry: %d tools, %d con error", len(self._tools), len(self._errors))

    def _load_one(self, path: Path) -> Tool:
        spec = importlib.util.spec_from_file_location(f"controladora_tool_{path.stem}", path)
        if spec is None or spec.loader is None:
            raise ToolError("no se pudo preparar el modulo")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        raw = getattr(module, "SPEC", None)
        if not isinstance(raw, dict):
            raise ToolError("falta SPEC (dict)")
        for key in ("name", "description", "parameters"):
            if key not in raw:
                raise ToolError(f"SPEC sin '{key}'")

        fn = getattr(module, "run", None)
        if not callable(fn):
            raise ToolError("falta run()")

        return Tool(
            name=raw["name"],
            description=raw["description"],
            parameters=raw["parameters"],
            confirm=bool(getattr(module, "CONFIRM", False)),
            run=fn,
            source=path,
        )

    # -- consulta ------------------------------------------------------------

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [t.schema() for t in self._tools.values()]

    def errors(self) -> dict[str, str]:
        return dict(self._errors)

    # -- ejecucion -----------------------------------------------------------

    def call(self, name: str, args: dict[str, Any]) -> str:
        """Sincrono y potencialmente lento (un build tarda minutos).

        Llamalo desde asyncio.to_thread para no bloquear el event loop.
        """
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"no existe la tool '{name}'. Disponibles: {', '.join(self.names()) or '(ninguna)'}")

        log.info("ejecutando %s(%s)", name, args)
        try:
            return tool.run(**args)
        except TypeError as e:
            # Argumentos que no casan con la firma: el modelo se los ha inventado.
            raise ToolError(f"argumentos invalidos para {name}: {e}") from e
        except Exception as e:
            raise ToolError(f"{name} fallo: {type(e).__name__}: {e}") from e
