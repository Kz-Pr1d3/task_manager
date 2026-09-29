import logging
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class LoggingMiddleware:
    """
    Логирует method/path/status и прокидывает request_id.

    Pure ASGI (не BaseHTTPMiddleware): иначе SSE/stream зависает
    из‑за буферизации ответа в ``call_next``.
    """

    def __init__(self, app: ASGIApp) -> None:
        """
        :param app: следующий ASGI-приложение в цепочке.
        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """
        Пишет access-лог и заголовок X-Request-ID.

        :param scope: ASGI scope.
        :param receive: ASGI receive.
        :param send: ASGI send.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        request_id = headers.get("x-request-id", str(uuid.uuid4()))
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id

        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                mutable = MutableHeaders(scope=message)
                mutable["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            method = scope.get("method", "?")
            path = scope.get("path", "?")
            if status_code >= 500:
                logger.error(
                    "%s %s → %d (%.1fms) [%s]",
                    method,
                    path,
                    status_code,
                    elapsed_ms,
                    request_id,
                )
            else:
                logger.info(
                    "%s %s → %d (%.1fms) [%s]",
                    method,
                    path,
                    status_code,
                    elapsed_ms,
                    request_id,
                )
