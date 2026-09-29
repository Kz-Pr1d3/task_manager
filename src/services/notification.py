import logging

from asyncpg import Connection

from src.core.notification_metrics import NOTIFICATIONS_CREATED
from src.models.notification import (
    MarkNotificationsRead,
    NotificationEvent,
    NotificationMutationResult,
    NotificationPage,
    UnreadCountResponse,
)
from src.repository.notification import NotificationRepository

logger = logging.getLogger(__name__)


class NotificationService:
    """HTTP-операции и emit уведомлений (без Redis publish)."""

    def __init__(self, repository: NotificationRepository):
        """
        Инициализирует сервис уведомлений.

        :param repository: репозиторий уведомлений.
        """
        self.repository = repository

    async def emit(
            self,
            event: NotificationEvent,
            conn: Connection | None = None,
    ) -> set[int]:
        """
        Создаёт уведомления через repository; commit не делает.

        Транзакцией владеет вызывающий код (worker / будущий TaskService).
        Publish в Redis — снаружи, после commit.

        :param event: контракт доменного события уведомления.
        :param conn: соединение транзакции вызывающего кода (опционально).
        :returns: recipient_id с реальной вставкой (для последующего publish).
        """
        created = await self.repository.create_for_recipients(
            event=event,
            conn=conn,
        )
        if created:
            NOTIFICATIONS_CREATED.labels(type=event.type).inc(amount=len(created))
        logger.info(
            "notification emit",
            extra={
                "event_id": event.event_id,
                "type": event.type,
                "created_recipients": sorted(created),
                "requested_recipients": sorted(event.recipient_ids),
            },
        )
        return created

    async def list_notifications(
            self,
            recipient_id: int,
            limit: int,
            before_id: int | None = None,
            unread: bool | None = None,
            category: str | None = None,
            important: bool | None = None,
    ) -> NotificationPage:
        """
        Страница уведомлений с cursor before_id (id DESC).

        :param recipient_id: id из access-токена.
        :param limit: размер страницы (1..100).
        :param before_id: курсор следующей страницы.
        :param unread: фильтр непрочитанных.
        :param category: фильтр category.
        :param important: фильтр severity=important.
        :returns: ``NotificationPage``.
        """
        rows = await self.repository.list_notifications(
            recipient_id=recipient_id,
            limit=limit + 1,
            before_id=before_id,
            unread=unread,
            category=category,
            important=important,
        )
        has_more = len(rows) > limit
        items = rows[:limit]
        next_before_id = items[-1].id if has_more and items else None
        return NotificationPage(
            items=items,
            has_more=has_more,
            next_before_id=next_before_id,
            limit=limit,
        )

    async def get_unread_counts(self, recipient_id: int) -> UnreadCountResponse:
        """
        Счётчики непрочитанных текущего пользователя.

        :param recipient_id: id из access-токена.
        :returns: ``UnreadCountResponse``.
        """
        return await self.repository.get_unread_counts(recipient_id=recipient_id)

    async def mark_read(
            self,
            recipient_id: int,
            body: MarkNotificationsRead,
    ) -> NotificationMutationResult:
        """
        Отмечает уведомления прочитанными (ids или all).

        Publish invalidate — на вызывающем после успешного результата.

        :param recipient_id: id из access-токена.
        :param body: ids XOR all=true (+ optional category).
        :returns: id обновлённых строк.
        """
        if body.all:
            updated_ids = await self.repository.mark_read_all(
                recipient_id=recipient_id,
                category=body.category,
            )
        else:
            updated_ids = await self.repository.mark_read(
                recipient_id=recipient_id,
                ids=body.ids,
            )
        return NotificationMutationResult(updated_ids=updated_ids)

    async def mark_unread(
            self,
            recipient_id: int,
            ids: list[int],
    ) -> NotificationMutationResult:
        """
        Возвращает уведомления в непрочитанные.

        Publish invalidate — на вызывающем после успешного результата.

        :param recipient_id: id из access-токена.
        :param ids: id уведомлений.
        :returns: id обновлённых строк.
        """
        updated_ids = await self.repository.mark_unread(
            recipient_id=recipient_id,
            ids=ids,
        )
        return NotificationMutationResult(updated_ids=updated_ids)
