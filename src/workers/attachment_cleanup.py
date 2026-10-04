"""
Entrypoint worker чистки pending-вложений.

Запуск::

    python -m src.workers.attachment_cleanup
"""

from __future__ import annotations

import asyncio
import logging
import signal

from src.core.config import configs
from src.core.database import db
from src.repository.attachment import AttachmentRepository
from src.services.attachment_cleanup import AttachmentCleanupService

logger = logging.getLogger(__name__)


async def run_forever() -> None:
    """
    Цикл: tick → sleep(interval) до SIGINT/SIGTERM.

    Отдельный процесс (как deadline_reminders): без S3-клиента —
    объекты ``tmp/`` чистит lifecycle бакета.
    """
    await db.connect()

    cleanup = AttachmentCleanupService(
        repository=AttachmentRepository(pool=db.pool),
        ttl=configs.attachment_pending_ttl,
    )
    interval = configs.attachment_cleanup_interval_sec
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()

    def _request_stop() -> None:
        logger.info("attachment cleanup worker shutdown requested")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            pass

    logger.info(
        "attachment cleanup worker started",
        extra={
            "interval_sec": interval,
            "ttl_sec": configs.attachment_pending_ttl.total_seconds(),
        },
    )
    try:
        while not stop.is_set():
            try:
                await cleanup.tick()
            except Exception:
                logger.exception("attachment cleanup tick failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
    finally:
        await db.disconnect()
        logger.info("attachment cleanup worker stopped")


def main() -> None:
    """Синхронная точка входа ``python -m``."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
