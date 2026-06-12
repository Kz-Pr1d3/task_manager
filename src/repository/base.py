import asyncpg
from asyncpg import Record


class BaseRepository:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def one(self, query: str, *args, timeout=None) -> Record:
        async with self.pool.acquire() as connection:
            return await connection.fetchrow(query, *args, timeout=timeout)

    async def query(self, query: str, *args, timeout=None) -> list[Record]:
        async with self.pool.acquire() as connection:
            res = await connection.fetch(query, *args, timeout=timeout)
            return res

    async def update(self): ...
