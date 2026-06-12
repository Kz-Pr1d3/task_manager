import logging

from opentelemetry import trace
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


def setup_tracing(service_name: str = "my-service") -> None:
    """Call once at app startup to initialise the tracing pipeline."""
    provider = TracerProvider()

    # ConsoleSpanExporter prints spans to stdout.
    # For Jaeger: swap to OTLPSpanExporter(endpoint="http://localhost:4317")
    exporter = ConsoleSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)

    # Auto-instruments all asyncpg queries — no changes to pool.py needed.
    AsyncPGInstrumentor().instrument()

    logger.info("Tracing initialised for service '%s'", service_name)


class TracingMiddleware(BaseHTTPMiddleware):
    """Wraps every HTTP request in an OpenTelemetry span."""

    async def dispatch(self, request: Request, call_next) -> Response:
        span_name = f"{request.method} {request.url.path}"

        with tracer.start_as_current_span(span_name) as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))
            span.set_attribute("http.route", request.url.path)

            response: Response = await call_next(request)

            span.set_attribute("http.status_code", response.status_code)

            if response.status_code >= 500:
                span.set_status(trace.StatusCode.ERROR)

            return response
