"""
Entrypoint worker напоминаний о дедлайне.

Запуск::

    python -m src.workers.deadline_reminders
"""

from __future__ import annotations

import asyncio
import logging
import signal

import redis.asyncio as redis

from src.core.config import configs
from src.core.database import db
from src.core.redis_notification_bus import RedisNotificationBus
from src.repository.notification import NotificationRepository
from src.repository.task import TaskRepository
from src.services.deadline_reminders import DeadlineRemindersService
from src.services.notification import NotificationService

logger = logging.getLogger(__name__)


async def run_forever() -> None:
    """
    Цикл: tick → sleep(interval) до SIGINT/SIGTERM.

    Отдельный процесс: Redis client + bus только для publish
    (без SSEHub / listener — их поднимает uvicorn lifespan).
    """
    await db.connect()

    redis_pool = redis.ConnectionPool.from_url(configs.redis_url)
    redis_client = redis.Redis.from_pool(redis_pool)
    notification_bus = RedisNotificationBus(client=redis_client)
    notification_service = NotificationService(
        repository=NotificationRepository(pool=db.pool),
    )
    reminders = DeadlineRemindersService(
        task_repository=TaskRepository(pool=db.pool),
        notification_service=notification_service,
        window=configs.deadline_reminder_window,
        publisher=notification_bus,
    )
    interval = configs.deadline_worker_interval_sec
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()

    def _request_stop() -> None:
        logger.info("deadline worker shutdown requested")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            # Windows / ограниченные loops — Ctrl+C всё равно прервёт sleep
            pass

    logger.info(
        "deadline worker started",
        extra={
            "interval_sec": interval,
            "window_sec": configs.deadline_reminder_window.total_seconds(),
        },
    )
    try:
        while not stop.is_set():
            try:
                await reminders.tick()
            except Exception:
                logger.exception("deadline reminders tick failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
    finally:
        await redis_client.aclose()
        await db.disconnect()
        logger.info("deadline worker stopped")


def main() -> None:
    """Синхронная точка входа ``python -m``."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
