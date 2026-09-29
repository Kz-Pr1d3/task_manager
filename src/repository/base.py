from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import asyncpg
from asyncpg import Connection, Record


class BaseRepository:
    """Базовый репозиторий с пулом и транзакциями."""

    def __init__(self, pool: asyncpg.Pool):
        """
        Сохраняет пул соединений asyncpg.

        :param pool: пул соединений к PostgreSQL.
        """
        self.pool = pool

    async def one(self, query: str, *args, timeout=None) -> Record:
        """
        Выполняет SQL и возвращает одну строку.

        :param query: SQL-запрос.
        :param args: позиционные параметры запроса.
        :param timeout: таймаут выполнения в секундах.
        :returns: запись ``Record`` или ``None``, если пусто.
        """
        async with self.pool.acquire() as connection:
            return await connection.fetchrow(query, *args, timeout=timeout)

    async def query(self, query: str, *args, timeout=None) -> list[Record]:
        """
        Выполняет SQL и возвращает список строк.

        :param query: SQL-запрос.
        :param args: позиционные параметры запроса.
        :param timeout: таймаут выполнения в секундах.
        :returns: список записей ``Record``.
        """
        async with self.pool.acquire() as connection:
            res = await connection.fetch(query, *args, timeout=timeout)
            return res

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Connection]:
        """
        Открывает connection и транзакцию, yield'ит connection.

        Ограничения:
        - внутри блока используй только переданный ``conn``
          (``execute`` / ``fetch`` / ``fetchrow`` / ``fetchval``);
        - не вызывай ``self.one()`` / ``self.query()`` — они берут
          другой connection из пула и выполняются вне этой транзакции;
        - при исключении транзакция откатывается целиком.

        :returns: async-контекст с ``Connection`` внутри транзакции.
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                yield conn

    async def update(self):
        """Заглушка для обновлений; пока не реализована."""
        ...
