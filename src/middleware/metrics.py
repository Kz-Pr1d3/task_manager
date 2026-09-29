import time

from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Собирает Prometheus-метрики по HTTP-запросам."""

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Считает latency и счётчик по route template.

        :param request: входящий HTTP-запрос.
        :param call_next: следующий обработчик в цепочке.
        :returns: HTTP-ответ downstream.
        """
        start = time.perf_counter()
        response: Response = await call_next(request)
        elapsed = time.perf_counter() - start

        # Route template (/lists/{id}) — низкая cardinality vs raw path (/lists/42).
        route = request.scope.get("route")
        endpoint = getattr(route, "path", None) or request.url.path
        method = request.method

        # TODO добавить размер отдаваемых данных - брать через хедеры (запрос и проверить на ответ)
        REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=response.status_code).inc()
        REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(elapsed)

        return response
