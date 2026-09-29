import pytest

from src.core.database import db
from src.repository.base import BaseRepository
from src.repository.notification import NotificationRepository
from src.services.notification import NotificationService


@pytest.fixture
async def create_pool():
    await db.connect()
    yield db
    await db.disconnect()


@pytest.fixture
async def base_repo(create_pool) -> BaseRepository:
    return BaseRepository(pool=create_pool.pool)


@pytest.fixture
async def notification_repo(create_pool) -> NotificationRepository:
    return NotificationRepository(pool=create_pool.pool)


@pytest.fixture
async def notification_service(notification_repo: NotificationRepository) -> NotificationService:
    return NotificationService(repository=notification_repo)
