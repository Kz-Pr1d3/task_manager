import pytest

from src.repository.base import BaseRepository
from src.repository.task import TaskRepository


INBOX_LIST_ID = 1


@pytest.fixture
async def parent_and_list(base_repo: BaseRepository, test_user_id: int, task_repo: TaskRepository):
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


async def test__get_subtasks__empty(
    task_repo: TaskRepository, test_user_id: int, parent_and_list
):
    parent, _ = parent_and_list
    children = await task_repo.get_subtasks(user_id=test_user_id, parent_id=parent.id)
    assert children == []


async def test__get_subtasks__ordered_and_excludes_deleted(
    task_repo: TaskRepository,
    test_user_id: int,
    parent_and_list,
    base_repo: BaseRepository,
):
    parent, list_id = parent_and_list
    c1 = await task_repo.create_task(
        user_id=test_user_id,
        list_id=list_id,
        title="first",
        parent_id=parent.id,
        limit=100,
    )
    c2 = await task_repo.create_task(
        user_id=test_user_id,
        list_id=list_id,
        title="second",
        parent_id=parent.id,
        limit=100,
    )
    assert c1 is not None and c2 is not None

    await base_repo.query(
        "UPDATE tasks SET deleted_at = now() WHERE id = $1",
        c2.id,
    )

    children = await task_repo.get_subtasks(user_id=test_user_id, parent_id=parent.id)
    assert len(children) == 1
    assert children[0].id == c1.id
    assert children[0].parent_id == parent.id
    assert children[0].list_id == list_id


async def test__create_task__as_subtask_inherits_list_id(
    task_repo: TaskRepository, test_user_id: int, parent_and_list
):
    parent, list_id = parent_and_list
    child = await task_repo.create_task(
        user_id=test_user_id,
        list_id=list_id,
        title="Подзадача",
        due_date=None,
        parent_id=parent.id,
        limit=100,
    )
    assert child is not None
    assert child.parent_id == parent.id
    assert child.list_id == parent.list_id == list_id
    assert child.due_date is None
    assert child.status == "active"
    assert child.deleted_at is None
