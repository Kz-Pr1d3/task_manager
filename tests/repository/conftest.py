import pytest

from src.core.database import db
from src.repository.base import BaseRepository
from src.repository.list import ListRepository
from src.repository.task import TaskRepository
from src.repository.user import UserRepository


@pytest.fixture
async def create_pool():
    await db.connect()
    yield db
    await db.disconnect()


@pytest.fixture
async def base_repo(create_pool) -> BaseRepository:
    return BaseRepository(pool=create_pool.pool)


@pytest.fixture
async def list_repo(create_pool) -> ListRepository:
    return ListRepository(pool=create_pool.pool)


@pytest.fixture
async def task_repo(create_pool) -> TaskRepository:
    return TaskRepository(pool=create_pool.pool)


@pytest.fixture
async def user_repo(create_pool) -> UserRepository:
    return UserRepository(pool=create_pool.pool)
