import json
from typing import Any

import asyncpg
from asyncpg import Connection, Record

from src.models.notification import (
    Notification,
    NotificationEvent,
    UnreadCountResponse,
)
from src.repository.base import BaseRepository


class NotificationRepository(BaseRepository):
    """Репозиторий уведомлений: create, list, unread, mark read/unread."""

    def __init__(self, pool: asyncpg.Pool):
        """
        Инициализирует репозиторий уведомлений.

        :param pool: пул соединений asyncpg.
        """
        super().__init__(pool)
        self.notification_model = Notification

    def _to_notification(self, row: Record) -> Notification:
        """
        Маппит Record в Notification (jsonb → dict).

        :param row: строка SELECT из notification.
        :returns: pydantic-модель уведомления.
        """
        data = dict(row)
        metadata = data.get("metadata")
        if isinstance(metadata, str):
            data["metadata"] = json.loads(metadata)
        elif metadata is None:
            data["metadata"] = {}
        return self.notification_model(**data)

    async def create_for_recipients(
            self,
            event: NotificationEvent,
            conn: Connection | None = None,
    ) -> set[int]:
        """
        Вставляет уведомления с ON CONFLICT DO NOTHING.

        actor_id вычитается из recipient_ids. Пустой набор — no-op.
        Не делает commit: при переданном ``conn`` работает в его
        транзакции; без ``conn`` — отдельный acquire (autocommit).

        :param event: контракт события уведомления.
        :param conn: соединение открытой транзакции вызывающего кода.
        :returns: recipient_id, для которых реально вставилась строка.
        """
        recipients = set(event.recipient_ids)
        if event.actor_id is not None:
            recipients.discard(event.actor_id)
        if not recipients:
            return set()

        query = """
            INSERT INTO notification (
                event_id, type, category, severity, actor_id, recipient_id,
                entity_type, entity_id, title, body, metadata, deep_link,
                grouping_key, occurred_at
            )
            SELECT
                $1, $2, $3, $4, $5, unnest($6::int[]),
                $7, $8, $9, $10, $11::jsonb, $12,
                $13, $14
            ON CONFLICT (event_id, recipient_id) DO NOTHING
            RETURNING recipient_id
        """
        args = (
            event.event_id,
            event.type,
            event.category,
            event.severity,
            event.actor_id,
            list(recipients),
            event.entity_type,
            event.entity_id,
            event.title,
            event.body,
            json.dumps(event.metadata),
            event.deep_link,
            event.grouping_key,
            event.occurred_at,
        )
        if conn is not None:
            rows = await conn.fetch(query, *args)
        else:
            rows = await self.query(query, *args)
        return {row["recipient_id"] for row in rows}

    async def list_notifications(
            self,
            recipient_id: int,
            limit: int,
            before_id: int | None = None,
            unread: bool | None = None,
            category: str | None = None,
            important: bool | None = None,
    ) -> list[Notification]:
        """
        Список уведомлений получателя, id DESC, cursor before_id.

        Берёт ``limit`` строк (вызывающий добавляет +1 для has_more).

        :param recipient_id: владелец ленты.
        :param limit: максимум строк в выборке.
        :param before_id: курсор — только id строго меньше.
        :param unread: True → только непрочитанные; False → только прочитанные.
        :param category: фильтр по category.
        :param important: True → только severity=important.
        :returns: список ``Notification``.
        """
        query = """
            SELECT
                id, type, category, severity, actor_id,
                entity_type, entity_id, title, body, metadata,
                deep_link, group_count, created_at, read_at
            FROM notification
            WHERE recipient_id = $1
              AND ($2::bigint IS NULL OR id < $2)
              AND (
                    $3::bool IS NULL
                    OR ($3 = true AND read_at IS NULL)
                    OR ($3 = false AND read_at IS NOT NULL)
              )
              AND ($4::text IS NULL OR category = $4)
              AND (
                    $5::bool IS NULL
                    OR ($5 = true AND severity = 'important')
                    OR ($5 = false AND severity = 'normal')
              )
            ORDER BY id DESC
            LIMIT $6
        """
        rows = await self.query(
            query,
            recipient_id,
            before_id,
            unread,
            category,
            important,
            limit,
        )
        return [self._to_notification(row) for row in rows]

    async def get_unread_counts(self, recipient_id: int) -> UnreadCountResponse:
        """
        Счётчики непрочитанных: total, important, by_category.

        :param recipient_id: владелец ленты.
        :returns: ``UnreadCountResponse``.
        """
        query = """
            WITH unread AS (
                SELECT category, severity
                FROM notification
                WHERE recipient_id = $1 AND read_at IS NULL
            )
            SELECT
                (SELECT COUNT(*)::int FROM unread) AS total,
                (SELECT COUNT(*)::int FROM unread WHERE severity = 'important') AS important,
                COALESCE(
                    (
                        SELECT jsonb_object_agg(category, cnt)
                        FROM (
                            SELECT category, COUNT(*)::int AS cnt
                            FROM unread
                            GROUP BY category
                        ) t
                    ),
                    '{}'::jsonb
                ) AS by_category
        """
        row = await self.one(query, recipient_id)
        by_category: dict[str, Any] = row["by_category"]
        if isinstance(by_category, str):
            by_category = json.loads(by_category)
        return UnreadCountResponse(
            total=row["total"],
            important=row["important"],
            by_category={str(k): int(v) for k, v in by_category.items()},
        )

    async def mark_read(
            self,
            recipient_id: int,
            ids: list[int],
    ) -> list[int]:
        """
        Отмечает выбранные уведомления прочитанными.

        :param recipient_id: владелец (фильтр в SQL).
        :param ids: id уведомлений.
        :returns: id реально обновлённых строк.
        """
        if not ids:
            return []
        query = """
            UPDATE notification
            SET read_at = now()
            WHERE recipient_id = $1
              AND id = ANY($2::bigint[])
              AND read_at IS NULL
            RETURNING id
        """
        rows = await self.query(query, recipient_id, ids)
        return [row["id"] for row in rows]

    async def mark_read_all(
            self,
            recipient_id: int,
            category: str | None = None,
    ) -> list[int]:
        """
        Отмечает все непрочитанные (опционально по category).

        :param recipient_id: владелец (фильтр в SQL).
        :param category: если задан — только эта category.
        :returns: id реально обновлённых строк.
        """
        query = """
            UPDATE notification
            SET read_at = now()
            WHERE recipient_id = $1
              AND read_at IS NULL
              AND ($2::text IS NULL OR category = $2)
            RETURNING id
        """
        rows = await self.query(query, recipient_id, category)
        return [row["id"] for row in rows]

    async def mark_unread(
            self,
            recipient_id: int,
            ids: list[int],
    ) -> list[int]:
        """
        Возвращает уведомления в непрочитанные.

        :param recipient_id: владелец (фильтр в SQL).
        :param ids: id уведомлений.
        :returns: id реально обновлённых строк.
        """
        if not ids:
            return []
        query = """
            UPDATE notification
            SET read_at = NULL
            WHERE recipient_id = $1
              AND id = ANY($2::bigint[])
              AND read_at IS NOT NULL
            RETURNING id
        """
        rows = await self.query(query, recipient_id, ids)
        return [row["id"] for row in rows]
