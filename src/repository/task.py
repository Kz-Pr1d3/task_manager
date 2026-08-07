import zlib
from datetime import datetime
from typing import Any, Optional

import asyncpg

from src.models.tasks import Task
from src.repository.base import BaseRepository


class TaskRepository(BaseRepository):
    # pg_advisory_xact_lock(key1, key2): key1 = namespace, key2 = hash(user_id:list_id)
    _TASKS_LOCK_NS = 759215

    def __init__(self, pool: asyncpg.Pool):
        super().__init__(pool)
        self.task_model = Task

    async def get_task(self, user_id: int, task_id: int) -> Task | None:
        query = """
            SELECT * FROM tasks
            WHERE user_id = $1 AND id = $2
        """
        row = await self.one(query, user_id, task_id)
        if row is not None:
            return self.task_model(**row)

    async def list_tasks(
            self,
            user_id: int,
            list_id: int,
            limit: int,
            cursor: Optional[int] = None,
            cursor_created_at: Optional[datetime] = None,
    ) -> list[Task]:
        """Корневые задачи списка с keyset-пагинацией.

        Фильтр: user_id, list_id, parent_id IS NULL, deleted_at IS NULL.
        Сортировка: created_at ASC, id ASC. Курсор — пара
        (cursor_created_at, cursor).
        :param user_id: владелец задач.
        :param list_id: физический список.
        :param limit: размер страницы.
        :param cursor: id последней задачи предыдущей страницы.
        :param cursor_created_at: companion к cursor (created_at).
        :returns: список задач текущей страницы.
        """
        if cursor is None:
            query = """
                SELECT * FROM tasks
                WHERE user_id = $1
                  AND list_id = $2
                  AND parent_id IS NULL
                  AND deleted_at IS NULL
                ORDER BY created_at ASC, id ASC
                LIMIT $3
            """
            rows = await self.query(query, user_id, list_id, limit)
        else:
            query = """
                SELECT * FROM tasks
                WHERE user_id = $1
                  AND list_id = $2
                  AND parent_id IS NULL
                  AND deleted_at IS NULL
                  AND (created_at, id) > ($4::timestamptz, $5)
                ORDER BY created_at ASC, id ASC
                LIMIT $3
            """
            rows = await self.query(
                query,
                user_id,
                list_id,
                limit,
                cursor_created_at,
                cursor,
            )
        return [self.task_model(**row) for row in rows]

    async def is_writable_list(self, user_id: int, list_id: int) -> bool:
        """Inbox (общий) или user-список текущего пользователя."""
        query = """
            SELECT EXISTS(
                SELECT 1 FROM lists
                WHERE id = $1
                  AND (
                      type = 'inbox'
                      OR (type = 'user' AND user_id = $2)
                  )
            ) AS ok
        """
        row = await self.one(query, list_id, user_id)
        return bool(row["ok"])

    async def create_task(
            self,
            user_id: int,
            list_id: int,
            title: str,
            due_date: Optional[datetime] = None,
            parent_id: Optional[int] = None,
            *,
            limit: int,
    ) -> Task | None:
        """Создаёт задачу в доступном списке с лимитом.

        Атомарно: lock → list access → count → INSERT при cnt < limit.
        ``None`` = список недоступен **или** лимит; различай через ``is_writable_list``.
        """
        # стабильный int4-ключ (hash() рандомизируется между воркерами)
        lock_key = zlib.crc32(f"{user_id}:{list_id}".encode()) & 0x7FFFFFFF
        query = """
            WITH _lock AS (
                SELECT pg_advisory_xact_lock($1, $2)
            ),
            list_ok AS (
                SELECT id FROM lists
                WHERE id = $4
                  AND (
                      type = 'inbox'
                      OR (type = 'user' AND user_id = $3)
                  )
            ),
            stats AS (
                SELECT COUNT(*)::int AS cnt
                FROM tasks
                WHERE user_id = $3 AND list_id = $4 AND deleted_at IS NULL
            )
            INSERT INTO tasks (user_id, list_id, title, due_date, parent_id, status)
            SELECT $3, list_ok.id, $5, $6::timestamptz, $7::int, 'active'
            FROM list_ok, stats, _lock
            WHERE stats.cnt < $8
            RETURNING *
        """
        row = await self.one(
            query,
            self._TASKS_LOCK_NS,
            lock_key,
            user_id,
            list_id,
            title,
            due_date,
            parent_id,
            limit,
        )
        if row is not None:
            return self.task_model(**row)

    async def update_task_info(self, user_id: int, task_id: int, info: dict[str, Any]) -> Task | None:
        cols = []
        values = []
        for i, (key, value) in enumerate(info.items(), start=3):
            cols.append(f"{key} = ${i}")
            values.append(value)
        set_query = ", ".join(cols)

        query = f"""
            UPDATE tasks SET {set_query}, updated_at = now()
            WHERE user_id = $1 AND id = $2
            RETURNING *
        """
        row = await self.one(query, user_id, task_id, *values)
        if row is not None:
            return self.task_model(**row)

    async def move_task(
            self,
            user_id: int,
            task_id: int,
            list_id: int,
            *,
            limit: int,
    ) -> Task | None:
        """Перемещает задачу и прямых потомков в другой список.

        Атомарно: lock → задача не в trash → list writable →
        ``target_cnt + subtree_cnt <= limit`` → UPDATE ``list_id``
        (root + ``parent_id = root``). ``previous_list_id`` не трогаем.
        ``None`` = задача/список недоступны **или** лимит.
        """
        lock_key = zlib.crc32(f"{user_id}:{list_id}".encode()) & 0x7FFFFFFF
        query = """
            WITH _lock AS (
                SELECT pg_advisory_xact_lock($1, $2)
            ),
            src AS (
                SELECT id, list_id
                FROM tasks
                WHERE user_id = $3 AND id = $4 AND deleted_at IS NULL
            ),
            list_ok AS (
                SELECT id FROM lists
                WHERE id = $5
                  AND (
                      type = 'inbox'
                      OR (type = 'user' AND user_id = $3)
                  )
            ),
            subtree AS (
                SELECT COUNT(*)::int AS cnt
                FROM tasks
                WHERE user_id = $3
                  AND deleted_at IS NULL
                  AND (id = $4 OR parent_id = $4)
            ),
            target_stats AS (
                SELECT COUNT(*)::int AS cnt
                FROM tasks
                WHERE user_id = $3 AND list_id = $5 AND deleted_at IS NULL
            ),
            moved AS (
                UPDATE tasks t
                SET list_id = list_ok.id,
                    updated_at = now()
                FROM src, list_ok, subtree, target_stats, _lock
                WHERE t.user_id = $3
                  AND (t.id = src.id OR t.parent_id = src.id)
                  AND src.list_id IS DISTINCT FROM $5
                  AND target_stats.cnt + subtree.cnt <= $6
                RETURNING t.*
            )
            SELECT * FROM moved WHERE id = $4
        """
        row = await self.one(
            query,
            self._TASKS_LOCK_NS,
            lock_key,
            user_id,
            task_id,
            list_id,
            limit,
        )
        if row is not None:
            return self.task_model(**row)

    async def complete_task(self, user_id: int, task_id: int) -> Task | None:
        """Завершает задачу и прямых потомков; auto-complete родителя.

        Root + ``parent_id = root`` → status=completed, completed_at=now().
        Если завершили подзадачу и все siblings completed — родитель тоже.
        :param user_id: владелец.
        :param task_id: задача (корень или подзадача).
        :returns: обновлённая задача или None если не найдена.
        """
        async with self.transaction() as conn:
            rows = await conn.fetch(
                """
                UPDATE tasks
                SET status = 'completed',
                    completed_at = COALESCE(completed_at, now()),
                    updated_at = now()
                WHERE user_id = $1
                  AND (id = $2 OR parent_id = $2)
                RETURNING *
                """,
                user_id,
                task_id,
            )
            if not rows:
                return None

            root = next(row for row in rows if row["id"] == task_id)

            if root["parent_id"] is not None:
                await conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'completed',
                        completed_at = COALESCE(completed_at, now()),
                        updated_at = now()
                    WHERE id = $2
                      AND user_id = $1
                      AND NOT EXISTS (
                          SELECT 1 FROM tasks
                          WHERE parent_id = $2
                            AND user_id = $1
                            AND deleted_at IS NULL
                            AND status <> 'completed'
                      )
                    """,
                    user_id,
                    root["parent_id"],
                )

            return self.task_model(**root)

    async def trash_task(self, user_id: int, task_id: int) -> Task | None:
        """Soft delete: previous_list_id + deleted_at для root и потомков.

        :param user_id: владелец.
        :param task_id: корень каскада.
        :returns: обновлённый root или None если не найден.
        """
        query = """
            WITH updated AS (
                UPDATE tasks
                SET previous_list_id = list_id,
                    deleted_at = now(),
                    updated_at = now()
                WHERE user_id = $1
                  AND (id = $2 OR parent_id = $2)
                RETURNING *
            )
            SELECT * FROM updated WHERE id = $2
        """
        row = await self.one(query, user_id, task_id)
        if row is not None:
            return self.task_model(**row)

    async def restore_task(
            self,
            user_id: int,
            task_id: int,
            list_id: int,
            *,
            limit: int,
    ) -> Task | None:
        """Restore из корзины в ``list_id`` с проверкой лимита.

        Атомарно: lock → задача в trash → count + subtree ≤ limit →
        deleted_at=NULL, list_id=target для root и потомков.
        ``None`` = нет в trash / не найдена / лимит.
        :param user_id: владелец.
        :param task_id: корень каскада.
        :param list_id: целевой физический список.
        :param limit: макс. задач в списке.
        :returns: восстановленный root или None.
        """
        lock_key = zlib.crc32(f"{user_id}:{list_id}".encode()) & 0x7FFFFFFF
        query = """
            WITH _lock AS (
                SELECT pg_advisory_xact_lock($1, $2)
            ),
            root AS (
                SELECT id
                FROM tasks
                WHERE user_id = $3 AND id = $4 AND deleted_at IS NOT NULL
            ),
            stats AS (
                SELECT COUNT(*)::int AS cnt
                FROM tasks
                WHERE user_id = $3 AND list_id = $5 AND deleted_at IS NULL
            ),
            subtree AS (
                SELECT COUNT(*)::int AS cnt
                FROM tasks t
                JOIN root ON TRUE
                WHERE t.user_id = $3
                  AND (t.id = root.id OR t.parent_id = root.id)
            ),
            updated AS (
                UPDATE tasks t
                SET deleted_at = NULL,
                    list_id = $5,
                    updated_at = now()
                FROM root, stats, subtree, _lock
                WHERE t.user_id = $3
                  AND (t.id = root.id OR t.parent_id = root.id)
                  AND stats.cnt + subtree.cnt <= $6
                RETURNING t.*
            )
            SELECT * FROM updated WHERE id = $4
        """
        row = await self.one(
            query,
            self._TASKS_LOCK_NS,
            lock_key,
            user_id,
            task_id,
            list_id,
            limit,
        )
        if row is not None:
            return self.task_model(**row)

    async def hard_delete_task(self, user_id: int, task_id: int) -> bool:
        """Hard delete root + потомков; только из корзины.

        :param user_id: владелец.
        :param task_id: корень каскада.
        :returns: True если root удалён, иначе False.
        """
        query = """
            DELETE FROM tasks
            WHERE user_id = $1
              AND deleted_at IS NOT NULL
              AND (id = $2 OR parent_id = $2)
            RETURNING id
        """
        rows = await self.query(query, user_id, task_id)
        return any(row["id"] == task_id for row in rows)

    async def get_subtasks(self, user_id: int, parent_id: int) -> list[Task]:
        """Возвращает неудалённые подзадачи родителя.

        :param user_id: владелец задач.
        :param parent_id: id родительской задачи.
        :returns: подзадачи в порядке создания.
        """
        query = """
            SELECT * FROM tasks
            WHERE user_id = $1
              AND parent_id = $2
              AND deleted_at IS NULL
            ORDER BY created_at ASC, id ASC
        """
        rows = await self.query(query, user_id, parent_id)
        return [self.task_model(**row) for row in rows]

    async def count_tasks_in_list(self, user_id: int, list_id: int) -> int:
        """Число неудалённых задач пользователя в списке."""
        query = """
            SELECT COUNT(*)::int AS cnt
            FROM tasks
            WHERE user_id = $1 AND list_id = $2 AND deleted_at IS NULL
        """
        row = await self.one(query, user_id, list_id)
        return int(row["cnt"])
