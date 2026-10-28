"""Тесты AttachmentService (реальный MinIO + БД)."""

import pytest
from botocore.exceptions import ClientError

from src.core.config import configs
from src.core.exceptions import (
    ConflictException,
    NotFoundException,
    PayloadTooLargeException,
    UnprocessableEntityException,
)
from src.core.s3 import S3Storage
from src.models.attachments import DownloadAccelResult, DownloadUrlResult, TaskAttachment
from src.models.enums import AttachmentDownloadMode, AttachmentStatus
from src.repository.attachment import AttachmentRepository
from src.repository.base import BaseRepository
from src.services.attachment import AttachmentService

INBOX_LIST_ID = 1


async def _ready_png(
        service: AttachmentService,
        s3_storage: S3Storage,
        *,
        user_id: int,
        task_id: int,
        filename: str = "pic.png",
        body: bytes = b"png!",
) -> TaskAttachment:
    """initiate → PUT → complete для готового PNG-вложения."""
    initiated = await service.initiate_upload(
        user_id=user_id,
        task_id=task_id,
        filename=filename,
        content_type="image/png",
        size_bytes=len(body),
    )
    pending = await service.repository.get_by_id(
        attachment_id=initiated.id,
        task_id=task_id,
        user_id=user_id,
    )
    assert pending is not None
    await s3_storage.put_object(
        pending.storage_key,
        body,
        content_type="image/png",
    )
    return await service.complete_upload(
        user_id=user_id,
        task_id=task_id,
        attachment_id=initiated.id,
    )


