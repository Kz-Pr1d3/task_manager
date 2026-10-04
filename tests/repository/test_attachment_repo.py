"""Тесты AttachmentRepository."""

from datetime import timedelta

import pytest

from src.models.enums import AttachmentStatus, AttachmentWriteStatus
from src.repository.attachment import AttachmentRepository
from src.repository.base import BaseRepository

INBOX_LIST_ID = 1
LIMIT = 5


@pytest.fixture
async def task_id(base_repo: BaseRepository, test_user_id: int) -> int:
    row = await base_repo.one(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        VALUES ($1, $2, 'attach-test', 'active')
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
async def other_user_task(
        base_repo: BaseRepository,
) -> tuple[int, int]:
    user = await base_repo.one(
        """
        INSERT INTO users (email, password)
        VALUES ('attach_other@test.com', 'hash')
        ON CONFLICT (email) DO UPDATE SET password = EXCLUDED.password
        RETURNING id
        """
    )
    uid = user["id"]
    task = await base_repo.one(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        VALUES ($1, $2, 'other-task', 'active')
        RETURNING id
        """,
        uid,
        INBOX_LIST_ID,
    )
    tid = task["id"]
    yield uid, tid
    await base_repo.query("DELETE FROM task_attachment WHERE task_id = $1", tid)
    await base_repo.query("DELETE FROM tasks WHERE id = $1", tid)
    await base_repo.query("DELETE FROM users WHERE id = $1", uid)


async def test__create_pending__success(
        attachment_repo: AttachmentRepository,
        test_user_id: int,
        task_id: int,
):
    result = await attachment_repo.create_pending(
        user_id=test_user_id,
        task_id=task_id,
        storage_key=f"tmp/pending/{test_user_id}/abc.pdf",
        original_name="doc.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        limit=LIMIT,
    )
    assert result.status is AttachmentWriteStatus.ok
    assert result.attachment is not None
    assert result.attachment.status is AttachmentStatus.pending
    assert result.attachment.original_name == "doc.pdf"
    assert result.attachment.task_id == task_id


async def test__create_pending__forbidden_foreign_task(
        attachment_repo: AttachmentRepository,
        test_user_id: int,
        other_user_task: tuple[int, int],
):
    _, foreign_task_id = other_user_task
    result = await attachment_repo.create_pending(
        user_id=test_user_id,
        task_id=foreign_task_id,
        storage_key="tmp/pending/x/y.bin",
        original_name="x.bin",
        content_type="application/octet-stream",
        size_bytes=1,
        limit=LIMIT,
    )
    assert result.status is AttachmentWriteStatus.forbidden
    assert result.attachment is None


async def test__create_pending__limit(
        attachment_repo: AttachmentRepository,
        test_user_id: int,
        task_id: int,
):
    for i in range(LIMIT):
        result = await attachment_repo.create_pending(
            user_id=test_user_id,
            task_id=task_id,
            storage_key=f"tmp/pending/{test_user_id}/{i}.pdf",
            original_name=f"{i}.pdf",
            content_type="application/pdf",
            size_bytes=10,
            limit=LIMIT,
        )
        assert result.status is AttachmentWriteStatus.ok

    over = await attachment_repo.create_pending(
        user_id=test_user_id,
        task_id=task_id,
        storage_key=f"tmp/pending/{test_user_id}/over.pdf",
        original_name="over.pdf",
        content_type="application/pdf",
        size_bytes=10,
        limit=LIMIT,
    )
    assert over.status is AttachmentWriteStatus.limit
    assert over.attachment is None


async def test__get_list_mark_delete_roundtrip(
        attachment_repo: AttachmentRepository,
        test_user_id: int,
        task_id: int,
):
    created = await attachment_repo.create_pending(
        user_id=test_user_id,
        task_id=task_id,
        storage_key=f"tmp/pending/{test_user_id}/round.pdf",
        original_name="round.pdf",
        content_type="application/pdf",
        size_bytes=100,
        limit=LIMIT,
    )
    att = created.attachment
    assert att is not None

    got = await attachment_repo.get_by_id(
        attachment_id=att.id,
        task_id=task_id,
        user_id=test_user_id,
    )
    assert got is not None
    assert got.id == att.id

    assert await attachment_repo.list_ready(task_id=task_id, user_id=test_user_id) == []
    assert await attachment_repo.count_ready(task_id=task_id, user_id=test_user_id) == 0

    final_key = f"users/{test_user_id}/tasks/{task_id}/round.pdf"
    ready = await attachment_repo.mark_ready(
        attachment_id=att.id,
        task_id=task_id,
        user_id=test_user_id,
        storage_key=final_key,
        size_bytes=100,
        content_type="application/pdf",
    )
    assert ready is not None
    assert ready.status is AttachmentStatus.ready
    assert ready.storage_key == final_key
    assert ready.ready_at is not None

    listed = await attachment_repo.list_ready(task_id=task_id, user_id=test_user_id)
    assert len(listed) == 1
    assert listed[0].id == att.id
    assert await attachment_repo.count_ready(task_id=task_id, user_id=test_user_id) == 1

    deleted = await attachment_repo.delete(
        attachment_id=att.id,
        task_id=task_id,
        user_id=test_user_id,
    )
    assert deleted is not None
    assert deleted.storage_key == final_key
    assert (
        await attachment_repo.get_by_id(
            attachment_id=att.id,
            task_id=task_id,
            user_id=test_user_id,
        )
        is None
    )


async def test__mark_failed__from_pending(
        attachment_repo: AttachmentRepository,
        test_user_id: int,
        task_id: int,
):
    created = await attachment_repo.create_pending(
        user_id=test_user_id,
        task_id=task_id,
        storage_key=f"tmp/pending/{test_user_id}/fail.pdf",
        original_name="fail.pdf",
        content_type="application/pdf",
        size_bytes=50,
        limit=LIMIT,
    )
    att = created.attachment
    assert att is not None

    failed = await attachment_repo.mark_failed(
        attachment_id=att.id,
        task_id=task_id,
        user_id=test_user_id,
    )
    assert failed is not None
    assert failed.status is AttachmentStatus.failed
    assert await attachment_repo.list_ready(task_id=task_id, user_id=test_user_id) == []


async def test__delete_stale_pending__removes_old_keeps_fresh(
        attachment_repo: AttachmentRepository,
        base_repo: BaseRepository,
        test_user_id: int,
        task_id: int,
):
    stale = await attachment_repo.create_pending(
        user_id=test_user_id,
        task_id=task_id,
        storage_key=f"tmp/pending/{test_user_id}/stale.pdf",
        original_name="stale.pdf",
        content_type="application/pdf",
        size_bytes=10,
        limit=LIMIT,
    )
    fresh = await attachment_repo.create_pending(
        user_id=test_user_id,
        task_id=task_id,
        storage_key=f"tmp/pending/{test_user_id}/fresh.pdf",
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

    async with attachment_repo.transaction() as conn:
        locked, deleted = await attachment_repo.delete_stale_pending(
            older_than=timedelta(hours=24),
            conn=conn,
        )
    assert locked is True
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
    assert await attachment_repo.count_pending() == 1


async def test__delete_stale_pending__skips_ready(
        attachment_repo: AttachmentRepository,
        base_repo: BaseRepository,
        test_user_id: int,
        task_id: int,
):
    created = await attachment_repo.create_pending(
        user_id=test_user_id,
        task_id=task_id,
        storage_key=f"tmp/pending/{test_user_id}/old-ready.pdf",
        original_name="old-ready.pdf",
        content_type="application/pdf",
        size_bytes=10,
        limit=LIMIT,
    )
    att = created.attachment
    assert att is not None
    await attachment_repo.mark_ready(
        attachment_id=att.id,
        task_id=task_id,
        user_id=test_user_id,
        storage_key=f"users/{test_user_id}/tasks/{task_id}/old-ready.pdf",
        size_bytes=10,
        content_type="application/pdf",
    )
    await base_repo.query(
        """
        UPDATE task_attachment
        SET created_at = now() - interval '48 hours'
        WHERE id = $1
        """,
        att.id,
    )

    async with attachment_repo.transaction() as conn:
        locked, deleted = await attachment_repo.delete_stale_pending(
            older_than=timedelta(hours=24),
            conn=conn,
        )
    assert locked is True
    assert deleted == 0
    assert (
        await attachment_repo.get_by_id(
            attachment_id=att.id,
            task_id=task_id,
            user_id=test_user_id,
        )
        is not None
    )