import pytest

from src.core.database import db
from src.core.exceptions import ConflictException, NotFoundException
from src.repository.base import BaseRepository
from src.repository.task import TaskRepository
from src.services.task import TaskService


INBOX_LIST_ID = 1


@pytest.fixture
async def create_pool():
    await db.connect()
    yield db
    await db.disconnect()


@pytest.fixture
async def base_repo(create_pool) -> BaseRepository:
    return BaseRepository(pool=create_pool.pool)


@pytest.fixture
async def task_service(create_pool) -> TaskService:
    return TaskService(repository=TaskRepository(pool=create_pool.pool))


@pytest.fixture
async def two_user_lists(base_repo: BaseRepository, test_user_id: int) -> tuple[int, int]:
    rows = await base_repo.query(
        """
        INSERT INTO lists (user_id, type, name, position)
        VALUES
            ($1, 'user', 'SrcSvc', 1),
            ($1, 'user', 'DstSvc', 2)
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


async def test__move_task__success(
    task_service: TaskService,
    test_user_id: int,
    two_user_lists: tuple[int, int],
    base_repo: BaseRepository,
):
    source_id, target_id = two_user_lists
    root = await base_repo.one(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        VALUES ($1, $2, 'move-me', 'active')
        RETURNING id
        """,
        test_user_id,
        source_id,
    )
    moved = await task_service.move_task(
        user_id=test_user_id,
        task_id=root["id"],
        list_id=target_id,
    )
    assert moved.list_id == target_id
    assert moved.id == root["id"]


async def test__move_task__same_list_noop(
    task_service: TaskService,
    test_user_id: int,
    two_user_lists: tuple[int, int],
    base_repo: BaseRepository,
):
    source_id, _ = two_user_lists
    root = await base_repo.one(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        VALUES ($1, $2, 'same', 'active')
        RETURNING id, list_id, updated_at
        """,
        test_user_id,
        source_id,
    )
    moved = await task_service.move_task(
        user_id=test_user_id,
        task_id=root["id"],
        list_id=source_id,
    )
    assert moved.id == root["id"]
    assert moved.list_id == source_id
    assert moved.updated_at == root["updated_at"]


async def test__move_task__foreign_list_not_found(
    task_service: TaskService,
    test_user_id: int,
    two_user_lists: tuple[int, int],
    base_repo: BaseRepository,
):
    source_id, _ = two_user_lists
    root = await base_repo.one(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        VALUES ($1, $2, 'no-dst', 'active')
        RETURNING id
        """,
        test_user_id,
        source_id,
    )
    with pytest.raises(NotFoundException):
        await task_service.move_task(
            user_id=test_user_id,
            task_id=root["id"],
            list_id=999_999,
        )


async def test__move_task__missing_task_not_found(
    task_service: TaskService,
    test_user_id: int,
    two_user_lists: tuple[int, int],
):
    _, target_id = two_user_lists
    with pytest.raises(NotFoundException):
        await task_service.move_task(
            user_id=test_user_id,
            task_id=999_999,
            list_id=target_id,
        )


async def test__move_task__limit_conflict(
    task_service: TaskService,
    test_user_id: int,
    two_user_lists: tuple[int, int],
    base_repo: BaseRepository,
):
    source_id, target_id = two_user_lists
    await base_repo.query(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        SELECT $1, $2, 'fill' || g, 'active'
        FROM generate_series(1, 100) AS g
        """,
        test_user_id,
        target_id,
    )
    root = await base_repo.one(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        VALUES ($1, $2, 'overflow', 'active')
        RETURNING id
        """,
        test_user_id,
        source_id,
    )
    with pytest.raises(ConflictException) as exc_info:
        await task_service.move_task(
            user_id=test_user_id,
            task_id=root["id"],
            list_id=target_id,
        )
    assert "limit" in exc_info.value.detail.lower()
