import pytest

from src.models.enums import TaskWriteStatus
from src.repository.base import BaseRepository
from src.repository.task import TaskRepository


INBOX_LIST_ID = 1


@pytest.fixture
async def two_user_lists(base_repo: BaseRepository, test_user_id: int) -> tuple[int, int]:
    rows = await base_repo.query(
        """
        INSERT INTO lists (user_id, type, name, position)
        VALUES
            ($1, 'user', 'Источник', 1),
            ($1, 'user', 'Цель', 2)
        RETURNING id
        """,
        test_user_id,
    )
    source_id, target_id = rows[0]["id"], rows[1]["id"]
    yield source_id, target_id

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


async def test__count_tasks_in_list__empty(
    task_repo: TaskRepository, test_user_id: int, two_user_lists: tuple[int, int]
):
    source_id, _ = two_user_lists
    assert await task_repo.count_tasks_in_list(user_id=test_user_id, list_id=source_id) == 0


async def test__count_tasks_in_list__excludes_deleted(
    task_repo: TaskRepository,
    test_user_id: int,
    two_user_lists: tuple[int, int],
    base_repo: BaseRepository,
):
    source_id, _ = two_user_lists
    await base_repo.query(
        """
        INSERT INTO tasks (user_id, list_id, title, status, deleted_at)
        VALUES
            ($1, $2, 'alive', 'active', NULL),
            ($1, $2, 'trashed', 'active', now())
        """,
        test_user_id,
        source_id,
    )
    assert await task_repo.count_tasks_in_list(user_id=test_user_id, list_id=source_id) == 1


async def test__move_task__success(
    task_repo: TaskRepository,
    test_user_id: int,
    two_user_lists: tuple[int, int],
    base_repo: BaseRepository,
):
    source_id, target_id = two_user_lists
    root = await base_repo.one(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        VALUES ($1, $2, 'корень', 'active')
        RETURNING id
        """,
        test_user_id,
        source_id,
    )
    result = await task_repo.move_task(
        user_id=test_user_id,
        task_id=root["id"],
        list_id=target_id,
        limit=100,
    )
    assert result.status is TaskWriteStatus.ok
    moved = result.task
    assert moved is not None
    assert moved.id == root["id"]
    assert moved.list_id == target_id
    assert moved.previous_list_id is None
    assert await task_repo.count_tasks_in_list(user_id=test_user_id, list_id=source_id) == 0
    assert await task_repo.count_tasks_in_list(user_id=test_user_id, list_id=target_id) == 1


async def test__move_task__list_not_accessible(
    task_repo: TaskRepository,
    test_user_id: int,
    two_user_lists: tuple[int, int],
    base_repo: BaseRepository,
):
    source_id, _ = two_user_lists
    root = await base_repo.one(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        VALUES ($1, $2, 'orphan-move', 'active')
        RETURNING id
        """,
        test_user_id,
        source_id,
    )
    result = await task_repo.move_task(
        user_id=test_user_id,
        task_id=root["id"],
        list_id=999_999,
        limit=100,
    )
    assert result.status is TaskWriteStatus.forbidden
    assert result.task is None
    still = await task_repo.get_task(user_id=test_user_id, task_id=root["id"])
    assert still is not None
    assert still.list_id == source_id


async def test__move_task__missing_task(
    task_repo: TaskRepository, test_user_id: int, two_user_lists: tuple[int, int]
):
    _, target_id = two_user_lists
    result = await task_repo.move_task(
        user_id=test_user_id,
        task_id=999_999,
        list_id=target_id,
        limit=100,
    )
    assert result.status is TaskWriteStatus.not_found
    assert result.task is None


async def test__move_task__trashed_task(
    task_repo: TaskRepository,
    test_user_id: int,
    two_user_lists: tuple[int, int],
    base_repo: BaseRepository,
):
    source_id, target_id = two_user_lists
    root = await base_repo.one(
        """
        INSERT INTO tasks (user_id, list_id, title, status, deleted_at)
        VALUES ($1, $2, 'in-trash', 'active', now())
        RETURNING id
        """,
        test_user_id,
        source_id,
    )
    result = await task_repo.move_task(
        user_id=test_user_id,
        task_id=root["id"],
        list_id=target_id,
        limit=100,
    )
    assert result.status is TaskWriteStatus.not_found
    assert result.task is None


async def test__move_task__limit_reached(
    task_repo: TaskRepository,
    test_user_id: int,
    two_user_lists: tuple[int, int],
    base_repo: BaseRepository,
):
    source_id, target_id = two_user_lists
    await base_repo.query(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        SELECT $1, $2, 't' || g, 'active'
        FROM generate_series(1, 2) AS g
        """,
        test_user_id,
        target_id,
    )
    root = await base_repo.one(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        VALUES ($1, $2, 'mover', 'active')
        RETURNING id
        """,
        test_user_id,
        source_id,
    )
    # target=2, moving 1 → 3 > limit=2
    result = await task_repo.move_task(
        user_id=test_user_id,
        task_id=root["id"],
        list_id=target_id,
        limit=2,
    )
    assert result.status is TaskWriteStatus.limit
    assert result.task is None
    assert await task_repo.count_tasks_in_list(user_id=test_user_id, list_id=source_id) == 1
    assert await task_repo.count_tasks_in_list(user_id=test_user_id, list_id=target_id) == 2


async def test__move_task__same_list_noop_at_repo(
    task_repo: TaskRepository,
    test_user_id: int,
    two_user_lists: tuple[int, int],
    base_repo: BaseRepository,
):
    source_id, _ = two_user_lists
    root = await base_repo.one(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        VALUES ($1, $2, 'stay', 'active')
        RETURNING id, list_id, updated_at
        """,
        test_user_id,
        source_id,
    )
    result = await task_repo.move_task(
        user_id=test_user_id,
        task_id=root["id"],
        list_id=source_id,
        limit=100,
    )
    assert result.status is TaskWriteStatus.ok
    assert result.task is not None
    assert result.task.id == root["id"]
    assert result.task.list_id == source_id
    assert result.task.updated_at == root["updated_at"]
