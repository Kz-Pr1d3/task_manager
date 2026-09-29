import asyncio
import hashlib
import logging
import secrets
import time
from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.sse import EventSourceResponse, ServerSentEvent

from src.api.dependencies import get_current_user_id
from src.api.responses import UNAUTHORIZED
from src.core.cache import get_redis
from src.core.exceptions import UnauthorizedException
from src.core.sse_hub import SSEHub
from src.models.notification import SSETicketResponse

logger = logging.getLogger(__name__)

SSE_TICKET_TTL_SEC = 30
SSE_CONNECTION_MAX_SEC = 15 * 60

notification_stream_router = APIRouter(
    prefix="/notifications",
    responses=UNAUTHORIZED,
)


async def get_sse_hub(request: Request) -> SSEHub:
    """
    Достаёт ``SSEHub`` из ``app.state``.

    :param request: текущий HTTP-запрос.
    :returns: хаб локальных SSE-подписчиков процесса.
    """
    return request.app.state.sse_hub


def _ticket_redis_key(ticket: str) -> str:
    """
    Redis-ключ одноразового SSE ticket (sha256 от сырого ticket).

    :param ticket: plaintext ticket из query/ответа.
    :returns: ключ ``sse-ticket:{hex_digest}``.
    """
    digest = hashlib.sha256(ticket.encode("utf-8")).hexdigest()
    return f"sse-ticket:{digest}"


async def _consume_sse_ticket(ticket: str | None) -> int:
    """
    Атомарно забирает ticket из Redis (GETDEL) и возвращает user_id.

    :param ticket: одноразовый ticket из query.
    :returns: id пользователя-владельца ticket.
    :raises UnauthorizedException: нет ticket / истёк / уже использован.
    """
    if not ticket:
        raise UnauthorizedException(detail="SSE ticket required")

    redis_client = get_redis()
    raw = await redis_client.getdel(_ticket_redis_key(ticket=ticket))
    if raw is None:
        raise UnauthorizedException(detail="Invalid or expired SSE ticket")

    return int(raw)


async def get_sse_user_id(
        ticket: Annotated[str | None, Query()] = None,
) -> int:
    """
    Dependency: валидирует SSE ticket до старта EventSource-стрима.

    :param ticket: одноразовый ticket из query.
    :returns: user_id владельца ticket.
    :raises UnauthorizedException: ticket отсутствует или невалиден.
    """
    return await _consume_sse_ticket(ticket=ticket)


@notification_stream_router.post(
    "/sse-ticket",
    tags=["notifications"],
    summary="Одноразовый ticket для SSE stream",
    status_code=status.HTTP_200_OK,
    response_model=SSETicketResponse,
)
async def create_sse_ticket(
        user_id: Annotated[int, Depends(get_current_user_id)],
) -> SSETicketResponse:
    """
    Создаёт короткоживущий ticket для EventSource (Bearer → Redis).

    :param user_id: id из access-токена.
    :returns: ``{"ticket": "..."}``; TTL ~30s, одноразовый.
    """
    ticket = secrets.token_urlsafe(32)
    redis_client = get_redis()
    await redis_client.setex(
        name=_ticket_redis_key(ticket=ticket),
        time=SSE_TICKET_TTL_SEC,
        value=str(user_id),
    )
    return SSETicketResponse(ticket=ticket)


@notification_stream_router.get(
    "/stream",
    tags=["notifications"],
    summary="SSE-поток notification.invalidate",
    response_class=EventSourceResponse,
)
async def stream_notifications(
        user_id: Annotated[int, Depends(get_sse_user_id)],
        hub: Annotated[SSEHub, Depends(get_sse_hub)],
) -> AsyncIterable[ServerSentEvent]:
    """
    Открывает SSE по одноразовому ticket (не access token в URL).

    Первое событие ``ready`` (retry 3000), далее ``notification.invalidate``.
    Keepalive шлёт ``EventSourceResponse``. Соединение живёт до ~15 мин.

    :param user_id: id из одноразового ticket.
    :param hub: локальный SSEHub процесса.
    :returns: поток ``ServerSentEvent``.
    :raises UnauthorizedException: ticket отсутствует или невалиден.
    """
    queue = await hub.subscribe(user_id=user_id)
    deadline = time.monotonic() + SSE_CONNECTION_MAX_SEC
    logger.info("sse connect", extra={"user_id": user_id})

    try:
        yield ServerSentEvent(
            event="ready",
            data={"type": "ready"},
            retry=3000,
        )

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                message = await asyncio.wait_for(
                    queue.get(),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                break

            yield ServerSentEvent(
                event="notification.invalidate",
                data=message,
            )
    finally:
        await hub.unsubscribe(user_id=user_id, queue=queue)
        logger.info("sse disconnect", extra={"user_id": user_id})
