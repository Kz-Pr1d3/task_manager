import asyncio
from contextlib import suppress

import pytest
from fakeredis import FakeAsyncRedis
from redis.exceptions import RedisError

from src.core.redis_notification_bus import (
    RedisNotificationBus,
    parse_user_id_from_channel,
)
from src.core.sse_hub import SSEHub


class _FailingPublishRedis:
    """Минимальный stub: publish всегда RedisError (контракт внешнего сбоя)."""

    async def publish(self, channel: str, message: str) -> int:
        raise RedisError("redis unavailable")


@pytest.fixture
async def fake_redis():
    client = FakeAsyncRedis()
    try:
        yield client
    finally:
        await client.aclose()


def test__parse_user_id_from_channel__str_and_bytes():
    assert parse_user_id_from_channel(channel="notifications:user:42") == 42
    assert parse_user_id_from_channel(channel=b"notifications:user:7") == 7


def test__parse_user_id_from_channel__invalid():
    with pytest.raises(ValueError):
        parse_user_id_from_channel(channel="other:1")


async def test__publish_many__redis_error_does_not_raise():
    hub = SSEHub()
    bus = RedisNotificationBus(client=_FailingPublishRedis(), hub=hub)
    await bus.publish_many(user_ids={1, 2})


async def test__publish_many__empty_is_noop(fake_redis: FakeAsyncRedis):
    hub = SSEHub()
    bus = RedisNotificationBus(client=fake_redis, hub=hub)
    await bus.publish_many(user_ids=set())


async def test__deliver_pmessage__puts_into_hub(fake_redis: FakeAsyncRedis):
    hub = SSEHub()
    bus = RedisNotificationBus(client=fake_redis, hub=hub)
    queue = await hub.subscribe(user_id=11)

    await bus._deliver_pmessage(
        message={
            "type": "pmessage",
            "channel": b"notifications:user:11",
            "data": b'{"type": "notification.invalidate"}',
        },
    )

    payload = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert payload == {"type": "notification.invalidate"}


async def test__publish_many__reaches_hub_via_listener(fake_redis: FakeAsyncRedis):
    """
    publish_many → fakeredis pubsub → listen_forever → hub.

    Если pubsub fakeredis нестабилен — падает отдельно; логика
    доставки покрыта ``test__deliver_pmessage__puts_into_hub``.
    """
    hub = SSEHub()
    bus = RedisNotificationBus(client=fake_redis, hub=hub)
    queue = await hub.subscribe(user_id=99)

    listener = asyncio.create_task(bus.listen_forever())
    try:
        # дать psubscribe установиться
        await asyncio.sleep(0.1)
        await bus.publish_many(user_ids={99})
        payload = await asyncio.wait_for(queue.get(), timeout=2.0)
        assert payload["type"] == "notification.invalidate"
    finally:
        listener.cancel()
        with suppress(asyncio.CancelledError):
            await listener
