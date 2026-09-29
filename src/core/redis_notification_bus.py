import asyncio
import json
import logging
from typing import Any

import redis.asyncio as redis
from redis.exceptions import RedisError

from src.core.notification_metrics import REDIS_PUBLISH_ERRORS
from src.core.sse_hub import SSEHub

logger = logging.getLogger(__name__)

INVALIDATE_PAYLOAD = {"type": "notification.invalidate"}


def channel_as_str(channel: bytes | str) -> str:
    """
    Нормализует имя Redis-канала к str.

    Клиент без ``decode_responses`` отдаёт bytes.

    :param channel: имя канала из pubsub-сообщения.
    :returns: UTF-8 строка канала.
    """
    if isinstance(channel, bytes):
        return channel.decode("utf-8")
    return channel


def parse_user_id_from_channel(
        channel: bytes | str,
        *,
        prefix: str = "notifications:user:",
) -> int:
    """
    Достаёт ``user_id`` из ``notifications:user:{id}``.

    :param channel: полное имя канала (str или bytes).
    :param prefix: префикс канала bus.
    :returns: идентификатор пользователя.
    :raises ValueError: канал не совпадает с шаблоном или id не int.
    """
    name = channel_as_str(channel=channel)
    if not name.startswith(prefix):
        raise ValueError(f"unexpected notification channel: {name}")
    return int(name.removeprefix(prefix))


class RedisNotificationBus:
    """
    Redis Pub/Sub для ``notification.invalidate``.

    Publish — из HTTP/worker после commit. Listener — один на процесс
    FastAPI: ``psubscribe`` → локальный ``SSEHub``.
    """

    CHANNEL_PREFIX = "notifications:user:"

    def __init__(
            self,
            client: redis.Redis,
            hub: SSEHub | None = None,
    ) -> None:
        """
        Связывает Redis-клиент и опциональный локальный SSE-хаб.

        Worker publish-only может не передавать ``hub``.
        Listener (``listen_forever``) требует ``hub``.

        :param client: redis.asyncio клиент (можно без decode_responses).
        :param hub: ``SSEHub`` текущего uvicorn-процесса или ``None``.
        """
        self.client = client
        self.hub = hub

    def _channel_for_user(self, user_id: int) -> str:
        """
        Имя канала invalidate для пользователя.

        :param user_id: получатель уведомления.
        :returns: ``notifications:user:{user_id}``.
        """
        return f"{self.CHANNEL_PREFIX}{user_id}"

    async def publish_many(self, user_ids: set[int]) -> None:
        """
        PUBLISH invalidate каждому user_id; RedisError только в лог.

        :param user_ids: получатели с изменениями после commit.
        """
        if not user_ids:
            return

        message = json.dumps(INVALIDATE_PAYLOAD)

        for user_id in user_ids:
            try:
                await self.client.publish(
                    self._channel_for_user(user_id=user_id),
                    message,
                )
            except RedisError:
                REDIS_PUBLISH_ERRORS.inc()
                logger.exception(
                    "Failed to publish notification invalidation",
                    extra={"user_id": user_id},
                )

    async def _deliver_pmessage(self, message: dict[str, Any]) -> None:
        """
        Разбирает pmessage и кладёт payload в локальный hub.

        :param message: элемент из ``pubsub.listen()``.
        """
        if message.get("type") != "pmessage":
            return

        user_id = parse_user_id_from_channel(
            channel=message["channel"],
            prefix=self.CHANNEL_PREFIX,
        )
        raw_data = message["data"]
        if isinstance(raw_data, bytes):
            raw_data = raw_data.decode("utf-8")
        payload = json.loads(raw_data)
        if self.hub is None:
            raise RuntimeError("RedisNotificationBus delivery requires hub")
        await self.hub.publish_to_user(user_id=user_id, message=payload)

    async def listen_forever(self) -> None:
        """
        Фоновый listener: psubscribe и reconnect с backoff.

        ``CancelledError`` пробрасывается (shutdown lifespan).
        """
        if self.hub is None:
            raise RuntimeError("RedisNotificationBus.listen_forever requires hub")

        delay = 1

        while True:
            try:
                async with self.client.pubsub() as pubsub:
                    await pubsub.psubscribe(f"{self.CHANNEL_PREFIX}*")
                    delay = 1
                    logger.info("redis notification bus listener subscribed")

                    async for message in pubsub.listen():
                        try:
                            await self._deliver_pmessage(message=message)
                        except (ValueError, json.JSONDecodeError, TypeError):
                            logger.exception(
                                "redis notification bus bad message",
                                extra={"message_type": message.get("type")},
                            )

            except asyncio.CancelledError:
                raise
            except RedisError:
                logger.exception("Redis notification listener failed")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
            except Exception:
                logger.exception("Redis notification listener unexpected error")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
