import pytest

from src.models.enums import TaskWriteStatus
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


@pytest.fixture
async def cleanup_inbox_tasks(base_repo: BaseRepository, test_user_id: int):
    yield
    await base_repo.query(
        "DELETE FROM tasks WHERE user_id = $1 AND list_id = $2",
        test_user_id,
        INBOX_LIST_ID,
    )
    await base_repo.query(
        """
        SELECT setval(
            pg_get_serial_sequence('tasks', 'id'),
            (SELECT COALESCE(MAX(id), 1) FROM tasks)
        )
        """
    )


async def test__create_task__inbox_success(
    task_repo: TaskRepository, test_user_id: int, cleanup_inbox_tasks
):
    result = await task_repo.create_task(
        user_id=test_user_id,
        list_id=INBOX_LIST_ID,
        title="Купить молоко",
        limit=100,
    )
    assert result.status is TaskWriteStatus.ok
    task = result.task
    assert task is not None
    assert task.user_id == test_user_id
    assert task.list_id == INBOX_LIST_ID
    assert task.title == "Купить молоко"
    assert task.status == "active"
    assert task.due_date is None
    assert task.deleted_at is None


async def test__create_task__user_list_with_due_date(
    task_repo: TaskRepository, test_user_id: int, user_list_id: int
):
    from datetime import datetime, timezone

    due = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    result = await task_repo.create_task(
        user_id=test_user_id,
        list_id=user_list_id,
        title="Отчёт",
        due_date=due,
        limit=100,
    )
    assert result.status is TaskWriteStatus.ok
    assert result.task is not None
    assert result.task.list_id == user_list_id
    assert result.task.due_date == due


async def test__create_task__list_not_accessible(
    task_repo: TaskRepository, test_user_id: int
):
    result = await task_repo.create_task(
        user_id=test_user_id,
        list_id=999_999,
        title="ghost",
        limit=100,
    )
    assert result.status is TaskWriteStatus.forbidden
    assert result.task is None


async def test__create_task__limit_reached(
    task_repo: TaskRepository,
    test_user_id: int,
    user_list_id: int,
    base_repo: BaseRepository,
):
    await base_repo.query(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        SELECT $1, $2, 't' || g, 'active'
        FROM generate_series(1, 2) AS g
        """,
        test_user_id,
        user_list_id,
    )
    result = await task_repo.create_task(
        user_id=test_user_id,
        list_id=user_list_id,
        title="overflow",
        limit=2,
    )
    assert result.status is TaskWriteStatus.limit
    assert result.task is None
