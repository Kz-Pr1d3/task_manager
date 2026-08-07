import pytest

from src.core.exceptions import NotFoundException, UnprocessableEntityException
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
async def task_tree(
    base_repo: BaseRepository,
    test_user_id: int,
    user_list_id: int,
) -> dict[str, int]:
    root = await base_repo.one(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        VALUES ($1, $2, 'root', 'active')
        RETURNING id
        """,
        test_user_id,
        user_list_id,
    )
    child_a = await base_repo.one(
        """
        INSERT INTO tasks (user_id, list_id, parent_id, title, status)
        VALUES ($1, $2, $3, 'child-a', 'active')
        RETURNING id
        """,
        test_user_id,
        user_list_id,
        root["id"],
    )
    child_b = await base_repo.one(
        """
        INSERT INTO tasks (user_id, list_id, parent_id, title, status)
        VALUES ($1, $2, $3, 'child-b', 'active')
        RETURNING id
        """,
        test_user_id,
        user_list_id,
        root["id"],
    )
    return {
        "root_id": root["id"],
        "child_a_id": child_a["id"],
        "child_b_id": child_b["id"],
        "list_id": user_list_id,
    }


@pytest.fixture
async def task_service(task_repo: TaskRepository) -> TaskService:
    return TaskService(repository=task_repo)


async def test__complete_task__cascades_to_descendants(
    task_repo: TaskRepository,
    base_repo: BaseRepository,
    test_user_id: int,
    task_tree: dict[str, int],
):
    task = await task_repo.complete_task(
        user_id=test_user_id,
        task_id=task_tree["root_id"],
    )
    assert task is not None
    assert task.id == task_tree["root_id"]
    assert task.status == "completed"
    assert task.completed_at is not None
    assert task.list_id == task_tree["list_id"]

    rows = await base_repo.query(
        "SELECT id, status, completed_at, list_id FROM tasks WHERE user_id = $1 ORDER BY id",
        test_user_id,
    )
    assert len(rows) == 3
    assert all(row["status"] == "completed" for row in rows)
    assert all(row["completed_at"] is not None for row in rows)
    assert all(row["list_id"] == task_tree["list_id"] for row in rows)


async def test__complete_task__auto_completes_parent(
    task_repo: TaskRepository,
    base_repo: BaseRepository,
    test_user_id: int,
    task_tree: dict[str, int],
):
    await task_repo.complete_task(user_id=test_user_id, task_id=task_tree["child_a_id"])
    root = await base_repo.one(
        "SELECT status FROM tasks WHERE id = $1",
        task_tree["root_id"],
    )
    assert root["status"] == "active"

    await task_repo.complete_task(user_id=test_user_id, task_id=task_tree["child_b_id"])
    root = await base_repo.one(
        "SELECT status, completed_at FROM tasks WHERE id = $1",
        task_tree["root_id"],
    )
    assert root["status"] == "completed"
    assert root["completed_at"] is not None


async def test__complete_task__not_found(task_repo: TaskRepository, test_user_id: int):
    assert await task_repo.complete_task(user_id=test_user_id, task_id=999_999) is None


async def test__trash_task__cascades_and_sets_previous_list(
    task_repo: TaskRepository,
    base_repo: BaseRepository,
    test_user_id: int,
    task_tree: dict[str, int],
):
    task = await task_repo.trash_task(
        user_id=test_user_id,
        task_id=task_tree["root_id"],
    )
    assert task is not None
    assert task.deleted_at is not None
    assert task.previous_list_id == task_tree["list_id"]
    assert task.list_id == task_tree["list_id"]

    rows = await base_repo.query(
        """
        SELECT previous_list_id, deleted_at
        FROM tasks
        WHERE user_id = $1
        """,
        test_user_id,
    )
    assert len(rows) == 3
    assert all(row["deleted_at"] is not None for row in rows)
    assert all(row["previous_list_id"] == task_tree["list_id"] for row in rows)


async def test__trash_task__works_for_completed(
    task_repo: TaskRepository,
    test_user_id: int,
    task_tree: dict[str, int],
):
    await task_repo.complete_task(user_id=test_user_id, task_id=task_tree["root_id"])
    task = await task_repo.trash_task(user_id=test_user_id, task_id=task_tree["root_id"])
    assert task is not None
    assert task.status == "completed"
    assert task.deleted_at is not None


async def test__restore_task__to_previous_list(
    task_repo: TaskRepository,
    test_user_id: int,
    task_tree: dict[str, int],
):
    await task_repo.trash_task(user_id=test_user_id, task_id=task_tree["root_id"])
    restored = await task_repo.restore_task(
        user_id=test_user_id,
        task_id=task_tree["root_id"],
        list_id=task_tree["list_id"],
        limit=100,
    )
    assert restored is not None
    assert restored.deleted_at is None
    assert restored.list_id == task_tree["list_id"]

    child = await task_repo.get_task(user_id=test_user_id, task_id=task_tree["child_a_id"])
    assert child is not None
    assert child.deleted_at is None
    assert child.list_id == task_tree["list_id"]


async def test__restore_task__fallback_inbox_when_list_gone(
    task_service: TaskService,
    task_repo: TaskRepository,
    base_repo: BaseRepository,
    test_user_id: int,
    task_tree: dict[str, int],
):
    await task_repo.trash_task(user_id=test_user_id, task_id=task_tree["root_id"])
    # previous_list_id без FK — имитируем hard-deleted user list
    await base_repo.query(
        "UPDATE tasks SET previous_list_id = 999_999 WHERE user_id = $1 AND id = $2",
        test_user_id,
        task_tree["root_id"],
    )

    restored = await task_service.restore_task(
        user_id=test_user_id,
        task_id=task_tree["root_id"],
    )
    assert restored.deleted_at is None
    assert restored.list_id == INBOX_LIST_ID

    child = await task_repo.get_task(user_id=test_user_id, task_id=task_tree["child_a_id"])
    assert child is not None
    assert child.list_id == INBOX_LIST_ID
    assert child.deleted_at is None


async def test__restore_task__not_in_trash(
    task_service: TaskService,
    test_user_id: int,
    task_tree: dict[str, int],
):
    with pytest.raises(NotFoundException):
        await task_service.restore_task(
            user_id=test_user_id,
            task_id=task_tree["root_id"],
        )


async def test__restore_task__limit_reached(
    task_repo: TaskRepository,
    base_repo: BaseRepository,
    test_user_id: int,
    task_tree: dict[str, int],
):
    await task_repo.trash_task(user_id=test_user_id, task_id=task_tree["root_id"])
    await base_repo.query(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        VALUES ($1, $2, 'filler', 'active')
        """,
        test_user_id,
        task_tree["list_id"],
    )
    # subtree=3, existing active=1 → need limit < 4
    restored = await task_repo.restore_task(
        user_id=test_user_id,
        task_id=task_tree["root_id"],
        list_id=task_tree["list_id"],
        limit=3,
    )
    assert restored is None


