from datetime import datetime, timezone

import pytest

from src.models.notification import NotificationEvent
from src.repository.base import BaseRepository
from src.repository.notification import NotificationRepository


@pytest.fixture
async def other_user_id(base_repo: BaseRepository) -> int:
    row = await base_repo.one(
        """
        INSERT INTO users (email, password)
        VALUES ('notif_other@test.com', 'hash')
        ON CONFLICT (email) DO UPDATE SET password = EXCLUDED.password
        RETURNING id
        """
    )
    yield row["id"]
    await base_repo.query("DELETE FROM notification WHERE recipient_id = $1", row["id"])
    await base_repo.query("DELETE FROM users WHERE id = $1", row["id"])


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


def _event(
        *,
        event_id: str,
        recipient_ids: set[int],
        title: str = "Test",
        severity: str = "normal",
        category: str = "tasks",
        actor_id: int | None = None,
) -> NotificationEvent:
    return NotificationEvent(
        event_id=event_id,
        type="task.deadline_reminder",
        category=category,
        severity=severity,
        actor_id=actor_id,
        recipient_ids=recipient_ids,
        entity_type="task",
        entity_id="1",
        title=title,
        metadata={"task_id": 1},
        deep_link="/tasks/1",
        occurred_at=datetime.now(timezone.utc),
    )


async def test__create_for_recipients__success(
        notification_repo: NotificationRepository,
        test_user_id: int,
        cleanup_notifications,
):
    created = await notification_repo.create_for_recipients(
        event=_event(event_id="e1", recipient_ids={test_user_id}, title="Hello"),
    )
    assert created == {test_user_id}

    items = await notification_repo.list_notifications(recipient_id=test_user_id, limit=10)
    assert len(items) == 1
    assert items[0].title == "Hello"
    assert items[0].metadata == {"task_id": 1}
    assert items[0].deep_link == "/tasks/1"


async def test__create_for_recipients__idempotent_event_id(
        notification_repo: NotificationRepository,
        test_user_id: int,
        cleanup_notifications,
):
    event = _event(event_id="same-event", recipient_ids={test_user_id})
    first = await notification_repo.create_for_recipients(event=event)
    second = await notification_repo.create_for_recipients(event=event)

    assert first == {test_user_id}
    assert second == set()

    items = await notification_repo.list_notifications(recipient_id=test_user_id, limit=10)
    assert len(items) == 1


async def test__create_for_recipients__excludes_actor(
        notification_repo: NotificationRepository,
        test_user_id: int,
        other_user_id: int,
        cleanup_notifications,
):
    created = await notification_repo.create_for_recipients(
        event=_event(
            event_id="actor-skip",
            recipient_ids={test_user_id, other_user_id},
            actor_id=test_user_id,
        ),
    )
    assert created == {other_user_id}


async def test__list_notifications__recipient_isolation(
        notification_repo: NotificationRepository,
        test_user_id: int,
        other_user_id: int,
        cleanup_notifications,
):
    await notification_repo.create_for_recipients(
        event=_event(event_id="mine", recipient_ids={test_user_id}, title="Mine"),
    )
    await notification_repo.create_for_recipients(
        event=_event(event_id="theirs", recipient_ids={other_user_id}, title="Theirs"),
    )

    mine = await notification_repo.list_notifications(recipient_id=test_user_id, limit=10)
    theirs = await notification_repo.list_notifications(recipient_id=other_user_id, limit=10)

    assert len(mine) == 1
    assert mine[0].title == "Mine"
    assert len(theirs) == 1
    assert theirs[0].title == "Theirs"


async def test__list_notifications__cursor_before_id(
        notification_repo: NotificationRepository,
        test_user_id: int,
        cleanup_notifications,
):
    for i in range(3):
        await notification_repo.create_for_recipients(
            event=_event(event_id=f"cursor-{i}", recipient_ids={test_user_id}, title=f"n{i}"),
        )

    page1 = await notification_repo.list_notifications(recipient_id=test_user_id, limit=2)
    assert len(page1) == 2
    assert page1[0].id > page1[1].id

    page2 = await notification_repo.list_notifications(
        recipient_id=test_user_id,
        limit=2,
        before_id=page1[-1].id,
    )
    assert len(page2) == 1
    assert page2[0].id < page1[-1].id
    assert {n.id for n in page1}.isdisjoint({n.id for n in page2})


async def test__list_notifications__unread_filter(
        notification_repo: NotificationRepository,
        test_user_id: int,
        cleanup_notifications,
):
    await notification_repo.create_for_recipients(
        event=_event(event_id="u1", recipient_ids={test_user_id}, title="unread"),
    )
    await notification_repo.create_for_recipients(
        event=_event(event_id="u2", recipient_ids={test_user_id}, title="read-me"),
    )
    items = await notification_repo.list_notifications(recipient_id=test_user_id, limit=10)
    await notification_repo.mark_read(recipient_id=test_user_id, ids=[items[0].id])

    unread = await notification_repo.list_notifications(
        recipient_id=test_user_id,
        limit=10,
        unread=True,
    )
    assert len(unread) == 1
    assert unread[0].read_at is None
    assert unread[0].title == "unread"


async def test__get_unread_counts__after_read(
        notification_repo: NotificationRepository,
        test_user_id: int,
        cleanup_notifications,
):
    await notification_repo.create_for_recipients(
        event=_event(
            event_id="c1",
            recipient_ids={test_user_id},
            severity="important",
        ),
    )
    await notification_repo.create_for_recipients(
        event=_event(
            event_id="c2",
            recipient_ids={test_user_id},
            severity="normal",
            category="system",
        ),
    )

    counts = await notification_repo.get_unread_counts(recipient_id=test_user_id)
    assert counts.total == 2
    assert counts.important == 1
    assert counts.by_category["tasks"] == 1
    assert counts.by_category["system"] == 1

    items = await notification_repo.list_notifications(recipient_id=test_user_id, limit=10)
    await notification_repo.mark_read_all(recipient_id=test_user_id, category="tasks")

    counts = await notification_repo.get_unread_counts(recipient_id=test_user_id)
    assert counts.total == 1
    assert counts.important == 0
    assert counts.by_category == {"system": 1}


async def test__mark_read__cannot_touch_foreign(
        notification_repo: NotificationRepository,
        test_user_id: int,
        other_user_id: int,
        cleanup_notifications,
):
    await notification_repo.create_for_recipients(
        event=_event(event_id="foreign", recipient_ids={other_user_id}),
    )
    foreign = await notification_repo.list_notifications(recipient_id=other_user_id, limit=1)
    updated = await notification_repo.mark_read(
        recipient_id=test_user_id,
        ids=[foreign[0].id],
    )
    assert updated == []

    still = await notification_repo.list_notifications(recipient_id=other_user_id, limit=1)
    assert still[0].read_at is None


async def test__mark_unread__success(
        notification_repo: NotificationRepository,
        test_user_id: int,
        cleanup_notifications,
):
    await notification_repo.create_for_recipients(
        event=_event(event_id="mu1", recipient_ids={test_user_id}),
    )
    items = await notification_repo.list_notifications(recipient_id=test_user_id, limit=1)
    nid = items[0].id

    await notification_repo.mark_read(recipient_id=test_user_id, ids=[nid])
    updated = await notification_repo.mark_unread(recipient_id=test_user_id, ids=[nid])
    assert updated == [nid]

    items = await notification_repo.list_notifications(recipient_id=test_user_id, limit=1)
    assert items[0].read_at is None
