import asyncpg

from src.models.user import User
from src.repository.base import BaseRepository


class UserRepository(BaseRepository):
    def __init__(self, pool: asyncpg.Pool):
        super().__init__(pool)
        self.user_model = User

    async def create(self, email: str, password: str) -> User | None:
        query = "INSERT INTO users (email, password) VALUES ($1, $2) RETURNING id, email"
        row = await self.one(query, email, password)
        if row is not None:
            return self.user_model(**row)

    async def get_by_id(self, user_id: int) -> User | None:
        query = "SELECT id, email FROM users WHERE id = $1"
        row = await self.one(query, user_id)
        if row is not None:
            return self.user_model(**row)

    async def get_by_email(self, email: str) -> User | None:
        query = "SELECT id, email, password, created_at FROM users WHERE email = $1"
        row = await self.one(query, email)
        if row is not None:
            return self.user_model(**row)

    async def update_password(self, user_id: int, password: str) -> User | None:
        query = "UPDATE users SET password = $2 WHERE id = $1 RETURNING id, email"
        row = await self.one(query, user_id, password)
        if row is not None:
            return self.user_model(**row)

    async def delete(self, user_id: int) -> User | None:
        query = "DELETE FROM users WHERE id = $1 RETURNING id, email"
        row = await self.one(query, user_id)
        if row is not None:
            return self.user_model(**row)
