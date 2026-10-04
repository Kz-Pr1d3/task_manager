import pytest
from botocore.exceptions import ClientError

from src.core.config import configs
from src.core.database import db
from src.core.s3 import S3Storage, create_s3_client_cm
from src.repository.attachment import AttachmentRepository
from src.repository.base import BaseRepository
from src.repository.notification import NotificationRepository
from src.services.attachment import AttachmentService
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


@pytest.fixture
async def attachment_repo(create_pool) -> AttachmentRepository:
    return AttachmentRepository(pool=create_pool.pool)


@pytest.fixture
async def s3_storage():
    async with create_s3_client_cm() as client:
        storage = S3Storage(client=client, bucket=configs.s3_bucket)
        try:
            await storage.ensure_bucket()
        except ClientError as exc:
            pytest.skip(f"MinIO unavailable: {exc}")
        yield storage


@pytest.fixture
async def attachment_service(
        attachment_repo: AttachmentRepository,
        s3_storage: S3Storage,
) -> AttachmentService:
    return AttachmentService(repository=attachment_repo, s3=s3_storage)
