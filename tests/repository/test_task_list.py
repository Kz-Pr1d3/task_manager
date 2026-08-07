from datetime import datetime, timezone

import pytest

from src.repository.base import BaseRepository
from src.repository.task import TaskRepository


INBOX_LIST_ID = 1


@pytest.fixture
async def user_list_id(base_repo: BaseRepository, test_user_id: int) -> int:
    row = await base_repo.one(
        """
        INSERT INTO lists (user_id, type, name, position)
        VALUES ($1, 'user', 'Работа', 1)
        RETURNING id
        """,
        test_user_id,
    )
    list_id = row["id"]
    yield list_id

    await base_repo.query("DELETE FROM tasks WHERE user_id = $1", test_user_id)
    await base_repo.query(
        "DELETE FROM lists WHERE type = 'user' AND user_id = $1",
        test_user_id,
    )
    await base_repo.query(
        """
        SELECT setval(
            pg_get_serial_sequence('lists', 'id'),
            (SELECT COALESCE(MAX(id), 1) FROM lists)
        )
        """
    )
    await base_repo.query(
        """
        SELECT setval(
            pg_get_serial_sequence('tasks', 'id'),
            (SELECT COALESCE(MAX(id), 1) FROM tasks)
        )
        """
    )


async def test__list_tasks__empty(
    task_repo: TaskRepository, test_user_id: int, user_list_id: int
):
    items = await task_repo.list_tasks(
        user_id=test_user_id,
        list_id=user_list_id,
        limit=20,
    )
    assert items == []


async def test__list_tasks__first_page(
    task_repo: TaskRepository,
    test_user_id: int,
    user_list_id: int,
    base_repo: BaseRepository,
):
    await base_repo.query(
        """
        INSERT INTO tasks (user_id, list_id, title, status, created_at)
        VALUES
            ($1, $2, 'a', 'active', '2026-01-01 10:00:00+00'),
            ($1, $2, 'b', 'active', '2026-01-01 11:00:00+00'),
            ($1, $2, 'c', 'active', '2026-01-01 12:00:00+00')
        """,
        test_user_id,
        user_list_id,
    )

    items = await task_repo.list_tasks(
        user_id=test_user_id,
        list_id=user_list_id,
        limit=2,
    )
    assert len(items) == 2
    assert [t.title for t in items] == ["a", "b"]
    assert items[0].created_at < items[1].created_at
    assert items[0].id < items[1].id


async def test__list_tasks__pagination_next_page(
    task_repo: TaskRepository,
    test_user_id: int,
    user_list_id: int,
    base_repo: BaseRepository,
):
    await base_repo.query(
        """
        INSERT INTO tasks (user_id, list_id, title, status, created_at)
        VALUES
            ($1, $2, 'a', 'active', '2026-01-01 10:00:00+00'),
            ($1, $2, 'b', 'active', '2026-01-01 11:00:00+00'),
            ($1, $2, 'c', 'active', '2026-01-01 12:00:00+00')
        """,
        test_user_id,
        user_list_id,
    )

    first = await task_repo.list_tasks(
        user_id=test_user_id,
        list_id=user_list_id,
        limit=2,
    )
    assert len(first) == 2

    second = await task_repo.list_tasks(
        user_id=test_user_id,
        list_id=user_list_id,
        limit=2,
        cursor=first[-1].id,
        cursor_created_at=first[-1].created_at,
    )
    assert len(second) == 1
    assert second[0].title == "c"
    assert second[0].id > first[-1].id


async def test__list_tasks__exclude_subtasks(
    task_repo: TaskRepository,
    test_user_id: int,
    user_list_id: int,
    base_repo: BaseRepository,
):
    root = await base_repo.one(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        VALUES ($1, $2, 'root', 'active')
        RETURNING id
        """,
        test_user_id,
        user_list_id,
    )
    await base_repo.query(
        """
        INSERT INTO tasks (user_id, list_id, parent_id, title, status)
        VALUES ($1, $2, $3, 'sub', 'active')
        """,
        test_user_id,
        user_list_id,
        root["id"],
    )

    items = await task_repo.list_tasks(
        user_id=test_user_id,
        list_id=user_list_id,
        limit=20,
    )
    assert len(items) == 1
    assert items[0].title == "root"
    assert items[0].parent_id is None


async def test__list_tasks__exclude_deleted(
    task_repo: TaskRepository,
    test_user_id: int,
    user_list_id: int,
    base_repo: BaseRepository,
):
    await base_repo.query(
        """
        INSERT INTO tasks (user_id, list_id, title, status, deleted_at)
        VALUES
            ($1, $2, 'alive', 'active', NULL),
            ($1, $2, 'trashed', 'active', $3)
        """,
        test_user_id,
        user_list_id,
        datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    items = await task_repo.list_tasks(
        user_id=test_user_id,
        list_id=user_list_id,
        limit=20,
    )
    assert len(items) == 1
    assert items[0].title == "alive"
    assert items[0].deleted_at is None
