"""Тик чистки брошенных pending-вложений (БД; tmp в S3 — lifecycle)."""

from __future__ import annotations

import logging
from datetime import timedelta

from src.core.attachment_metrics import (
    ATTACHMENT_CLEANUP_DELETED,
    ATTACHMENT_CLEANUP_RUNS,
    ATTACHMENT_PENDING_GAUGE,
)
from src.repository.attachment import AttachmentRepository

logger = logging.getLogger(__name__)


class AttachmentCleanupService:
    """Один тик: lock → DELETE stale pending → gauge оставшихся."""

    def __init__(
            self,
            repository: AttachmentRepository,
            ttl: timedelta,
    ):
        """
        Инициализирует сервис чистки pending.

        :param repository: AttachmentRepository.
        :param ttl: возраст pending до удаления строки (default 24h).
        """
        self.repository = repository
        self.ttl = ttl

    async def tick(self) -> int:
        """
        Один тик: advisory lock → удалить pending старше ``ttl``.

        При занятом lock тик пропускается (``-1``).
        Объекты ``tmp/pending/`` не трогаем — expire на бакете.

        :returns: число удалённых строк; ``-1`` если lock занят.
        """
        ATTACHMENT_CLEANUP_RUNS.inc()
        async with self.repository.transaction() as conn:
            locked, deleted = await self.repository.delete_stale_pending(
                older_than=self.ttl,
                conn=conn,
            )
            if not locked:
                logger.info("attachment cleanup tick skipped: lock busy")
                return -1

        if deleted:
            ATTACHMENT_CLEANUP_DELETED.inc(amount=deleted)

        remaining = await self.repository.count_pending()
        ATTACHMENT_PENDING_GAUGE.set(remaining)

        logger.info(
            "attachment cleanup tick done",
            extra={
                "deleted": deleted,
                "pending_remaining": remaining,
                "ttl_sec": self.ttl.total_seconds(),
            },
        )
        return deleted
