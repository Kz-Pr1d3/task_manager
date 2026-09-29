import logging
from datetime import datetime, timedelta, timezone
from typing import Protocol

from src.core.notification_metrics import (
    DEADLINE_WORKER_CANDIDATES,
    DEADLINE_WORKER_RUNS,
)
from src.models.notification import NotificationEvent
from src.repository.task import TaskRepository
from src.services.notification import NotificationService

logger = logging.getLogger(__name__)


class InvalidatePublisher(Protocol):
    """Контракт publish после commit (Redis bus)."""

    async def publish_many(self, user_ids: set[int]) -> None:
        """
        Публикует ``notification.invalidate`` выбранным пользователям.

        :param user_ids: получатели с изменениями.
        """
        ...


def build_deadline_reminder_event(
        *,
        task_id: int,
        title: str,
        due_date: datetime,
        recipient_id: int,
) -> NotificationEvent:
    """
    Собирает ``NotificationEvent`` для task.deadline_reminder.

    ``event_id`` детерминирован по task/recipient/due/окну 24h.

    :param task_id: id задачи.
    :param title: заголовок задачи.
    :param due_date: дедлайн задачи (aware).
    :param recipient_id: ``tasks.user_id``.
    :returns: контракт события для ``emit``.
    """
    due_utc = due_date.astimezone(timezone.utc)
    due_iso = due_utc.isoformat()
    return NotificationEvent(
        event_id=f"task.deadline_reminder:{task_id}:{recipient_id}:{due_iso}:24h",
        type="task.deadline_reminder",
        category="tasks",
        severity="important",
        actor_id=None,
        recipient_ids={recipient_id},
        entity_type="task",
        entity_id=str(task_id),
        title=f"Скоро дедлайн: {title}",
        metadata={"task_id": task_id, "due_date": due_iso},
        deep_link=f"/tasks/{task_id}",
    )


class DeadlineRemindersService:
    """Один тик: кандидаты из repo → emit → commit → publish."""

    def __init__(
            self,
            task_repository: TaskRepository,
            notification_service: NotificationService,
            window: timedelta,
            publisher: InvalidatePublisher | None = None,
    ):
        """
        Инициализирует сервис тика напоминаний о дедлайне.

        :param task_repository: выборка кандидатов + advisory lock.
        :param notification_service: ``emit`` (без Redis).
        :param window: окно «скоро дедлайн» (default 24h из конфига).
        :param publisher: Redis bus; ``None`` — только запись в PG (тесты).
        """
        self.task_repository = task_repository
        self.notification_service = notification_service
        self.window = window
        self.publisher = publisher

    async def tick(self) -> set[int]:
        """
        Один тик: lock → кандидаты → emit → commit → publish_many.

        При занятом advisory lock тик пропускается (пустой set).
        Ошибки publish обрабатывает bus (лог, не raise).

        :returns: recipient_id с реальной вставкой за этот тик.
        """
        DEADLINE_WORKER_RUNS.inc()
        changed: set[int] = set()
        candidates_count = 0
        async with self.task_repository.transaction() as conn:
            locked, candidates = await self.task_repository.fetch_deadline_reminder_candidates(
                window=self.window,
                conn=conn,
            )
            if not locked:
                logger.info("deadline reminders tick skipped: lock busy")
                return set()

            candidates_count = len(candidates)
            DEADLINE_WORKER_CANDIDATES.inc(amount=candidates_count)
            for candidate in candidates:
                event = build_deadline_reminder_event(
                    task_id=candidate.id,
                    title=candidate.title,
                    due_date=candidate.due_date,
                    recipient_id=candidate.user_id,
                )
                created = await self.notification_service.emit(
                    event=event,
                    conn=conn,
                )
                changed |= created

        logger.info(
            "deadline reminders tick done",
            extra={
                "candidates": candidates_count,
                "created_recipients": sorted(changed),
            },
        )
        if changed and self.publisher is not None:
            await self.publisher.publish_many(user_ids=changed)
        return changed
