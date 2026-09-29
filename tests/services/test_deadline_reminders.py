from datetime import datetime, timedelta, timezone

import pytest

from src.core.config import configs
from src.repository.base import BaseRepository
from src.repository.notification import NotificationRepository
from src.repository.task import TaskRepository
from src.services.deadline_reminders import (
    DeadlineRemindersService,
    build_deadline_reminder_event,
)
from src.services.notification import NotificationService


INBOX_LIST_ID = 1


@pytest.fixture
async def cleanup_deadline_data(base_repo: BaseRepository, test_user_id: int):
    yield
    await base_repo.query("DELETE FROM notification WHERE recipient_id = $1", test_user_id)
    await base_repo.query(
        "DELETE FROM tasks WHERE user_id = $1 AND list_id = $2",
        test_user_id,
        INBOX_LIST_ID,
    )
    await base_repo.query(
        """
        SELECT setval(
            pg_get_serial_sequence('notification', 'id'),
            (SELECT COALESCE(MAX(id), 1) FROM notification)
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
def task_repo(create_pool) -> TaskRepository:
    return TaskRepository(pool=create_pool.pool)


@pytest.fixture
def reminders_service(
        task_repo: TaskRepository,
        notification_service: NotificationService,
) -> DeadlineRemindersService:
    return DeadlineRemindersService(
        task_repository=task_repo,
        notification_service=notification_service,
        window=configs.deadline_reminder_window,
    )


async def _insert_task(
        base_repo: BaseRepository,
        *,
        user_id: int,
        title: str,
        due_date: datetime | None,
        status: str = "active",
        deleted_at: datetime | None = None,
) -> dict:
    row = await base_repo.one(
        """
        INSERT INTO tasks (user_id, list_id, title, due_date, status, deleted_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id, title, due_date, user_id
        """,
        user_id,
        INBOX_LIST_ID,
        title,
        due_date,
        status,
        deleted_at,
    )
    return dict(row)


class RecordingPublisher:
    def __init__(self):
        self.calls: list[set[int]] = []

    async def publish_many(self, user_ids: set[int]) -> None:
        self.calls.append(set(user_ids))


async def test__tick__creates_reminder_in_window(
        reminders_service: DeadlineRemindersService,
        notification_repo: NotificationRepository,
        base_repo: BaseRepository,
        test_user_id: int,
        cleanup_deadline_data,
):
    due = datetime.now(timezone.utc) + timedelta(hours=12)
    task = await _insert_task(
        base_repo,
        user_id=test_user_id,
        title="soon",
        due_date=due,
    )

    changed = await reminders_service.tick()
    assert changed == {test_user_id}

    items = await notification_repo.list_notifications(recipient_id=test_user_id, limit=10)
    assert len(items) == 1
    assert items[0].type == "task.deadline_reminder"
    assert items[0].title == "Скоро дедлайн: soon"
    assert items[0].deep_link == f"/tasks/{task['id']}"
    assert items[0].entity_id == str(task["id"])


async def test__tick__second_tick_no_duplicate(
        reminders_service: DeadlineRemindersService,
        notification_repo: NotificationRepository,
        base_repo: BaseRepository,
        test_user_id: int,
        cleanup_deadline_data,
):
    due = datetime.now(timezone.utc) + timedelta(hours=6)
    await _insert_task(
        base_repo,
        user_id=test_user_id,
        title="idem",
        due_date=due,
    )

    first = await reminders_service.tick()
    second = await reminders_service.tick()

    assert first == {test_user_id}
    assert second == set()

    items = await notification_repo.list_notifications(recipient_id=test_user_id, limit=10)
    assert len(items) == 1


async def test__tick__due_date_change_new_event_id(
        reminders_service: DeadlineRemindersService,
        notification_repo: NotificationRepository,
        base_repo: BaseRepository,
        test_user_id: int,
        cleanup_deadline_data,
):
    due1 = datetime.now(timezone.utc) + timedelta(hours=8)
    task = await _insert_task(
        base_repo,
        user_id=test_user_id,
        title="reschedule",
        due_date=due1,
    )
    await reminders_service.tick()

    due2 = datetime.now(timezone.utc) + timedelta(hours=16)
    await base_repo.query(
        "UPDATE tasks SET due_date = $1 WHERE id = $2",
        due2,
        task["id"],
    )
    changed = await reminders_service.tick()
    assert changed == {test_user_id}

    items = await notification_repo.list_notifications(recipient_id=test_user_id, limit=10)
    assert len(items) == 2

    event1 = build_deadline_reminder_event(
        task_id=task["id"],
        title="reschedule",
        due_date=due1,
        recipient_id=test_user_id,
    )
    event2 = build_deadline_reminder_event(
        task_id=task["id"],
        title="reschedule",
        due_date=due2,
        recipient_id=test_user_id,
    )
    assert event1.event_id != event2.event_id


async def test__tick__completed_not_created(
        reminders_service: DeadlineRemindersService,
        notification_repo: NotificationRepository,
        base_repo: BaseRepository,
        test_user_id: int,
        cleanup_deadline_data,
):
    due = datetime.now(timezone.utc) + timedelta(hours=4)
    await _insert_task(
        base_repo,
        user_id=test_user_id,
        title="done",
        due_date=due,
        status="completed",
    )
    changed = await reminders_service.tick()
    assert changed == set()
    items = await notification_repo.list_notifications(recipient_id=test_user_id, limit=10)
    assert items == []


async def test__tick__deleted_not_created(
        reminders_service: DeadlineRemindersService,
        notification_repo: NotificationRepository,
        base_repo: BaseRepository,
        test_user_id: int,
        cleanup_deadline_data,
):
    due = datetime.now(timezone.utc) + timedelta(hours=4)
    await _insert_task(
        base_repo,
        user_id=test_user_id,
        title="trashed",
        due_date=due,
        deleted_at=datetime.now(timezone.utc),
    )
    changed = await reminders_service.tick()
    assert changed == set()
    items = await notification_repo.list_notifications(recipient_id=test_user_id, limit=10)
    assert items == []


async def test__tick__outside_window_not_created(
        reminders_service: DeadlineRemindersService,
        notification_repo: NotificationRepository,
        base_repo: BaseRepository,
        test_user_id: int,
        cleanup_deadline_data,
):
    due = datetime.now(timezone.utc) + timedelta(hours=48)
    await _insert_task(
        base_repo,
        user_id=test_user_id,
        title="far",
        due_date=due,
    )
    changed = await reminders_service.tick()
    assert changed == set()
    items = await notification_repo.list_notifications(recipient_id=test_user_id, limit=10)
    assert items == []


async def test__tick__past_due_not_created(
        reminders_service: DeadlineRemindersService,
        notification_repo: NotificationRepository,
        base_repo: BaseRepository,
        test_user_id: int,
        cleanup_deadline_data,
):
    due = datetime.now(timezone.utc) - timedelta(hours=1)
    await _insert_task(
        base_repo,
        user_id=test_user_id,
        title="overdue",
        due_date=due,
    )
    changed = await reminders_service.tick()
    assert changed == set()
    items = await notification_repo.list_notifications(recipient_id=test_user_id, limit=10)
    assert items == []


async def test__tick__publish_after_commit(
        task_repo: TaskRepository,
        notification_service: NotificationService,
        base_repo: BaseRepository,
        test_user_id: int,
        cleanup_deadline_data,
):
    publisher = RecordingPublisher()
    reminders = DeadlineRemindersService(
        task_repository=task_repo,
        notification_service=notification_service,
        window=configs.deadline_reminder_window,
        publisher=publisher,
    )
    due = datetime.now(timezone.utc) + timedelta(hours=3)
    await _insert_task(
        base_repo,
        user_id=test_user_id,
        title="pub",
        due_date=due,
    )

    await reminders.tick()
    assert publisher.calls == [{test_user_id}]

    await reminders.tick()
    assert publisher.calls == [{test_user_id}]


async def test__build_deadline_reminder_event__contract():
    due = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
    event = build_deadline_reminder_event(
        task_id=42,
        title="X",
        due_date=due,
        recipient_id=7,
    )
    assert event.event_id == "task.deadline_reminder:42:7:2026-09-08T12:00:00+00:00:24h"
    assert event.type == "task.deadline_reminder"
    assert event.severity == "important"
    assert event.recipient_ids == {7}
    assert event.actor_id is None
    assert event.entity_type == "task"
    assert event.entity_id == "42"
    assert event.title == "Скоро дедлайн: X"
    assert event.deep_link == "/tasks/42"
    assert event.metadata == {"task_id": 42, "due_date": "2026-09-08T12:00:00+00:00"}
