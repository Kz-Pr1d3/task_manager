"""Репозиторий вложений задач (task_attachment)."""

import zlib
from datetime import datetime, timedelta, timezone

import asyncpg
from asyncpg import Connection, Record

from src.models.attachments import AttachmentWriteResult, TaskAttachment
from src.models.enums import AttachmentWriteStatus
from src.repository.base import BaseRepository


class AttachmentRepository(BaseRepository):
    """CRUD pending/ready вложений + лимит на задачу."""

    # pg_advisory_xact_lock(key1, key2): key1 = namespace, key2 = hash(user_id:task_id)
    _ATTACHMENTS_LOCK_NS = 759217
    # отдельный namespace для cleanup worker (не пересекается с create pending)
    _CLEANUP_WORKER_LOCK_NS = 759218
    _CLEANUP_WORKER_LOCK_KEY = 1

    def __init__(self, pool: asyncpg.Pool):
        """
        Инициализирует репозиторий вложений.

        :param pool: пул соединений asyncpg.
        """
        super().__init__(pool)
        self.attachment_model = TaskAttachment

    @staticmethod
    def _task_lock_key(user_id: int, task_id: int) -> int:
        """
        Стабильный int4-ключ для ``pg_advisory_xact_lock``.

        Сериализует create pending на одном ``(user_id, task_id)``,
        чтобы COUNT→INSERT не пробивал лимит гонкой.

        :param user_id: владелец.
        :param task_id: задача.
        :returns: int31-ключ для advisory lock.
        """
        return zlib.crc32(f"{user_id}:{task_id}".encode()) & 0x7FFFFFFF

    def _to_attachment(self, row: Record) -> TaskAttachment:
        """
        Маппит Record в TaskAttachment.

        :param row: строка SELECT из task_attachment.
        :returns: pydantic-модель вложения.
        """
        return self.attachment_model(**dict(row))

    def _to_write_result(self, row: Record) -> AttachmentWriteResult:
        """
        Собирает AttachmentWriteResult из строки с write_status.

        :param row: запись SQL с write_status и полями вложения.
        :returns: статус записи и вложение при ``ok``.
        """
        status = AttachmentWriteStatus(row["write_status"])
        if status is not AttachmentWriteStatus.ok:
            return AttachmentWriteResult(status=status)
        return AttachmentWriteResult(
            status=status,
            attachment=self._to_attachment(row),
        )

    async def create_pending(
        self,
        *,
        user_id: int,
        task_id: int,
        storage_key: str,
        original_name: str,
        content_type: str,
        size_bytes: int | None,
        limit: int,
    ) -> AttachmentWriteResult:
        """
        Создаёт pending-вложение с проверкой владельца и лимита.

        Атомарно: lock → task access → count (pending+ready) → INSERT.
        ``write_status``: ``ok`` | ``forbidden`` | ``limit``.

        :param user_id: владелец задачи.
        :param task_id: задача.
        :param storage_key: ключ объекта в S3 (обычно ``tmp/pending/...``).
        :param original_name: имя файла пользователя (≤255).
        :param content_type: MIME.
        :param size_bytes: заявленный размер (до complete может быть None).
        :param limit: максимум pending+ready на задачу.
        :returns: AttachmentWriteResult.
        """
        lock_key = self._task_lock_key(user_id, task_id)
        query = """
            WITH _lock AS (
                SELECT pg_advisory_xact_lock($1, $2)
            ),
            task_ok AS (
                SELECT id FROM tasks
                WHERE id = $3
                  AND user_id = $4
                  AND deleted_at IS NULL
            ),
            stats AS (
                SELECT COUNT(*)::int AS cnt
                FROM task_attachment
                WHERE task_id = $3
                  AND status IN ('pending', 'ready')
            ),
            ins AS (
                INSERT INTO task_attachment (
                    task_id, user_id, storage_key, original_name,
                    content_type, size_bytes, status
                )
                SELECT
                    task_ok.id, $4, $5, $6, $7, $8, 'pending'
                FROM task_ok, stats, _lock
                WHERE stats.cnt < $9
                RETURNING *
            ),
            meta AS (
                SELECT CASE
                    WHEN EXISTS (SELECT 1 FROM ins) THEN 'ok'
                    WHEN NOT EXISTS (SELECT 1 FROM task_ok) THEN 'forbidden'
                    ELSE 'limit'
                END AS write_status
            )
            SELECT meta.write_status, ins.*
            FROM meta
            LEFT JOIN ins ON TRUE
        """
        row = await self.one(
            query,
            self._ATTACHMENTS_LOCK_NS,
            lock_key,
            task_id,
            user_id,
            storage_key,
            original_name,
            content_type,
            size_bytes,
            limit,
        )
        return self._to_write_result(row)

    async def get_by_id(
        self,
        *,
        attachment_id: int,
        task_id: int,
        user_id: int,
    ) -> TaskAttachment | None:
        """
        Вложение по id с фильтром task+user (чужое → None).

        :param attachment_id: id вложения.
        :param task_id: задача.
        :param user_id: владелец.
        :returns: вложение или None.
        """
        query = """
            SELECT *
            FROM task_attachment
            WHERE id = $1
              AND task_id = $2
              AND user_id = $3
        """
        row = await self.one(query, attachment_id, task_id, user_id)
        if row is not None:
            return self._to_attachment(row)

    async def list_ready(
        self,
        *,
        task_id: int,
        user_id: int,
    ) -> list[TaskAttachment]:
        """
        Ready-вложения задачи (новые сверху).

        :param task_id: задача.
        :param user_id: владелец.
        :returns: список ready.
        """
        query = """
            SELECT *
            FROM task_attachment
            WHERE task_id = $1
              AND user_id = $2
              AND status = 'ready'
            ORDER BY created_at DESC, id DESC
        """
        rows = await self.query(query, task_id, user_id)
        return [self._to_attachment(row) for row in rows]

    async def count_ready(self, *, task_id: int, user_id: int) -> int:
        """
        Число ready-вложений задачи владельца.

        :param task_id: задача.
        :param user_id: владелец.
        :returns: количество.
        """
        query = """
            SELECT COUNT(*)::int AS cnt
            FROM task_attachment
            WHERE task_id = $1
              AND user_id = $2
              AND status = 'ready'
        """
        row = await self.one(query, task_id, user_id)
        return int(row["cnt"])

    async def mark_ready(
        self,
        *,
        attachment_id: int,
        task_id: int,
        user_id: int,
        storage_key: str,
        size_bytes: int,
        content_type: str,
    ) -> TaskAttachment | None:
        """
        Переводит pending → ready после успешного complete.

        :param attachment_id: id вложения.
        :param task_id: задача.
        :param user_id: владелец.
        :param storage_key: финальный ключ ``users/...``.
        :param size_bytes: фактический размер из head_object.
        :param content_type: фактический Content-Type.
        :returns: обновлённая строка или None.
        """
        now = datetime.now(timezone.utc)
        query = """
            UPDATE task_attachment
            SET status = 'ready',
                storage_key = $4,
                size_bytes = $5,
                content_type = $6,
                ready_at = $7::timestamptz
            WHERE id = $1
              AND task_id = $2
              AND user_id = $3
              AND status = 'pending'
            RETURNING *
        """
        row = await self.one(
            query,
            attachment_id,
            task_id,
            user_id,
            storage_key,
            size_bytes,
            content_type,
            now,
        )
        if row is not None:
            return self._to_attachment(row)

    async def mark_failed(
        self,
        *,
        attachment_id: int,
        task_id: int,
        user_id: int,
    ) -> TaskAttachment | None:
        """
        Переводит pending → failed.

        :param attachment_id: id вложения.
        :param task_id: задача.
        :param user_id: владелец.
        :returns: обновлённая строка или None.
        """
        query = """
            UPDATE task_attachment
            SET status = 'failed'
            WHERE id = $1
              AND task_id = $2
              AND user_id = $3
              AND status = 'pending'
            RETURNING *
        """
        row = await self.one(query, attachment_id, task_id, user_id)
        if row is not None:
            return self._to_attachment(row)

    async def delete(
        self,
        *,
        attachment_id: int,
        task_id: int,
        user_id: int,
    ) -> TaskAttachment | None:
        """
        Удаляет вложение; RETURNING для последующего delete_object.

        :param attachment_id: id вложения.
        :param task_id: задача.
        :param user_id: владелец.
        :returns: удалённая строка или None.
        """
        query = """
            DELETE FROM task_attachment
            WHERE id = $1
              AND task_id = $2
              AND user_id = $3
            RETURNING *
        """
        row = await self.one(query, attachment_id, task_id, user_id)
        if row is not None:
            return self._to_attachment(row)

    async def count_pending(self) -> int:
        """
        Число pending-вложений (метрика «висящих»).

        :returns: количество строк ``status=pending``.
        """
        query = """
            SELECT COUNT(*)::int AS cnt
            FROM task_attachment
            WHERE status = 'pending'
        """
        row = await self.one(query)
        return int(row["cnt"])

    async def delete_stale_pending(
        self,
        *,
        older_than: timedelta,
        conn: Connection,
    ) -> tuple[bool, int]:
        """
        Один CTE: try advisory lock + DELETE pending старше ``older_than``.

        Вызывать внутри открытой транзакции ``conn``. Если lock занят —
        ``(False, 0)`` (DELETE не выполняется); иначе ``(True, deleted_count)``.

        Объекты в ``tmp/pending/`` чистит lifecycle бакета — здесь только БД.

        :param older_than: TTL pending (например 24h).
        :param conn: соединение текущей транзакции worker.
        :returns: ``(locked, deleted_count)``.
        """
        cutoff = datetime.now(timezone.utc) - older_than
        row = await conn.fetchrow(
            """
            WITH lock AS (
                SELECT pg_try_advisory_xact_lock($1, $2) AS got
            ),
            gone AS (
                DELETE FROM task_attachment
                WHERE status = 'pending'
                  AND created_at < $3::timestamptz
                  AND (SELECT got FROM lock)
                RETURNING id
            )
            SELECT
                (SELECT got FROM lock) AS locked,
                (SELECT COUNT(*)::int FROM gone) AS deleted
            """,
            self._CLEANUP_WORKER_LOCK_NS,
            self._CLEANUP_WORKER_LOCK_KEY,
            cutoff,
        )
        return bool(row["locked"]), int(row["deleted"])
