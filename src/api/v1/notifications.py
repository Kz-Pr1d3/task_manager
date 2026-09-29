from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.api.dependencies import get_current_user_id
from src.api.responses import UNAUTHORIZED, UNPROCESSABLE
from src.models.notification import (
    MarkNotificationsRead,
    MarkNotificationsUnread,
    NotificationMutationResult,
    NotificationPage,
    UnreadCountResponse,
)
from src.services.dependencies import NotificationBusDep, NotificationServiceDep

notifications_router = APIRouter(prefix="/notifications", responses=UNAUTHORIZED)


@notifications_router.get(
    "/",
    tags=["notifications"],
    summary="Список уведомлений текущего пользователя",
    status_code=status.HTTP_200_OK,
    response_model=NotificationPage,
    responses=UNPROCESSABLE,
)
async def list_notifications(
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: NotificationServiceDep,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        before_id: int | None = None,
        unread: bool | None = None,
        category: str | None = None,
        important: bool | None = None,
):
    """
    Возвращает страницу уведомлений (cursor before_id, id DESC).

    :param user_id: id из access-токена.
    :param service: сервис уведомлений.
    :param limit: размер страницы (1..100).
    :param before_id: курсор следующей страницы.
    :param unread: фильтр непрочитанных.
    :param category: фильтр category.
    :param important: фильтр severity=important.
    :returns: ``NotificationPage``.
    """
    return await service.list_notifications(
        recipient_id=user_id,
        limit=limit,
        before_id=before_id,
        unread=unread,
        category=category,
        important=important,
    )


@notifications_router.get(
    "/unread-count",
    tags=["notifications"],
    summary="Счётчики непрочитанных уведомлений",
    status_code=status.HTTP_200_OK,
    response_model=UnreadCountResponse,
)
async def get_unread_count(
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: NotificationServiceDep,
):
    """
    Возвращает total / important / by_category непрочитанных.

    :param user_id: id из access-токена.
    :param service: сервис уведомлений.
    :returns: ``UnreadCountResponse``.
    """
    return await service.get_unread_counts(recipient_id=user_id)


@notifications_router.post(
    "/read",
    tags=["notifications"],
    summary="Отметить уведомления прочитанными",
    status_code=status.HTTP_200_OK,
    response_model=NotificationMutationResult,
    responses=UNPROCESSABLE,
)
async def mark_notifications_read(
        body: MarkNotificationsRead,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: NotificationServiceDep,
        bus: NotificationBusDep,
):
    """
    Отмечает выбранные или все уведомления прочитанными.

    После успешного обновления — ``notification.invalidate`` текущему user.

    :param body: ids XOR all=true (+ optional category).
    :param user_id: id из access-токена.
    :param service: сервис уведомлений.
    :param bus: Redis bus invalidate.
    :returns: id обновлённых строк.
    """
    result = await service.mark_read(recipient_id=user_id, body=body)
    if result.updated_ids:
        await bus.publish_many(user_ids={user_id})
    return result


@notifications_router.post(
    "/unread",
    tags=["notifications"],
    summary="Вернуть уведомления в непрочитанные",
    status_code=status.HTTP_200_OK,
    response_model=NotificationMutationResult,
    responses=UNPROCESSABLE,
)
async def mark_notifications_unread(
        body: MarkNotificationsUnread,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: NotificationServiceDep,
        bus: NotificationBusDep,
):
    """
    Сбрасывает read_at у выбранных уведомлений.

    После успешного обновления — ``notification.invalidate`` текущему user.

    :param body: список ids.
    :param user_id: id из access-токена.
    :param service: сервис уведомлений.
    :param bus: Redis bus invalidate.
    :returns: id обновлённых строк.
    """
    result = await service.mark_unread(recipient_id=user_id, ids=body.ids)
    if result.updated_ids:
        await bus.publish_many(user_ids={user_id})
    return result
