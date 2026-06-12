import asyncpg

from src.core.config import configs


class Database:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.pool = None

    async def connect(self):
        self.pool: asyncpg.Pool = await asyncpg.create_pool(dsn=self.db_url)

    async def disconnect(self):
        await self.pool.close()


db = Database(db_url=configs.database_url)
