from datetime import datetime, timezone

import pytest

from src.models.notification import (
    MarkNotificationsRead,
    NotificationEvent,
)
from src.repository.base import BaseRepository
from src.repository.notification import NotificationRepository
from src.services.notification import NotificationService


@pytest.fixture
async def cleanup_notifications(base_repo: BaseRepository, test_user_id: int):
    yield
    await base_repo.query("DELETE FROM notification WHERE recipient_id = $1", test_user_id)
    await base_repo.query(
        """
        SELECT setval(
            pg_get_serial_sequence('notification', 'id'),
            (SELECT COALESCE(MAX(id), 1) FROM notification)
        )
        """
    )


def _event(*, event_id: str, recipient_ids: set[int], title: str = "Test") -> NotificationEvent:
    return NotificationEvent(
        event_id=event_id,
        type="task.deadline_reminder",
        category="tasks",
        severity="important",
        actor_id=None,
        recipient_ids=recipient_ids,
        entity_type="task",
        entity_id="1",
        title=title,
        metadata={"task_id": 1},
        deep_link="/tasks/1",
        occurred_at=datetime.now(timezone.utc),
    )


async def test__emit__creates_and_returns_recipients(
        notification_service: NotificationService,
        notification_repo: NotificationRepository,
        test_user_id: int,
        cleanup_notifications,
):
    created = await notification_service.emit(
        event=_event(event_id="svc-emit-1", recipient_ids={test_user_id}, title="Hello"),
    )
    assert created == {test_user_id}

    items = await notification_repo.list_notifications(recipient_id=test_user_id, limit=10)
    assert len(items) == 1
    assert items[0].title == "Hello"
    assert items[0].severity == "important"


async def test__emit__idempotent_same_event_id(
        notification_service: NotificationService,
        notification_repo: NotificationRepository,
        test_user_id: int,
        cleanup_notifications,
):
    event = _event(event_id="svc-same", recipient_ids={test_user_id})
    first = await notification_service.emit(event=event)
    second = await notification_service.emit(event=event)

    assert first == {test_user_id}
    assert second == set()

    items = await notification_repo.list_notifications(recipient_id=test_user_id, limit=10)
    assert len(items) == 1


async def test__emit__empty_recipients(
        notification_service: NotificationService,
):
    created = await notification_service.emit(
        event=_event(event_id="svc-empty", recipient_ids=set()),
    )
    assert created == set()


async def test__emit__excludes_actor(
        notification_service: NotificationService,
        test_user_id: int,
        cleanup_notifications,
):
    event = NotificationEvent(
        event_id="svc-actor",
        type="task.assigned",
        severity="important",
        actor_id=test_user_id,
        recipient_ids={test_user_id},
        title="Self",
    )
    created = await notification_service.emit(event=event)
    assert created == set()


async def test__mark_read__updates_ids(
        notification_service: NotificationService,
        notification_repo: NotificationRepository,
        test_user_id: int,
        cleanup_notifications,
):
    await notification_service.emit(
        event=_event(event_id="svc-mark", recipient_ids={test_user_id}),
    )
    items = await notification_repo.list_notifications(recipient_id=test_user_id, limit=10)
    result = await notification_service.mark_read(
        recipient_id=test_user_id,
        body=MarkNotificationsRead(ids=[items[0].id]),
    )
    assert result.updated_ids == [items[0].id]


async def test__mark_read__nothing_updated(
        notification_service: NotificationService,
        test_user_id: int,
):
    result = await notification_service.mark_read(
        recipient_id=test_user_id,
        body=MarkNotificationsRead(ids=[999_999_999]),
    )
    assert result.updated_ids == []


async def test__mark_unread__updates_ids(
        notification_service: NotificationService,
        notification_repo: NotificationRepository,
        test_user_id: int,
        cleanup_notifications,
):
    await notification_service.emit(
        event=_event(event_id="svc-unmark", recipient_ids={test_user_id}),
    )
    items = await notification_repo.list_notifications(recipient_id=test_user_id, limit=10)
    nid = items[0].id
    await notification_service.mark_read(
        recipient_id=test_user_id,
        body=MarkNotificationsRead(ids=[nid]),
    )
    result = await notification_service.mark_unread(
        recipient_id=test_user_id,
        ids=[nid],
    )
    assert result.updated_ids == [nid]