@pytest.fixture
async def task_id(base_repo: BaseRepository, test_user_id: int) -> int:
    row = await base_repo.one(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        VALUES ($1, $2, 'attach-svc-test', 'active')
        RETURNING id
        """,
        test_user_id,
        INBOX_LIST_ID,
    )
    tid = row["id"]
    yield tid
    await base_repo.query("DELETE FROM task_attachment WHERE task_id = $1", tid)
    await base_repo.query("DELETE FROM tasks WHERE id = $1", tid)
    await base_repo.query(
        """
        SELECT setval(
            pg_get_serial_sequence('task_attachment', 'id'),
            (SELECT COALESCE(MAX(id), 1) FROM task_attachment)
        )
        """
    )
    await base_repo.query(
        """
        SELECT setval(
            pg_get_serial_sequence('tasks', 'id'),
            (SELECT COALESCE(MAX(id), 1) FROM tasks)
        )
        """
    )


async def test__initiate_upload__success(
        attachment_service: AttachmentService,
        attachment_repo: AttachmentRepository,
        test_user_id: int,
        task_id: int,
):
    result = await attachment_service.initiate_upload(
        user_id=test_user_id,
        task_id=task_id,
        filename="photo.JPG",
        content_type="image/jpeg",
        size_bytes=1024,
    )
    assert result.id > 0
    assert result.content_type == "image/jpeg"
    assert result.expires_in == attachment_service.settings.s3_presigned_put_ttl_sec
    assert result.upload_url.startswith("http")

    row = await attachment_repo.get_by_id(
        attachment_id=result.id,
        task_id=task_id,
        user_id=test_user_id,
    )
    assert row is not None
    assert row.status is AttachmentStatus.pending
    assert row.storage_key.startswith(f"tmp/pending/{test_user_id}/")
    assert row.storage_key.endswith(".jpg")
    assert row.original_name == "photo.JPG"


async def test__initiate_upload__rejects_mime(
        attachment_service: AttachmentService,
        test_user_id: int,
        task_id: int,
):
    with pytest.raises(UnprocessableEntityException):
        await attachment_service.initiate_upload(
            user_id=test_user_id,
            task_id=task_id,
            filename="x.exe",
            content_type="application/octet-stream",
            size_bytes=10,
        )


async def test__initiate_upload__rejects_size(
        attachment_service: AttachmentService,
        test_user_id: int,
        task_id: int,
):
    too_big = attachment_service.settings.attachment_max_bytes + 1
    with pytest.raises(PayloadTooLargeException):
        await attachment_service.initiate_upload(
            user_id=test_user_id,
            task_id=task_id,
            filename="big.jpg",
            content_type="image/jpeg",
            size_bytes=too_big,
        )


async def test__initiate_upload__foreign_task(
        attachment_service: AttachmentService,
        test_user_id: int,
):
    with pytest.raises(NotFoundException):
        await attachment_service.initiate_upload(
            user_id=test_user_id,
            task_id=999_999_999,
            filename="a.png",
            content_type="image/png",
            size_bytes=10,
        )


async def test__initiate_upload__limit(
        attachment_service: AttachmentService,
        test_user_id: int,
        task_id: int,
):
    limit = attachment_service.settings.attachment_max_per_task
    for i in range(limit):
        await attachment_service.initiate_upload(
            user_id=test_user_id,
            task_id=task_id,
            filename=f"slot-{i}.png",
            content_type="image/png",
            size_bytes=10,
        )

    with pytest.raises(ConflictException) as exc_info:
        await attachment_service.initiate_upload(
            user_id=test_user_id,
            task_id=task_id,
            filename="over.png",
            content_type="image/png",
            size_bytes=10,
        )
    assert "limit" in str(exc_info.value.detail).lower()


async def test__complete_upload__success(
        attachment_service: AttachmentService,
        s3_storage: S3Storage,
        test_user_id: int,
        task_id: int,
):
    initiated = await attachment_service.initiate_upload(
        user_id=test_user_id,
        task_id=task_id,
        filename="doc.pdf",
        content_type="application/pdf",
        size_bytes=11,
    )
    pending = await attachment_service.repository.get_by_id(
        attachment_id=initiated.id,
        task_id=task_id,
        user_id=test_user_id,
    )
    assert pending is not None

    body = b"%PDF-1.4hi"
    await s3_storage.put_object(
        pending.storage_key,
        body,
        content_type="application/pdf",
    )

    ready = await attachment_service.complete_upload(
        user_id=test_user_id,
        task_id=task_id,
        attachment_id=initiated.id,
    )
    assert ready.status is AttachmentStatus.ready
    assert ready.size_bytes == len(body)
    assert ready.storage_key.startswith(
        f"users/{test_user_id}/tasks/{task_id}/",
    )
    assert ready.storage_key.endswith(".pdf")
    assert ready.ready_at is not None

    with pytest.raises(ClientError):
        await s3_storage.head_object(pending.storage_key)

    head = await s3_storage.head_object(ready.storage_key)
    assert head["ContentLength"] == len(body)

    await s3_storage.delete_object(ready.storage_key)


async def test__complete_upload__missing_object(
        attachment_service: AttachmentService,
        test_user_id: int,
        task_id: int,
):
    initiated = await attachment_service.initiate_upload(
        user_id=test_user_id,
        task_id=task_id,
        filename="gone.png",
        content_type="image/png",
        size_bytes=10,
    )
    with pytest.raises(ConflictException) as exc_info:
        await attachment_service.complete_upload(
            user_id=test_user_id,
            task_id=task_id,
            attachment_id=initiated.id,
        )
    assert "not found" in str(exc_info.value.detail).lower()

    still = await attachment_service.repository.get_by_id(
        attachment_id=initiated.id,
        task_id=task_id,
        user_id=test_user_id,
    )
    assert still is not None
    assert still.status is AttachmentStatus.pending


async def test__complete_upload__oversize_head(
        attachment_service: AttachmentService,
        s3_storage: S3Storage,
        attachment_repo: AttachmentRepository,
        test_user_id: int,
        task_id: int,
):
    initiated = await attachment_service.initiate_upload(
        user_id=test_user_id,
        task_id=task_id,
        filename="fat.webp",
        content_type="image/webp",
        size_bytes=100,
    )
    pending = await attachment_repo.get_by_id(
        attachment_id=initiated.id,
        task_id=task_id,
        user_id=test_user_id,
    )
    assert pending is not None

    # Клиент залил больше заявленного / лимита
    max_bytes = attachment_service.settings.attachment_max_bytes
    body = b"x" * (max_bytes + 1)
    await s3_storage.put_object(
        pending.storage_key,
        body,
        content_type="image/webp",
    )

    with pytest.raises(PayloadTooLargeException):
        await attachment_service.complete_upload(
            user_id=test_user_id,
            task_id=task_id,
            attachment_id=initiated.id,
        )

    failed = await attachment_repo.get_by_id(
        attachment_id=initiated.id,
        task_id=task_id,
        user_id=test_user_id,
    )
    assert failed is not None
    assert failed.status is AttachmentStatus.failed

    with pytest.raises(ClientError):
        await s3_storage.head_object(pending.storage_key)


def test__path_and_query_from_url__strips_host():
    url = (
        "http://minio:9000/task-manager-media/users/1/a.png"
        "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=abc"
    )
    assert AttachmentService.path_and_query_from_url(url) == (
        "/task-manager-media/users/1/a.png"
        "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=abc"
    )


def test__build_x_accel_redirect__joins_prefix():
    service = AttachmentService.__new__(AttachmentService)
    service.settings = configs.model_copy(
        update={"s3_x_accel_prefix": "/internal-s3"},
    )
    assert service.build_x_accel_redirect(
        "/bucket/key?X-Amz-Signature=x",
    ) == "/internal-s3/bucket/key?X-Amz-Signature=x"


async def test__get_download_url__ready(
        attachment_service: AttachmentService,
        s3_storage: S3Storage,
        test_user_id: int,
        task_id: int,
):
    ready = await _ready_png(
        attachment_service,
        s3_storage,
        user_id=test_user_id,
        task_id=task_id,
    )

    download = await attachment_service.get_download_url(
        user_id=test_user_id,
        task_id=task_id,
        attachment_id=ready.id,
    )
    assert isinstance(download, DownloadUrlResult)
    assert download.url.startswith("http")
    assert download.expires_in == attachment_service.settings.s3_presigned_get_ttl_sec

    await s3_storage.delete_object(ready.storage_key)


async def test__get_download_url__x_accel(
        attachment_repo: AttachmentRepository,
        s3_storage: S3Storage,
        test_user_id: int,
        task_id: int,
):
    settings = configs.model_copy(
        update={"attachment_download_mode": AttachmentDownloadMode.x_accel},
    )
    service = AttachmentService(
        repository=attachment_repo,
        s3=s3_storage,
        settings=settings,
    )
    ready = await _ready_png(
        service,
        s3_storage,
        user_id=test_user_id,
        task_id=task_id,
    )

    download = await service.get_download_url(
        user_id=test_user_id,
        task_id=task_id,
        attachment_id=ready.id,
    )
    assert isinstance(download, DownloadAccelResult)
    assert download.x_accel_redirect.startswith("/internal-s3/")
    assert "X-Amz-Signature=" in download.x_accel_redirect
    assert "localhost:9000" not in download.x_accel_redirect
    assert configs.s3_endpoint_url not in download.x_accel_redirect
    assert download.content_type == "image/png"
    assert 'filename="pic.png"' in download.content_disposition
    assert download.expires_in == settings.s3_presigned_get_ttl_sec

    await s3_storage.delete_object(ready.storage_key)


async def test__delete_attachment__removes_s3(
        attachment_service: AttachmentService,
        s3_storage: S3Storage,
        test_user_id: int,
        task_id: int,
):
    initiated = await attachment_service.initiate_upload(
        user_id=test_user_id,
        task_id=task_id,
        filename="del.jpg",
        content_type="image/jpeg",
        size_bytes=3,
    )
    pending = await attachment_service.repository.get_by_id(
        attachment_id=initiated.id,
        task_id=task_id,
        user_id=test_user_id,
    )
    assert pending is not None
    await s3_storage.put_object(
        pending.storage_key,
        b"jpg",
        content_type="image/jpeg",
    )
    ready = await attachment_service.complete_upload(
        user_id=test_user_id,
        task_id=task_id,
        attachment_id=initiated.id,
    )

    await attachment_service.delete_attachment(
        user_id=test_user_id,
        task_id=task_id,
        attachment_id=ready.id,
    )
    assert (
        await attachment_service.repository.get_by_id(
            attachment_id=ready.id,
            task_id=task_id,
            user_id=test_user_id,
        )
        is None
    )
    with pytest.raises(ClientError):
        await s3_storage.head_object(ready.storage_key)


async def test__list_ready__only_ready(
        attachment_service: AttachmentService,
        s3_storage: S3Storage,
        test_user_id: int,
        task_id: int,
):
    pending_init = await attachment_service.initiate_upload(
        user_id=test_user_id,
        task_id=task_id,
        filename="pending.png",
        content_type="image/png",
        size_bytes=1,
    )
    ready_init = await attachment_service.initiate_upload(
        user_id=test_user_id,
        task_id=task_id,
        filename="ready.png",
        content_type="image/png",
        size_bytes=1,
    )
    ready_row = await attachment_service.repository.get_by_id(
        attachment_id=ready_init.id,
        task_id=task_id,
        user_id=test_user_id,
    )
    assert ready_row is not None
    await s3_storage.put_object(
        ready_row.storage_key,
        b"1",
        content_type="image/png",
    )
    ready = await attachment_service.complete_upload(
        user_id=test_user_id,
        task_id=task_id,
        attachment_id=ready_init.id,
    )

    items = await attachment_service.list_ready(
        user_id=test_user_id,
        task_id=task_id,
    )
    ids = {item.id for item in items}
    assert ready.id in ids
    assert pending_init.id not in ids

    await s3_storage.delete_object(ready.storage_key)