async def test__hard_delete_task__from_trash_cascades(
    task_repo: TaskRepository,
    base_repo: BaseRepository,
    test_user_id: int,
    task_tree: dict[str, int],
):
    await task_repo.trash_task(user_id=test_user_id, task_id=task_tree["root_id"])
    deleted = await task_repo.hard_delete_task(
        user_id=test_user_id,
        task_id=task_tree["root_id"],
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
    task_tree: dict[str, int],
):
    deleted = await task_repo.hard_delete_task(
        user_id=test_user_id,
        task_id=task_tree["root_id"],
    )
    assert deleted is False
    still = await task_repo.get_task(user_id=test_user_id, task_id=task_tree["root_id"])
    assert still is not None


async def test__hard_delete_task__not_from_trash_raises_422(
    task_service: TaskService,
    test_user_id: int,
    task_tree: dict[str, int],
):
    with pytest.raises(UnprocessableEntityException) as exc_info:
        await task_service.hard_delete_task(
            user_id=test_user_id,
            task_id=task_tree["root_id"],
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
    task_tree: dict[str, int],
):
    assert await task_repo.count_tasks_in_list(
        user_id=test_user_id,
        list_id=task_tree["list_id"],
    ) == 3

    await task_repo.trash_task(user_id=test_user_id, task_id=task_tree["root_id"])
    assert await task_repo.count_tasks_in_list(
        user_id=test_user_id,
        list_id=task_tree["list_id"],
    ) == 0
