import pytest

from src.core.database import db
from src.core.exceptions import BadRequestException
from src.repository.base import BaseRepository
from src.repository.task import TaskRepository
from src.services.task import TaskService


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
async def user_list_id(base_repo: BaseRepository, test_user_id: int) -> int:
    row = await base_repo.one(
        """
        INSERT INTO lists (user_id, type, name, position)
        VALUES ($1, 'user', 'ListPage', 1)
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


async def test__list_tasks__exact_limit_last_page_has_more_false(
    task_service: TaskService,
    test_user_id: int,
    user_list_id: int,
    base_repo: BaseRepository,
):
    """Ровно limit задач → has_more=false (баг был: len==limit ⇒ true)."""
    await base_repo.query(
        """
        INSERT INTO tasks (user_id, list_id, title, status, created_at)
        SELECT $1, $2, 't' || g, 'active',
               timestamptz '2026-01-01 10:00:00+00' + (g || ' minutes')::interval
        FROM generate_series(1, 2) AS g
        """,
        test_user_id,
        user_list_id,
    )

    page = await task_service.list_tasks(
        user_id=test_user_id,
        list_id=user_list_id,
        limit=2,
    )
    assert len(page.items) == 2
    assert page.has_more is False
    assert page.next_cursor is None
    assert page.limit == 2


async def test__list_tasks__more_than_limit_has_more_true(
    task_service: TaskService,
    test_user_id: int,
    user_list_id: int,
    base_repo: BaseRepository,
):
    await base_repo.query(
        """
        INSERT INTO tasks (user_id, list_id, title, status, created_at)
        SELECT $1, $2, 't' || g, 'active',
               timestamptz '2026-01-01 10:00:00+00' + (g || ' minutes')::interval
        FROM generate_series(1, 3) AS g
        """,
        test_user_id,
        user_list_id,
    )

    page = await task_service.list_tasks(
        user_id=test_user_id,
        list_id=user_list_id,
        limit=2,
    )
    assert len(page.items) == 2
    assert [t.title for t in page.items] == ["t1", "t2"]
    assert page.has_more is True
    assert page.next_cursor == page.items[-1].id


async def test__list_tasks__cursor_without_companion_bad_request(
    task_service: TaskService,
    test_user_id: int,
    user_list_id: int,
):
    with pytest.raises(BadRequestException):
        await task_service.list_tasks(
            user_id=test_user_id,
            list_id=user_list_id,
            limit=2,
            cursor=1,
            cursor_created_at=None,
        )
