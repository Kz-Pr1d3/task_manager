from datetime import datetime
from typing import Annotated

from fastapi import Depends, Query
from fastapi import APIRouter, status, Path

from src.api.dependencies import get_current_user_id
from src.api.responses import BAD_REQUEST, CONFLICT, NOT_FOUND, UNAUTHORIZED, UNPROCESSABLE
from src.models.tasks import (
    Task,
    TaskPage,
    CreateTaskRequest,
    UpdateTaskRequest,
    MoveTaskRequest,
)
from src.services.dependencies import TaskServiceDep

tasks_router = APIRouter(prefix="/tasks", responses=UNAUTHORIZED)

task_id_annotation = Annotated[int, Path(description="ID задачи.")]
list_id_query = Annotated[int, Query(description="ID физического списка.")]


@tasks_router.get(
    "/",
    tags=["tasks"],
    summary="Задачи физического списка (cursor pagination).",
    status_code=status.HTTP_200_OK,
    response_model=TaskPage,
    responses=BAD_REQUEST,
)
async def list_tasks(
        list_id: list_id_query,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: TaskServiceDep,
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
        cursor: int | None = None,
        cursor_created_at: datetime | None = None,
):
    """
    Возвращает страницу задач списка (cursor pagination).

    :param list_id: id физического списка.
    :param user_id: id из access-токена.
    :param service: сервис задач.
    :param limit: размер страницы (1..50).
    :param cursor: id курсора для следующей страницы.
    :param cursor_created_at: created_at курсора (вместе с cursor).
    :returns: страница ``TaskPage``.
    """
    return await service.list_tasks(
        user_id=user_id,
        list_id=list_id,
        limit=limit,
        cursor=cursor,
        cursor_created_at=cursor_created_at,
    )


@tasks_router.post(
    "/",
    tags=["tasks"],
    summary="Создание задачи в списке.",
    status_code=status.HTTP_200_OK,
    response_model=Task,
    responses={**NOT_FOUND, **CONFLICT},
)
async def create_task(
        body: CreateTaskRequest,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: TaskServiceDep,
):
    """
    Создаёт задачу в указанном физическом списке.

    :param body: list_id, title и опциональный due_date.
    :param user_id: id из access-токена.
    :param service: сервис задач.
    :returns: созданная ``Task``.
    """
    return await service.create_task(
        user_id=user_id,
        list_id=body.list_id,
        title=body.title,
        due_date=body.due_date,
    )


@tasks_router.get(
    "/{task_id}",
    tags=["tasks"],
    summary="Получение задачи.",
    status_code=status.HTTP_200_OK,
    response_model=Task,
    responses=NOT_FOUND,
)
async def get_task(
        task_id: task_id_annotation,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: TaskServiceDep,
):
    """
    Возвращает задачу по идентификатору.

    :param task_id: идентификатор задачи.
    :param user_id: id из access-токена.
    :param service: сервис задач.
    :returns: найденная ``Task``.
    """
    return await service.get_task(user_id=user_id, task_id=task_id)


@tasks_router.patch(
    "/{task_id}",
    tags=["tasks"],
    summary="Обновление задачи.",
    status_code=status.HTTP_200_OK,
    response_model=Task,
    responses={**BAD_REQUEST, **NOT_FOUND},
)
async def update_task_info(
        task_id: task_id_annotation,
        info_body: UpdateTaskRequest,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: TaskServiceDep,
):
    """
    Частично обновляет поля задачи (title и др.).

    :param task_id: идентификатор задачи.
    :param info_body: поля для обновления (только переданные).
    :param user_id: id из access-токена.
    :param service: сервис задач.
    :returns: обновлённая ``Task``.
    """
    info = info_body.model_dump(exclude_unset=True)
    return await service.update_task(user_id=user_id, task_id=task_id, info=info)


@tasks_router.post(
    "/{task_id}/move",
    tags=["tasks"],
    summary="Перемещение задачи в другой список.",
    status_code=status.HTTP_200_OK,
    response_model=Task,
    responses={**NOT_FOUND, **CONFLICT},
)
async def move_task(
        task_id: task_id_annotation,
        body: MoveTaskRequest,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: TaskServiceDep,
):
    """
    Перемещает задачу в другой физический список.

    :param task_id: идентификатор задачи.
    :param body: целевой list_id.
    :param user_id: id из access-токена.
    :param service: сервис задач.
    :returns: перемещённая ``Task``.
    """
    return await service.move_task(user_id=user_id, task_id=task_id, list_id=body.list_id)


@tasks_router.post(
    "/{task_id}/complete",
    tags=["tasks"],
    summary="Завершение задачи.",
    status_code=status.HTTP_200_OK,
    response_model=Task,
    responses=NOT_FOUND,
)
async def complete_task(
        task_id: task_id_annotation,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: TaskServiceDep,
):
    """
    Помечает задачу как завершённую.

    :param task_id: идентификатор задачи.
    :param user_id: id из access-токена.
    :param service: сервис задач.
    :returns: завершённая ``Task``.
    """
    return await service.complete_task(user_id=user_id, task_id=task_id)


@tasks_router.post(
    "/{task_id}/trash",
    tags=["tasks"],
    summary="Перемещение задачи в корзину.",
    status_code=status.HTTP_200_OK,
    response_model=Task,
    responses=NOT_FOUND,
)
async def trash_task(
        task_id: task_id_annotation,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: TaskServiceDep,
):
    """
    Перемещает задачу в корзину (soft delete).

    :param task_id: идентификатор задачи.
    :param user_id: id из access-токена.
    :param service: сервис задач.
    :returns: задача в состоянии trash.
    """
    return await service.trash_task(user_id=user_id, task_id=task_id)


@tasks_router.post(
    "/{task_id}/restore",
    tags=["tasks"],
    summary="Восстановление задачи из корзины.",
    status_code=status.HTTP_200_OK,
    response_model=Task,
    responses={**NOT_FOUND, **CONFLICT},
)
async def restore_task(
        task_id: task_id_annotation,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: TaskServiceDep,
):
    """
    Восстанавливает задачу из корзины в список.

    :param task_id: идентификатор задачи.
    :param user_id: id из access-токена.
    :param service: сервис задач.
    :returns: восстановленная ``Task``.
    """
    return await service.restore_task(user_id=user_id, task_id=task_id)


@tasks_router.delete(
    "/{task_id}",
    tags=["tasks"],
    summary="Hard delete задачи (только из корзины).",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**NOT_FOUND, **UNPROCESSABLE},
)
async def hard_delete_task(
        task_id: task_id_annotation,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: TaskServiceDep,
):
    """
    Безвозвратно удаляет задачу из корзины.

    :param task_id: идентификатор задачи.
    :param user_id: id из access-токена.
    :param service: сервис задач.
    """
    await service.hard_delete_task(user_id=user_id, task_id=task_id)
