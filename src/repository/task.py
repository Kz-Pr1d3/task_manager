import zlib
from datetime import datetime, timedelta
from typing import Any

import asyncpg
from asyncpg import Connection, Record

from src.models.enums import TaskWriteStatus
from src.models.tasks import DeadlineReminderCandidate, Task, TaskWriteResult
from src.repository.base import BaseRepository


class TaskRepository(BaseRepository):
    """Репозиторий задач: CRUD, move, trash/restore, лимиты."""

    # pg_advisory_xact_lock(key1, key2): key1 = namespace, key2 = hash(user_id:list_id)
    _TASKS_LOCK_NS = 759215
    # отдельный namespace для deadline worker (не пересекается с lists/tasks)
    _DEADLINE_WORKER_LOCK_NS = 759216
    _DEADLINE_WORKER_LOCK_KEY = 1

    def __init__(self, pool: asyncpg.Pool):
        """
        Инициализирует репозиторий задач.

        :param pool: пул соединений asyncpg.
        """
        super().__init__(pool)
        self.task_model = Task

    @staticmethod
    def _list_lock_key(user_id: int, list_id: int) -> int:
        """
        Стабильный int4-ключ для ``pg_advisory_xact_lock``.

        Сериализует create/move/restore на одном ``(user_id, list_id)``,
        чтобы COUNT→INSERT/UPDATE не пробивали лимит гонкой (TOCTOU).
        Лок в Postgres: воркеры с одним ``(ns, key)`` встают в очередь.
        ``zlib.crc32`` детерминирован (в отличие от ``hash()``);
        ``& 0x7FFFFFFF`` даёт неотрицательный int31.
        :param user_id: владелец задач.
        :param list_id: целевой физический список.
        :returns: int31-ключ для advisory lock.
        """
        return zlib.crc32(f"{user_id}:{list_id}".encode()) & 0x7FFFFFFF

    def _to_write_result(self, row: Record) -> TaskWriteResult:
        """
        Собирает TaskWriteResult из строки с write_status.

        :param row: запись SQL с write_status и полями задачи.
        :returns: статус записи и задача при ``ok``.
        """
        status = TaskWriteStatus(row["write_status"])
        if status is not TaskWriteStatus.ok:
            return TaskWriteResult(status=status)
        return TaskWriteResult(status=status, task=self.task_model(**row))

    async def get_task(self, user_id: int, task_id: int) -> Task | None:
        """
        Возвращает задачу пользователя по id.

        :param user_id: владелец задачи.
        :param task_id: идентификатор задачи.
        :returns: задача или None, если не найдена.
        """
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
            cursor: int | None = None,
            cursor_created_at: datetime | None = None,
    ) -> list[Task]:
        """
        Задачи списка с keyset-пагинацией.

        Фильтр: user_id, list_id, deleted_at IS NULL.
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

    async def create_task(
            self,
            user_id: int,
            list_id: int,
            title: str,
            due_date: datetime | None = None,
            *,
            limit: int,
    ) -> TaskWriteResult:
        """
        Создаёт задачу в доступном списке с лимитом.

        Атомарно: lock → list access → count → INSERT при cnt < limit.
        ``write_status``: ``ok`` | ``forbidden`` | ``limit``.
        :param user_id: владелец задачи.
        :param list_id: целевой список (inbox или свой user).
        :param title: заголовок задачи.
        :param due_date: опциональный дедлайн.
        :param limit: максимум активных задач в списке.
        :returns: TaskWriteResult со статусом и задачей при ``ok``.
        """
        lock_key = self._list_lock_key(user_id, list_id)
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
            ),
            ins AS (
                INSERT INTO tasks (user_id, list_id, title, due_date, status)
                SELECT $3, list_ok.id, $5, $6::timestamptz, 'active'
                FROM list_ok, stats, _lock
                WHERE stats.cnt < $7
                RETURNING *
            ),
            meta AS (
                SELECT CASE
                    WHEN EXISTS (SELECT 1 FROM ins) THEN 'ok'
                    WHEN NOT EXISTS (SELECT 1 FROM list_ok) THEN 'forbidden'
                    ELSE 'limit'
                END AS write_status
            )
            SELECT meta.write_status, ins.*
            FROM meta
            LEFT JOIN ins ON TRUE
        """
        row = await self.one(
            query,
            self._TASKS_LOCK_NS,
            lock_key,
            user_id,
            list_id,
            title,
            due_date,
            limit,
        )
        return self._to_write_result(row)

    async def update_task_info(self, user_id: int, task_id: int, info: dict[str, Any]) -> Task | None:
        """
        Частично обновляет поля задачи по dict.

        :param user_id: владелец задачи.
        :param task_id: идентификатор задачи.
        :param info: колонки и значения для SET.
        :returns: обновлённая задача или None, если не найдена.
        """
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
    ) -> TaskWriteResult:
        """
        Перемещает задачу в другой список.

        Атомарно: lock → задача не в trash → list writable →
        ``target_cnt + 1 <= limit`` → UPDATE ``list_id``.
        Same-list: ``ok`` без UPDATE. ``previous_list_id`` не трогаем.
        ``write_status``: ``ok`` | ``not_found`` | ``forbidden`` | ``limit``.
        :param user_id: владелец задачи.
        :param task_id: идентификатор задачи.
        :param list_id: целевой список.
        :param limit: максимум активных задач в целевом списке.
        :returns: TaskWriteResult со статусом и задачей при ``ok``.
        """
        lock_key = self._list_lock_key(user_id, list_id)
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
            target_stats AS (
                SELECT COUNT(*)::int AS cnt
                FROM tasks
                WHERE user_id = $3 AND list_id = $5 AND deleted_at IS NULL
            ),
            upd AS (
                UPDATE tasks t
                SET list_id = list_ok.id,
                    updated_at = now()
                FROM src, list_ok, target_stats, _lock
                WHERE t.user_id = $3
                  AND t.id = src.id
                  AND src.list_id IS DISTINCT FROM $5
                  AND target_stats.cnt + 1 <= $6
                RETURNING t.*
            ),
            same AS (
                SELECT t.*
                FROM tasks t
                JOIN src ON t.id = src.id
                WHERE src.list_id IS NOT DISTINCT FROM $5
            ),
            result AS (
                SELECT * FROM upd
                UNION ALL
                SELECT * FROM same
            ),
            meta AS (
                SELECT CASE
                    WHEN EXISTS (SELECT 1 FROM result) THEN 'ok'
                    WHEN NOT EXISTS (SELECT 1 FROM src) THEN 'not_found'
                    WHEN NOT EXISTS (SELECT 1 FROM list_ok) THEN 'forbidden'
                    ELSE 'limit'
                END AS write_status
            )
            SELECT meta.write_status, result.*
            FROM meta
            LEFT JOIN result ON TRUE
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
        return self._to_write_result(row)

    async def complete_task(self, user_id: int, task_id: int) -> Task | None:
        """
        Помечает задачу как завершённую.

        :param user_id: владелец задачи.
        :param task_id: идентификатор задачи.
        :returns: обновлённая задача или None, если не найдена.
        """
        # Отменено: таблица статусов с numeric ID — YAGNI / out of scope.
        # Пока только active/completed; schema и rules/db/db.mdc + tasks plans
        # оставляют VARCHAR + CHECK. Вернуться, если статусов станет больше
        # или понадобятся FK / i18n.
        query = """
            UPDATE tasks
            SET status = 'completed',
                completed_at = COALESCE(completed_at, now()),
                updated_at = now()
            WHERE user_id = $1 AND id = $2
            RETURNING *
        """
        row = await self.one(query, user_id, task_id)
        if row is not None:
            return self.task_model(**row)

    async def trash_task(self, user_id: int, task_id: int) -> Task | None:
        """
        Soft delete: previous_list_id и deleted_at.

        :param user_id: владелец задачи.
        :param task_id: идентификатор задачи.
        :returns: обновлённая задача или None, если не найдена.
        """
        query = """
            UPDATE tasks
            SET previous_list_id = list_id,
                deleted_at = now(),
                updated_at = now()
            WHERE user_id = $1 AND id = $2
            RETURNING *
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
    ) -> TaskWriteResult:
        """
        Restore из корзины в list_id с доступом и лимитом.

        Атомарно: lock → задача в trash → list writable →
        count + 1 ≤ limit → deleted_at=NULL, list_id=target.
        ``write_status``: ``ok`` | ``not_found`` | ``forbidden`` | ``limit``.
        :param user_id: владелец задачи.
        :param task_id: идентификатор задачи в корзине.
        :param list_id: целевой список для восстановления.
        :param limit: максимум активных задач в целевом списке.
        :returns: TaskWriteResult со статусом и задачей при ``ok``.
        """
        lock_key = self._list_lock_key(user_id, list_id)
        query = """
            WITH _lock AS (
                SELECT pg_advisory_xact_lock($1, $2)
            ),
            src AS (
                SELECT id
                FROM tasks
                WHERE user_id = $3 AND id = $4 AND deleted_at IS NOT NULL
            ),
            list_ok AS (
                SELECT id FROM lists
                WHERE id = $5
                  AND (
                      type = 'inbox'
                      OR (type = 'user' AND user_id = $3)
                  )
            ),
            stats AS (
                SELECT COUNT(*)::int AS cnt
                FROM tasks
                WHERE user_id = $3 AND list_id = $5 AND deleted_at IS NULL
            ),
            upd AS (
                UPDATE tasks t
                SET deleted_at = NULL,
                    list_id = list_ok.id,
                    updated_at = now()
                FROM src, list_ok, stats, _lock
                WHERE t.user_id = $3
                  AND t.id = src.id
                  AND stats.cnt + 1 <= $6
                RETURNING t.*
            ),
            meta AS (
                SELECT CASE
                    WHEN EXISTS (SELECT 1 FROM upd) THEN 'ok'
                    WHEN NOT EXISTS (SELECT 1 FROM src) THEN 'not_found'
                    WHEN NOT EXISTS (SELECT 1 FROM list_ok) THEN 'forbidden'
                    ELSE 'limit'
                END AS write_status
            )
            SELECT meta.write_status, upd.*
            FROM meta
            LEFT JOIN upd ON TRUE
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
        return self._to_write_result(row)

    async def hard_delete_task(self, user_id: int, task_id: int) -> bool:
        """
        Hard delete задачи; только из корзины.

        :param user_id: владелец задачи.
        :param task_id: идентификатор задачи.
        :returns: True если удалена, иначе False.
        """
        query = """
            DELETE FROM tasks
            WHERE user_id = $1
              AND id = $2
              AND deleted_at IS NOT NULL
            RETURNING id
        """
        row = await self.one(query, user_id, task_id)
        return row is not None

    async def count_tasks_in_list(self, user_id: int, list_id: int) -> int:
        """
        Считает неудалённые задачи пользователя в списке.

        :param user_id: владелец задач.
        :param list_id: физический список.
        :returns: число активных (не soft-deleted) задач.
        """
        #TODO проверить тесты
        query = """
            SELECT COUNT(*)::int AS cnt
            FROM tasks
            WHERE user_id = $1 AND list_id = $2 AND deleted_at IS NULL
        """
        row = await self.one(query, user_id, list_id)
        return int(row["cnt"])

    async def fetch_deadline_reminder_candidates(
            self,
            window: timedelta,
            conn: Connection,
    ) -> tuple[bool, list[DeadlineReminderCandidate]]:
        """
        Advisory lock тика + кандидаты в окне ``window``.

        Вызывать внутри открытой транзакции ``conn``. Если lock занят —
        ``(False, [])``; иначе ``(True, candidates)`` (список может быть пуст).

        :param window: окно «скоро дедлайн» (например 24h).
        :param conn: соединение текущей транзакции worker.
        :returns: ``(locked, candidates)``.
        """
        locked = await conn.fetchval(
            "SELECT pg_try_advisory_xact_lock($1, $2)",
            self._DEADLINE_WORKER_LOCK_NS,
            self._DEADLINE_WORKER_LOCK_KEY,
        )
        if not locked:
            return False, []

        rows = await conn.fetch(
            """
            SELECT id, title, due_date, user_id
            FROM tasks
            WHERE due_date > now()
              AND due_date <= now() + $1::interval
              AND status = 'active'
              AND deleted_at IS NULL
            """,
            window,
        )
        candidates = [
            DeadlineReminderCandidate(
                id=row["id"],
                title=row["title"],
                due_date=row["due_date"],
                user_id=row["user_id"],
            )
            for row in rows
        ]
        return True, candidates
