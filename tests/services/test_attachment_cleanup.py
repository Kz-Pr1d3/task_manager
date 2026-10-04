"""Тесты AttachmentCleanupService."""

from datetime import timedelta

import pytest

from src.core.config import configs
from src.repository.attachment import AttachmentRepository
from src.repository.base import BaseRepository
from src.services.attachment_cleanup import AttachmentCleanupService

INBOX_LIST_ID = 1
LIMIT = 5


@pytest.fixture
async def task_id(base_repo: BaseRepository, test_user_id: int) -> int:
    row = await base_repo.one(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        VALUES ($1, $2, 'cleanup-attach-test', 'active')
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


@pytest.fixture
def cleanup_service(attachment_repo: AttachmentRepository) -> AttachmentCleanupService:
    return AttachmentCleanupService(
        repository=attachment_repo,
        ttl=configs.attachment_pending_ttl,
    )


async def test__tick__deletes_stale_pending(
        cleanup_service: AttachmentCleanupService,
        attachment_repo: AttachmentRepository,
        base_repo: BaseRepository,
        test_user_id: int,
        task_id: int,
):
    stale = await attachment_repo.create_pending(
        user_id=test_user_id,
        task_id=task_id,
        storage_key=f"tmp/pending/{test_user_id}/stale-tick.pdf",
        original_name="stale.pdf",
        content_type="application/pdf",
        size_bytes=10,
        limit=LIMIT,
    )
    fresh = await attachment_repo.create_pending(
        user_id=test_user_id,
        task_id=task_id,
        storage_key=f"tmp/pending/{test_user_id}/fresh-tick.pdf",
        original_name="fresh.pdf",
        content_type="application/pdf",
        size_bytes=10,
        limit=LIMIT,
    )
    assert stale.attachment is not None
    assert fresh.attachment is not None

    await base_repo.query(
        """
        UPDATE task_attachment
        SET created_at = now() - interval '25 hours'
        WHERE id = $1
        """,
        stale.attachment.id,
    )

    deleted = await cleanup_service.tick()
    assert deleted == 1
    assert (
        await attachment_repo.get_by_id(
            attachment_id=stale.attachment.id,
            task_id=task_id,
            user_id=test_user_id,
        )
        is None
    )
    assert (
        await attachment_repo.get_by_id(
            attachment_id=fresh.attachment.id,
            task_id=task_id,
            user_id=test_user_id,
        )
        is not None
    )


async def test__tick__noop_when_nothing_stale(
        cleanup_service: AttachmentCleanupService,
        attachment_repo: AttachmentRepository,
        test_user_id: int,
        task_id: int,
):
    created = await attachment_repo.create_pending(
        user_id=test_user_id,
        task_id=task_id,
        storage_key=f"tmp/pending/{test_user_id}/noop.pdf",
        original_name="noop.pdf",
        content_type="application/pdf",
        size_bytes=10,
        limit=LIMIT,
    )
    assert created.attachment is not None

    deleted = await cleanup_service.tick()
    assert deleted == 0
    assert (
        await attachment_repo.get_by_id(
            attachment_id=created.attachment.id,
            task_id=task_id,
            user_id=test_user_id,
        )
        is not None
    )


async def test__tick__respects_custom_ttl(
        attachment_repo: AttachmentRepository,
        base_repo: BaseRepository,
        test_user_id: int,
        task_id: int,
):
    created = await attachment_repo.create_pending(
        user_id=test_user_id,
        task_id=task_id,
        storage_key=f"tmp/pending/{test_user_id}/ttl.pdf",
        original_name="ttl.pdf",
        content_type="application/pdf",
        size_bytes=10,
        limit=LIMIT,
    )
    assert created.attachment is not None
    await base_repo.query(
        """
        UPDATE task_attachment
        SET created_at = now() - interval '2 hours'
        WHERE id = $1
        """,
        created.attachment.id,
    )

    short = AttachmentCleanupService(
        repository=attachment_repo,
        ttl=timedelta(hours=1),
    )
    assert await short.tick() == 1
    assert (
        await attachment_repo.get_by_id(
            attachment_id=created.attachment.id,
            task_id=task_id,
            user_id=test_user_id,
        )
        is None
    )
