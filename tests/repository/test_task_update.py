import pytest

from src.repository.base import BaseRepository
from src.repository.task import TaskRepository


INBOX_LIST_ID = 1


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


async def test__update_task_info__success(
    task_repo: TaskRepository,
    test_user_id: int,
    cleanup_inbox_tasks,
):
    created = await task_repo.create_task(
        user_id=test_user_id,
        list_id=INBOX_LIST_ID,
        title="before",
        limit=100,
    )
    assert created is not None

    updated = await task_repo.update_task_info(
        user_id=test_user_id,
        task_id=created.id,
        info={"title": "after", "description": "desc"},
    )
    assert updated is not None
    assert updated.id == created.id
    assert updated.title == "after"
    assert updated.description == "desc"
    assert updated.list_id == INBOX_LIST_ID


async def test__update_task_info__not_found(
    task_repo: TaskRepository,
    test_user_id: int,
):
    updated = await task_repo.update_task_info(
        user_id=test_user_id,
        task_id=999_999,
        info={"title": "ghost"},
    )
    assert updated is None
