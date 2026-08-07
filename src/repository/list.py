import asyncpg

from src.models.lists import CustomList
from src.repository.base import BaseRepository


class ListRepository(BaseRepository):
    # pg_advisory_xact_lock(key1, key2): key1 = namespace, key2 = user_id
    _LISTS_LOCK_NS = 759214

    def __init__(self, pool: asyncpg.Pool):
        super().__init__(pool)
        self.list_model = CustomList

    async def get_custom_lists(self, user_id: int) -> list[CustomList]:
        query = """
            SELECT id, name, position, user_id, created_at
            FROM lists
            WHERE user_id = $1 AND type = 'user'
            ORDER BY position
        """
        rows = await self.query(query, user_id)
        return [self.list_model(**row) for row in rows]

    async def create_custom_list(self, user_id: int, list_name: str, limit: int) -> CustomList | None:
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
        query = """
            UPDATE lists SET name = $3 WHERE user_id = $1 and id = $2 
            RETURNING id, name, position, user_id, created_at
        """
        row = await self.one(query, user_id, list_id, list_name)
        if row is not None:
            return self.list_model(**row)

    async def reorder_custom_list(self, user_id: int, list_id: int, position: int) -> CustomList | None:
        """Перемещает user-список на ``position`` с каскадным сдвигом соседей.

        В одной транзакции:
        1. advisory lock по ``user_id`` (тот же namespace, что create);
        2. читает текущую позицию target (`FOR UPDATE`);
        3. clamp ``position`` в ``[1, count]``;
        4. если позиция не меняется — возвращает строку as-is;
        5. сдвигает соседей: вниз ``(old, new]`` → ``-1``, вверх ``[new, old)`` → ``+1``;
        6. пишет target ``position = new_pos``.

        Returns:
            обновлённый список или ``None``, если список не найден.
        """
        async with self.transaction() as conn:
            await conn.execute(
                "SELECT pg_advisory_xact_lock($1, $2)",
                self._LISTS_LOCK_NS,
                user_id,
            )

            target = await conn.fetchrow(
                """
                SELECT id, position
                FROM lists
                WHERE user_id = $1 AND id = $2 AND type = 'user'
                FOR UPDATE
                """,
                user_id,
                list_id,
            )
            if target is None:
                return None

            old_pos: int = target["position"]
            cnt: int = await conn.fetchval(
                """
                SELECT COUNT(*)::int
                FROM lists
                WHERE user_id = $1 AND type = 'user'
                """,
                user_id,
            )
            new_pos = min(max(position, 1), cnt)

            if old_pos == new_pos:
                row = await conn.fetchrow(
                    """
                    SELECT id, name, position, user_id, created_at
                    FROM lists
                    WHERE id = $1
                    """,
                    list_id,
                )
                return self.list_model(**row)

            if old_pos < new_pos:
                await conn.execute(
                    """
                    UPDATE lists
                    SET position = position - 1
                    WHERE user_id = $1
                      AND type = 'user'
                      AND position > $2
                      AND position <= $3
                    """,
                    user_id,
                    old_pos,
                    new_pos,
                )
            else:
                await conn.execute(
                    """
                    UPDATE lists
                    SET position = position + 1
                    WHERE user_id = $1
                      AND type = 'user'
                      AND position >= $2
                      AND position < $3
                    """,
                    user_id,
                    new_pos,
                    old_pos,
                )

            row = await conn.fetchrow(
                """
                UPDATE lists
                SET position = $3
                WHERE user_id = $1 AND id = $2
                RETURNING id, name, position, user_id, created_at
                """,
                user_id,
                list_id,
                new_pos,
            )
            return self.list_model(**row)

    async def delete_custom_list(self, user_id: int, list_id: int) -> CustomList | None:
        ...
