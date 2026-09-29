import asyncpg

from src.core.config import configs


class Database:
    """Обёртка над asyncpg pool: connect / disconnect."""

    def __init__(self, db_url: str):
        """
        Создаёт обёртку без активного пула.

        :param db_url: DSN PostgreSQL для asyncpg.
        """
        self.db_url = db_url
        self.pool = None

    async def connect(self):
        """Создаёт пул соединений asyncpg по DSN."""
        self.pool: asyncpg.Pool = await asyncpg.create_pool(dsn=self.db_url)

    async def disconnect(self):
        """Закрывает пул соединений asyncpg."""
        await self.pool.close()


db = Database(db_url=configs.database_url)
