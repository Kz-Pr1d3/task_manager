from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import asyncpg
from asyncpg import Connection, Record


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

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Connection]:
        """Открывает connection и транзакцию, yield'ит этот connection.

        Ограничения:
        - внутри блока используй только переданный ``conn``
          (``execute`` / ``fetch`` / ``fetchrow`` / ``fetchval``);
        - не вызывай ``self.one()`` / ``self.query()`` — они берут
          другой connection из пула и выполняются вне этой транзакции;
        - при исключении транзакция откатывается целиком.
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                yield conn

    async def update(self): ...
