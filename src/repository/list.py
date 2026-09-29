from datetime import datetime, timezone

import asyncpg

from src.models.lists import CustomList
from src.repository.base import BaseRepository


class ListRepository(BaseRepository):
    """Репозиторий пользовательских списков задач (type=user)."""

    # pg_advisory_xact_lock(key1, key2): key1 = namespace, key2 = user_id
    _LISTS_LOCK_NS = 759214

    def __init__(self, pool: asyncpg.Pool):
        """
        Инициализирует репозиторий списков.

        :param pool: пул соединений asyncpg.
        """
        super().__init__(pool)
        self.list_model = CustomList

    async def get_custom_lists(self, user_id: int) -> list[CustomList]:
        """
        Возвращает user-списки владельца по position.

        :param user_id: идентификатор владельца списков.
        :returns: список ``CustomList``, отсортированный по position.
        """
        query = """
            SELECT id, name, position, user_id, created_at
            FROM lists
            WHERE user_id = $1 AND type = 'user'
            ORDER BY position
        """
        rows = await self.query(query, user_id)
        return [self.list_model(**row) for row in rows]

    async def create_custom_list(self, user_id: int, list_name: str, limit: int) -> CustomList | None:
        """
        Создаёт user-список с advisory lock и лимитом.

        Позиция = max(position) + 1. При достижении ``limit`` INSERT не выполняется.

        :param user_id: идентификатор владельца.
        :param list_name: имя нового списка.
        :param limit: максимальное число user-списков у пользователя.
        :returns: созданный ``CustomList`` или ``None``, если лимит исчерпан.
        """
        # RR not needed — xact advisory lock covers limit race; default READ COMMITTED is fine.
        query = """
            WITH _lock AS (
                SELECT pg_advisory_xact_lock($1, $2)
            ),
            stats AS (
                SELECT COUNT(*)::int AS cnt,
                       COALESCE(MAX(position), 0) AS max_pos
                FROM lists
                WHERE user_id = $2 AND type = 'user'
            )
            INSERT INTO lists (user_id, type, name, position)
            SELECT $2, 'user', $3, stats.max_pos + 1
            FROM stats, _lock
            WHERE stats.cnt < $4
            RETURNING id, name, position, user_id, created_at
        """
        row = await self.one(query, self._LISTS_LOCK_NS, user_id, list_name, limit)
        if row is not None:
            return self.list_model(**row)

    async def rename_custom_list(self, user_id: int, list_id: int, list_name: str) -> CustomList | None:
        """
        Переименовывает user-список владельца.

        :param user_id: идентификатор владельца.
        :param list_id: идентификатор списка.
        :param list_name: новое имя списка.
        :returns: обновлённый ``CustomList`` или ``None``, если не найден.
        """
        query = """
            UPDATE lists SET name = $3 WHERE user_id = $1 and id = $2 
            RETURNING id, name, position, user_id, created_at
        """
        row = await self.one(query, user_id, list_id, list_name)
        if row is not None:
            return self.list_model(**row)

    async def reorder_custom_list(self, user_id: int, list_id: int, position: int) -> CustomList | None:
        """
        Перемещает user-список на position со сдвигом соседей.

        Один CTE round-trip:
        1. advisory lock по ``user_id`` (тот же namespace, что create);
        2. читает текущую позицию target (`FOR UPDATE`);
        3. clamp ``position`` в ``[1, count]``;
        4. если позиция не меняется — возвращает строку as-is;
        5. сдвигает соседей: вниз ``(old, new]`` → ``-1``, вверх ``[new, old)`` → ``+1``;
        6. пишет target ``position = new_pos``.

        :param user_id: идентификатор владельца.
        :param list_id: идентификатор перемещаемого списка.
        :param position: желаемая позиция (будет ограничена диапазоном).
        :returns: обновлённый список или ``None``, если список не найден.
        """
        query = """
            WITH _lock AS (
                SELECT pg_advisory_xact_lock($1, $2)
            ),
            target AS (
                SELECT l.id, l.name, l.position, l.user_id, l.created_at
                FROM lists l
                CROSS JOIN _lock
                WHERE l.user_id = $2 AND l.id = $3 AND l.type = 'user'
                FOR UPDATE OF l
            ),
            stats AS (
                SELECT COUNT(*)::int AS cnt
                FROM lists
                WHERE user_id = $2 AND type = 'user'
            ),
            bounds AS (
                SELECT
                    target.id,
                    target.name,
                    target.user_id,
                    target.created_at,
                    target.position AS old_pos,
                    LEAST(GREATEST($4::int, 1), stats.cnt) AS new_pos
                FROM target
                CROSS JOIN stats
            ),
            shifted AS (
                UPDATE lists l
                SET position = CASE
                    WHEN b.old_pos < b.new_pos THEN l.position - 1
                    ELSE l.position + 1
                END
                FROM bounds b
                WHERE l.user_id = $2
                  AND l.type = 'user'
                  AND b.old_pos <> b.new_pos
                  AND (
                      (b.old_pos < b.new_pos
                       AND l.position > b.old_pos
                       AND l.position <= b.new_pos)
                      OR
                      (b.old_pos > b.new_pos
                       AND l.position >= b.new_pos
                       AND l.position < b.old_pos)
                  )
                RETURNING l.id
            ),
            updated AS (
                UPDATE lists l
                SET position = b.new_pos
                FROM bounds b
                WHERE l.id = b.id
                  AND b.old_pos <> b.new_pos
                  AND (SELECT COUNT(*) FROM shifted) >= 0
                RETURNING l.id, l.name, l.position, l.user_id, l.created_at
            )
            SELECT
                COALESCE(u.id, b.id) AS id,
                COALESCE(u.name, b.name) AS name,
                COALESCE(u.position, b.new_pos) AS position,
                COALESCE(u.user_id, b.user_id) AS user_id,
                COALESCE(u.created_at, b.created_at) AS created_at
            FROM bounds b
            LEFT JOIN updated u ON TRUE
        """
        row = await self.one(query, self._LISTS_LOCK_NS, user_id, list_id, position)
        if row is not None:
            return self.list_model(**row)

    async def delete_custom_list(self, user_id: int, list_id: int) -> CustomList | None:
        """
        Hard delete user-списка с trash задач и компактом.

        Один CTE + UTC timestamps из приложения:
        1. advisory lock по ``user_id``;
        2. читает target (`FOR UPDATE`, только ``type = 'user'``);
        3. все задачи с ``list_id = target``: ``previous_list_id = list_id``,
           ``list_id = Inbox`` (FK), ``deleted_at = COALESCE(deleted_at, $now)``,
           ``updated_at = $now``;
        4. ``DELETE`` строки списка;
        5. сдвигает позиции соседей справа на ``-1``.

        :param user_id: идентификатор владельца.
        :param list_id: идентификатор удаляемого списка.
        :returns: удалённый список или ``None``, если не найден / не user-тип.
        """
        now = datetime.now(timezone.utc)
        query = """
            WITH _lock AS (
                SELECT pg_advisory_xact_lock($1, $2)
            ),
            target AS (
                SELECT l.id, l.name, l.position, l.user_id, l.created_at
                FROM lists l
                CROSS JOIN _lock
                WHERE l.user_id = $2 AND l.id = $3 AND l.type = 'user'
                FOR UPDATE OF l
            ),
            trashed AS (
                UPDATE tasks t
                SET previous_list_id = t.list_id,
                    list_id = (SELECT id FROM lists WHERE type = 'inbox'),
                    deleted_at = COALESCE(t.deleted_at, $4::timestamptz),
                    updated_at = $4::timestamptz
                FROM target
                WHERE t.user_id = $2 AND t.list_id = target.id
                RETURNING t.id
            ),
            deleted AS (
                DELETE FROM lists l
                USING target
                WHERE l.id = target.id
                  AND (SELECT COUNT(*) FROM trashed) >= 0
                RETURNING l.id
            ),
            compacted AS (
                UPDATE lists l
                SET position = l.position - 1
                FROM target
                WHERE l.user_id = $2
                  AND l.type = 'user'
                  AND l.position > target.position
                  AND EXISTS (SELECT 1 FROM deleted)
                RETURNING l.id
            )
            SELECT target.id, target.name, target.position, target.user_id, target.created_at
            FROM target
            WHERE EXISTS (SELECT 1 FROM deleted)
              AND (SELECT COUNT(*) FROM compacted) >= 0
        """
        row = await self.one(query, self._LISTS_LOCK_NS, user_id, list_id, now)
        if row is not None:
            return self.list_model(**row)
