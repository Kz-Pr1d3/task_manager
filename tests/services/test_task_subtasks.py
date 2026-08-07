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
async def task_repo(create_pool) -> TaskRepository:
    return TaskRepository(pool=create_pool.pool)


@pytest.fixture
async def task_service(task_repo: TaskRepository) -> TaskService:
    return TaskService(repository=task_repo)


@pytest.fixture
async def parent_setup(base_repo: BaseRepository, test_user_id: int, task_repo: TaskRepository):
    row = await base_repo.one(
        """
        INSERT INTO lists (user_id, type, name, position)
        VALUES ($1, 'user', 'Работа', 1)
        RETURNING id
        """,
        test_user_id,
    )
    list_id = row["id"]
    parent = await task_repo.create_task(
        user_id=test_user_id,
        list_id=list_id,
        title="Родитель",
        limit=100,
    )
    assert parent is not None
    yield parent, list_id

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


async def test__create_subtask__inherits_list_id(
    task_service: TaskService, test_user_id: int, parent_setup
):
    parent, list_id = parent_setup
    child = await task_service.create_subtask(
        user_id=test_user_id,
        parent_id=parent.id,
        title="Дочка",
    )
    assert child.parent_id == parent.id
    assert child.list_id == list_id
    assert child.due_date is None
    assert child.status == "active"


async def test__get_subtasks__lists_children(
    task_service: TaskService, test_user_id: int, parent_setup
):
    parent, _ = parent_setup
    await task_service.create_subtask(
        user_id=test_user_id, parent_id=parent.id, title="a"
    )
    await task_service.create_subtask(
        user_id=test_user_id, parent_id=parent.id, title="b"
    )
    children = await task_service.get_subtasks(user_id=test_user_id, task_id=parent.id)
    assert len(children) == 2
    assert [c.title for c in children] == ["a", "b"]


async def test__get_subtasks__parent_missing(
    task_service: TaskService, test_user_id: int
):
    with pytest.raises(NotFoundException):
        await task_service.get_subtasks(user_id=test_user_id, task_id=999_999)


async def test__create_subtask__parent_missing(
    task_service: TaskService, test_user_id: int
):
    with pytest.raises(NotFoundException):
        await task_service.create_subtask(
            user_id=test_user_id, parent_id=999_999, title="x"
        )


async def test__create_subtask__deleted_parent(
    task_service: TaskService,
    test_user_id: int,
    parent_setup,
    base_repo: BaseRepository,
):
    parent, _ = parent_setup
    await base_repo.query(
        "UPDATE tasks SET deleted_at = now() WHERE id = $1",
        parent.id,
    )
    with pytest.raises(NotFoundException):
        await task_service.create_subtask(
            user_id=test_user_id, parent_id=parent.id, title="x"
        )


async def test__create_subtask__limit_reached(
    task_service: TaskService,
    test_user_id: int,
    parent_setup,
):
    parent, _ = parent_setup
    # родитель уже в списке → при лимите 1 подзадачу создать нельзя
    task_service.tasks_per_list = 1
    with pytest.raises(ConflictException) as exc_info:
        await task_service.create_subtask(
            user_id=test_user_id, parent_id=parent.id, title="overflow"
        )
    assert "limit" in exc_info.value.detail.lower()
