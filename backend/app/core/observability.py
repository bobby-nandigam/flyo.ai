"""Observability & hardening middleware (spec §7, §9).

Adds, with no external dependencies:
* a per-request ``X-Request-ID`` (generated if the client did not send one),
* structured JSON access logs (method, route, status, duration, request id),
* security response headers,
* an in-process metrics registry exposed at ``/metrics`` in Prometheus text format.

Note on scope: the metrics and the simple rate limiter are per-process. On
serverless (multiple instances) they are best-effort; production-grade rate
limiting and aggregation belong to the edge (Vercel Firewall) and a metrics
backend (Prometheus/OTel), which this structure is ready to export to.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

logger = logging.getLogger("flyo.access")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


class _Metrics:
    def __init__(self) -> None:
        self.requests_total: dict[tuple[str, str, int], int] = defaultdict(int)
        self.duration_sum: dict[tuple[str, str], float] = defaultdict(float)
        self.duration_count: dict[tuple[str, str], int] = defaultdict(int)

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        self.requests_total[(method, route, status)] += 1
        self.duration_sum[(method, route)] += seconds
        self.duration_count[(method, route)] += 1

    def render(self) -> str:
        lines = [
            "# HELP flyo_requests_total Total HTTP requests.",
            "# TYPE flyo_requests_total counter",
        ]
        for (method, route, status), n in sorted(self.requests_total.items()):
            lines.append(f'flyo_requests_total{{method="{method}",route="{route}",status="{status}"}} {n}')
        lines.append("# HELP flyo_request_duration_seconds_sum Sum of request durations.")
        lines.append("# TYPE flyo_request_duration_seconds_sum counter")
        for (method, route), s in sorted(self.duration_sum.items()):
            lines.append(f'flyo_request_duration_seconds_sum{{method="{method}",route="{route}"}} {s:.6f}')
            c = self.duration_count[(method, route)]
            lines.append(f'flyo_request_duration_seconds_count{{method="{method}",route="{route}"}} {c}')
        return "\n".join(lines) + "\n"


METRICS = _Metrics()

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        start = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception:
            self._log(request, 500, time.perf_counter() - start, request_id)
            raise
        elapsed = time.perf_counter() - start

        route = _route_template(request)
        METRICS.observe(request.method, route, response.status_code, elapsed)
        response.headers["X-Request-ID"] = request_id
        for k, v in _SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        self._log(request, response.status_code, elapsed, request_id, route)
        return response

    @staticmethod
    def _log(request: Request, status: int, elapsed: float, request_id: str,
             route: str | None = None) -> None:
        logger.info(json.dumps({
            "event": "http_request",
            "method": request.method,
            "route": route or request.url.path,
            "status": status,
            "duration_ms": round(elapsed * 1000, 2),
            "request_id": request_id,
        }))


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


def metrics_response() -> PlainTextResponse:
    return PlainTextResponse(METRICS.render(), media_type="text/plain; version=0.0.4")
