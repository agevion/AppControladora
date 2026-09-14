"""Proxy de solo-lectura para el % de tokens de la cuenta.

El problema: el CLI de Claude Code recibe de Anthropic, en CADA respuesta, unas
cabeceras `anthropic-ratelimit-unified-*` con el % gastado de la ventana de 5 h
(y de 7 dias). Pero el SDK solo expone ese numero en su evento `rate_limit_event`
cuando ya rozas el limite (~90%). Por debajo, lo omite a proposito: la peticion
para exponerlo siempre (issue #50518) se cerro como "not planned".

La solucion honesta y probada: como esas cabeceras SOLO llegan dentro del propio
trafico del CLI (Anthropic devuelve 429 si intentas leerlas con una llamada suelta
usando el token de suscripcion, ver el intento con `count_tokens`/`/v1/messages`
que falla fuera del cliente), interceptamos ese trafico sin tocarlo. Se arranca el
CLI con ANTHROPIC_BASE_URL apuntando aqui; este proxy reenvia la peticion TAL CUAL
a api.anthropic.com (mismas cabeceras, incluido el user-agent que evita el 429),
lee de reojo el `utilization` de la respuesta y devuelve la respuesta intacta.

Coste: 0 tokens y 0 llamadas extra -- solo lee lo que tus turnos de chat ya generan.
Riesgo: es una pieza mas en el camino CLI -> Anthropic. Por eso el arranque falla
"blando": si el proxy no puede levantar, se deja ANTHROPIC_BASE_URL sin poner y el
CLI habla directo como siempre (ver brain_claude._ensure_client).
"""

from __future__ import annotations

import asyncio
import logging
import re
import socket
from typing import Any

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

log = logging.getLogger("controladora.ratelimit")

UPSTREAM = "https://api.anthropic.com"

# Cabeceras "salto a salto" (HTTP/1.1): son de la conexion, no del mensaje, y
# reenviarlas rompe el siguiente salto. content-length/transfer-encoding las
# recalcula quien emite la respuesta, asi que tampoco se copian.
_HOP = {
    "host", "content-length", "connection", "keep-alive", "transfer-encoding",
    "te", "trailer", "upgrade", "proxy-authorization", "proxy-authenticate",
}

# anthropic-ratelimit-unified-5h-utilization, ...-7d-status, ...-5h-reset, etc.
_HDR = re.compile(
    r"anthropic-ratelimit-unified-(\d+[hd])-(utilization|status|reset|resets|resets-at)",
    re.IGNORECASE,
)


class RateLimitProxy:
    def __init__(self) -> None:
        self._latest: dict[str, Any] | None = None
        self._client: httpx.AsyncClient | None = None
        self._task: asyncio.Task[Any] | None = None
        self._port: int | None = None
        self._logged_once = False

    @property
    def base_url(self) -> str | None:
        return f"http://127.0.0.1:{self._port}" if self._port else None

    def latest(self) -> dict[str, Any] | None:
        """Ultimo estado leido: {"five_hour": {"utilization": 0.37, ...}, ...} o None."""
        return self._latest

    async def start(self) -> str | None:
        """Levanta el proxy y devuelve su base_url, o None si no pudo (fallo blando)."""
        if self._port:
            return self.base_url
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

            self._client = httpx.AsyncClient(
                base_url=UPSTREAM,
                timeout=httpx.Timeout(600.0, connect=15.0),
            )
            app = Starlette(routes=[Route(
                "/{path:path}", self._handle,
                methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
            )])
            config = uvicorn.Config(app, log_level="warning", access_log=False)
            server = uvicorn.Server(config)
            # No tocar los signal handlers: ya hay un uvicorn (el server mTLS) en
            # este proceso que los tiene; instalarlos otra vez se los robaria.
            server.install_signal_handlers = lambda: None  # type: ignore[assignment]

            self._task = asyncio.create_task(server.serve(sockets=[sock]))
            for _ in range(100):  # esperar al bind, ~5 s como mucho
                if server.started:
                    break
                await asyncio.sleep(0.05)
            if not server.started:
                raise RuntimeError("el proxy no arranco a tiempo")

            self._port = port
            log.info("proxy de rate-limit escuchando en %s", self.base_url)
            return self.base_url
        except Exception as e:
            log.warning("no se pudo arrancar el proxy de rate-limit (%s); el CLI hablara directo", e)
            if self._client is not None:
                await self._client.aclose()
                self._client = None
            self._port = None
            return None

    async def _handle(self, request: Request) -> Response:
        assert self._client is not None
        # Reenvio TAL CUAL: mismas cabeceras (menos las de conexion), mismo cuerpo,
        # misma ruta y query. Es lo que hace que Anthropic lo trate como el CLI y
        # no como una llamada suelta (que devuelve 429).
        fwd_headers = [
            (k, v) for k, v in request.headers.items() if k.lower() not in _HOP
        ]
        body = await request.body()
        url = httpx.URL(path=request.url.path, query=request.url.query.encode("utf-8"))
        try:
            upstream_req = self._client.build_request(
                request.method, url, headers=fwd_headers, content=body,
            )
            resp = await self._client.send(upstream_req, stream=True)
        except Exception as e:
            log.warning("fallo reenviando al upstream: %s", e)
            return Response("proxy upstream error", status_code=502)

        self._capture(resp.headers)

        resp_headers = [
            (k, v) for k, v in resp.headers.items()
            if k.lower() not in _HOP
        ]
        return StreamingResponse(
            resp.aiter_raw(),
            status_code=resp.status_code,
            headers=dict(resp_headers),
            background=BackgroundTask(resp.aclose),
        )

    def _capture(self, headers: httpx.Headers) -> None:
        crudas = {
            k.lower(): v for k, v in headers.items()
            if k.lower().startswith("anthropic-ratelimit")
        }
        if not crudas:
            return
        if not self._logged_once:
            # Una sola vez, para poder confirmar en el log los nombres/formato
            # reales de las cabeceras (la doc no fija el formato del valor).
            log.info("cabeceras de rate-limit vistas: %s", crudas)
            self._logged_once = True

        buckets: dict[str, dict[str, Any]] = {}
        for key, val in crudas.items():
            m = _HDR.match(key)
            if not m:
                continue
            window = m.group(1).lower()   # "5h" / "7d"
            field = m.group(2).lower()
            b = buckets.setdefault(window, {})
            if field == "utilization":
                try:
                    u = float(val)
                    b["utilization"] = u / 100.0 if u > 1.0 else u
                except ValueError:
                    pass
            elif field in ("reset", "resets", "resets-at"):
                try:
                    b["resets_at"] = int(float(val))
                except ValueError:
                    pass
            elif field == "status":
                b["status"] = val

        if not buckets:
            return
        norm: dict[str, Any] = {}
        if "5h" in buckets:
            norm["five_hour"] = buckets["5h"]
        if "7d" in buckets:
            norm["seven_day"] = buckets["7d"]
        self._latest = norm or None


# Singleton: uno por proceso, compartido por todos los turnos (como claude_brain).
proxy = RateLimitProxy()
