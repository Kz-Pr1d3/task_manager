import asyncpg

from src.repository.base import BaseRepository


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


