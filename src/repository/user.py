import asyncpg

from src.models.user import User
from src.repository.base import BaseRepository


class UserRepository(BaseRepository):
    """Репозиторий пользователей: CRUD по таблице users."""

    def __init__(self, pool: asyncpg.Pool):
        """
        Инициализирует репозиторий пользователей.

        :param pool: пул соединений asyncpg.
        """
        super().__init__(pool)
        self.user_model = User

    async def create(self, email: str, password: str) -> User | None:
        """
        Создаёт пользователя с email и хешем пароля.

        :param email: email нового пользователя.
        :param password: уже захэшированный пароль.
        :returns: созданный ``User`` или ``None`` при сбое INSERT.
        """
        query = "INSERT INTO users (email, password) VALUES ($1, $2) RETURNING id, email"
        row = await self.one(query, email, password)
        if row is not None:
            return self.user_model(**row)

    async def get_by_id(self, user_id: int) -> User | None:
        """
        Ищет пользователя по первичному ключу.

        :param user_id: идентификатор пользователя.
        :returns: ``User`` или ``None``, если не найден.
        """
        query = "SELECT id, email, password, created_at FROM users WHERE id = $1"
        row = await self.one(query, user_id)
        if row is not None:
            return self.user_model(**row)

    async def get_by_email(self, email: str) -> User | None:
        """
        Ищет пользователя по уникальному email.

        :param email: email для поиска.
        :returns: ``User`` или ``None``, если не найден.
        """
        query = "SELECT id, email, password, created_at FROM users WHERE email = $1"
        row = await self.one(query, email)
        if row is not None:
            return self.user_model(**row)

    async def update_password(self, user_id: int, password: str) -> User | None:
        """
        Обновляет хеш пароля пользователя.

        :param user_id: идентификатор пользователя.
        :param password: новый захэшированный пароль.
        :returns: обновлённый ``User`` или ``None``, если не найден.
        """
        query = "UPDATE users SET password = $2 WHERE id = $1 RETURNING id, email"
        row = await self.one(query, user_id, password)
        if row is not None:
            return self.user_model(**row)

    async def delete(self, user_id: int) -> User | None:
        """
        Удаляет пользователя по идентификатору.

        :param user_id: идентификатор пользователя.
        :returns: удалённый ``User`` или ``None``, если не найден.
        """
        query = "DELETE FROM users WHERE id = $1 RETURNING id, email"
        row = await self.one(query, user_id)
        if row is not None:
            return self.user_model(**row)
