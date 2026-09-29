import pytest

from src.core.exceptions import NotFoundException, UnprocessableEntityException
from src.models.enums import TaskWriteStatus
from src.repository.base import BaseRepository
from src.repository.task import TaskRepository
from src.services.task import TaskService, INBOX_LIST_ID


@pytest.fixture
async def user_list_id(base_repo: BaseRepository, test_user_id: int) -> int:
    row = await base_repo.one(
        """
        INSERT INTO lists (user_id, type, name, position)
        VALUES ($1, 'user', 'LifecycleList', 1)
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
async def sample_task(
    base_repo: BaseRepository,
    test_user_id: int,
    user_list_id: int,
) -> dict[str, int]:
    row = await base_repo.one(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        VALUES ($1, $2, 'task', 'active')
        RETURNING id
        """,
        test_user_id,
        user_list_id,
    )
    return {"task_id": row["id"], "list_id": user_list_id}


@pytest.fixture
async def task_service(task_repo: TaskRepository) -> TaskService:
    return TaskService(repository=task_repo)


async def test__complete_task__success(
    task_repo: TaskRepository,
    test_user_id: int,
    sample_task: dict[str, int],
):
    task = await task_repo.complete_task(
        user_id=test_user_id,
        task_id=sample_task["task_id"],
    )
    assert task is not None
    assert task.id == sample_task["task_id"]
    assert task.status == "completed"
    assert task.completed_at is not None
    assert task.list_id == sample_task["list_id"]


async def test__complete_task__not_found(task_repo: TaskRepository, test_user_id: int):
    assert await task_repo.complete_task(user_id=test_user_id, task_id=999_999) is None


async def test__trash_task__sets_previous_list(
    task_repo: TaskRepository,
    test_user_id: int,
    sample_task: dict[str, int],
):
    task = await task_repo.trash_task(
        user_id=test_user_id,
        task_id=sample_task["task_id"],
    )
    assert task is not None
    assert task.deleted_at is not None
    assert task.previous_list_id == sample_task["list_id"]
    assert task.list_id == sample_task["list_id"]


async def test__trash_task__works_for_completed(
    task_repo: TaskRepository,
    test_user_id: int,
    sample_task: dict[str, int],
):
    await task_repo.complete_task(user_id=test_user_id, task_id=sample_task["task_id"])
    task = await task_repo.trash_task(user_id=test_user_id, task_id=sample_task["task_id"])
    assert task is not None
    assert task.status == "completed"
    assert task.deleted_at is not None


async def test__restore_task__to_previous_list(
    task_repo: TaskRepository,
    test_user_id: int,
    sample_task: dict[str, int],
):
    await task_repo.trash_task(user_id=test_user_id, task_id=sample_task["task_id"])
    result = await task_repo.restore_task(
        user_id=test_user_id,
        task_id=sample_task["task_id"],
        list_id=sample_task["list_id"],
        limit=100,
    )
    assert result.status is TaskWriteStatus.ok
    restored = result.task
    assert restored is not None
    assert restored.deleted_at is None
    assert restored.list_id == sample_task["list_id"]


async def test__restore_task__list_forbidden(
    task_repo: TaskRepository,
    test_user_id: int,
    sample_task: dict[str, int],
):
    await task_repo.trash_task(user_id=test_user_id, task_id=sample_task["task_id"])
    result = await task_repo.restore_task(
        user_id=test_user_id,
        task_id=sample_task["task_id"],
        list_id=999_999,
        limit=100,
    )
    assert result.status is TaskWriteStatus.forbidden
    assert result.task is None


async def test__restore_task__fallback_inbox_when_list_gone(
    task_service: TaskService,
    task_repo: TaskRepository,
    base_repo: BaseRepository,
    test_user_id: int,
    sample_task: dict[str, int],
):
    await task_repo.trash_task(user_id=test_user_id, task_id=sample_task["task_id"])
    await base_repo.query(
        "UPDATE tasks SET previous_list_id = 999_999 WHERE user_id = $1 AND id = $2",
        test_user_id,
        sample_task["task_id"],
    )

    restored = await task_service.restore_task(
        user_id=test_user_id,
        task_id=sample_task["task_id"],
    )
    assert restored.deleted_at is None
    assert restored.list_id == INBOX_LIST_ID


async def test__restore_task__not_in_trash(
    task_service: TaskService,
    test_user_id: int,
    sample_task: dict[str, int],
):
    with pytest.raises(NotFoundException):
        await task_service.restore_task(
            user_id=test_user_id,
            task_id=sample_task["task_id"],
        )


async def test__restore_task__limit_reached(
    task_repo: TaskRepository,
    base_repo: BaseRepository,
    test_user_id: int,
    sample_task: dict[str, int],
):
    await task_repo.trash_task(user_id=test_user_id, task_id=sample_task["task_id"])
    await base_repo.query(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        VALUES ($1, $2, 'filler', 'active')
        """,
        test_user_id,
        sample_task["list_id"],
    )
    result = await task_repo.restore_task(
        user_id=test_user_id,
        task_id=sample_task["task_id"],
        list_id=sample_task["list_id"],
        limit=1,
    )
    assert result.status is TaskWriteStatus.limit
    assert result.task is None


async def test__hard_delete_task__from_trash(
    task_repo: TaskRepository,
    base_repo: BaseRepository,
    test_user_id: int,
    sample_task: dict[str, int],
):
    await task_repo.trash_task(user_id=test_user_id, task_id=sample_task["task_id"])
    deleted = await task_repo.hard_delete_task(
        user_id=test_user_id,
        task_id=sample_task["task_id"],
    )
    assert deleted is True

    rows = await base_repo.query(
        "SELECT id FROM tasks WHERE user_id = $1",
        test_user_id,
    )
    assert rows == []


async def test__hard_delete_task__not_from_trash_returns_false(
    task_repo: TaskRepository,
    test_user_id: int,
    sample_task: dict[str, int],
):
    deleted = await task_repo.hard_delete_task(
        user_id=test_user_id,
        task_id=sample_task["task_id"],
    )
    assert deleted is False
    still = await task_repo.get_task(user_id=test_user_id, task_id=sample_task["task_id"])
    assert still is not None


async def test__hard_delete_task__not_from_trash_raises_422(
    task_service: TaskService,
    test_user_id: int,
    sample_task: dict[str, int],
):
    with pytest.raises(UnprocessableEntityException) as exc_info:
        await task_service.hard_delete_task(
            user_id=test_user_id,
            task_id=sample_task["task_id"],
        )
    assert exc_info.value.status_code == 422


async def test__hard_delete_task__not_found(
    task_service: TaskService,
    test_user_id: int,
):
    with pytest.raises(NotFoundException):
        await task_service.hard_delete_task(user_id=test_user_id, task_id=999_999)


async def test__count_tasks_in_list__excludes_trashed(
    task_repo: TaskRepository,
    test_user_id: int,
    sample_task: dict[str, int],
):
    assert await task_repo.count_tasks_in_list(
        user_id=test_user_id,
        list_id=sample_task["list_id"],
    ) == 1

    await task_repo.trash_task(user_id=test_user_id, task_id=sample_task["task_id"])
    assert await task_repo.count_tasks_in_list(
        user_id=test_user_id,
        list_id=sample_task["list_id"],
    ) == 0
