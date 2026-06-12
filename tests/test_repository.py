import asyncpg
import pytest

from src.core.database import db
from src.repository.base import BaseRepository
from src.repository.user import UserRepository


@pytest.fixture
async def create_pool():
    await db.connect()
    yield db
    await db.disconnect()


async def test__base_one__success(create_pool, select_three_rows):
    base_repo = BaseRepository(pool=create_pool.pool)
    res = await base_repo.one(query=select_three_rows)

    assert isinstance(res, asyncpg.Record)
    assert res["id"] == 1
    assert len(res) == 3


async def test__base_query__success(create_pool, select_three_rows):
    base_repo = BaseRepository(pool=create_pool.pool)
    res = await base_repo.query(query=select_three_rows)

    assert isinstance(res, list)
    assert len(res) == 3


async def test__create__success(create_pool):
    user_repo = UserRepository(pool=create_pool.pool)
    res = await user_repo.create(email="test2@test.com", password="test")
    assert res


async def test__get_by_email__success(create_pool):
    user_repo = UserRepository(pool=create_pool.pool)
    res = await user_repo.get_by_email(email="test2@test.com")
    assert res
