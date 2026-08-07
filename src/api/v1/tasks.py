from datetime import datetime
from typing import Annotated, Optional

from fastapi import Depends, Query
from fastapi import APIRouter, status, Path

from src.api.dependencies import get_current_user_id
from src.models.tasks import (
    Task,
    TaskPage,
    CreateTaskRequest,
    UpdateTaskRequest,
    MoveTaskRequest,
    CreateSubtaskRequest,
)
from src.services.dependencies import TaskServiceDep

tasks_router = APIRouter(prefix="/tasks")

task_id_annotation = Annotated[int, Path(description="ID задачи.")]
list_id_query = Annotated[int, Query(description="ID физического списка.")]


@tasks_router.get(
    "/",
    tags=["tasks"],
    summary="Задачи физического списка (cursor pagination).",
    status_code=status.HTTP_200_OK,
    response_model=TaskPage,
)
async def list_tasks(
        list_id: list_id_query,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: TaskServiceDep,
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
        cursor: Optional[int] = None,
        cursor_created_at: Optional[datetime] = None,
):
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
)
async def create_task(
        body: CreateTaskRequest,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: TaskServiceDep,
):
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
)
async def get_task(
        task_id: task_id_annotation,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: TaskServiceDep,
):
    return await service.get_task(user_id=user_id, task_id=task_id)


@tasks_router.patch(
    "/{task_id}",
    tags=["tasks"],
    summary="Обновление задачи.",
    status_code=status.HTTP_200_OK,
    response_model=Task,
)
async def update_task_info(
        task_id: task_id_annotation,
        info_body: UpdateTaskRequest,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: TaskServiceDep,
):
    info = info_body.model_dump(exclude_unset=True)
    return await service.update_task(user_id=user_id, task_id=task_id, info=info)


@tasks_router.post(
    "/{task_id}/move",
    tags=["tasks"],
    summary="Перемещение задачи в другой список.",
    status_code=status.HTTP_200_OK,
    response_model=Task,
)
async def move_task(
        task_id: task_id_annotation,
        body: MoveTaskRequest,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: TaskServiceDep,
):
    return await service.move_task(user_id=user_id, task_id=task_id, list_id=body.list_id)


@tasks_router.post(
    "/{task_id}/complete",
    tags=["tasks"],
    summary="Завершение задачи (с каскадом подзадач).",
    status_code=status.HTTP_200_OK,
    response_model=Task,
)
async def complete_task(
        task_id: task_id_annotation,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: TaskServiceDep,
):
    return await service.complete_task(user_id=user_id, task_id=task_id)


@tasks_router.post(
    "/{task_id}/trash",
    tags=["tasks"],
    summary="Перемещение задачи в корзину.",
    status_code=status.HTTP_200_OK,
    response_model=Task,
)
async def trash_task(
        task_id: task_id_annotation,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: TaskServiceDep,
):
    return await service.trash_task(user_id=user_id, task_id=task_id)


@tasks_router.post(
    "/{task_id}/restore",
    tags=["tasks"],
    summary="Восстановление задачи из корзины.",
    status_code=status.HTTP_200_OK,
    response_model=Task,
)
async def restore_task(
        task_id: task_id_annotation,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: TaskServiceDep,
):
    return await service.restore_task(user_id=user_id, task_id=task_id)


@tasks_router.delete(
    "/{task_id}",
    tags=["tasks"],
    summary="Hard delete задачи (только из корзины).",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def hard_delete_task(
        task_id: task_id_annotation,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: TaskServiceDep,
):
    await service.hard_delete_task(user_id=user_id, task_id=task_id)


@tasks_router.get(
    "/{task_id}/subtasks",
    tags=["tasks"],
    summary="Список подзадач.",
    status_code=status.HTTP_200_OK,
    response_model=list[Task],
)
async def get_subtasks(
        task_id: task_id_annotation,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: TaskServiceDep,
):
    return await service.get_subtasks(user_id=user_id, task_id=task_id)


@tasks_router.post(
    "/{task_id}/subtasks",
    tags=["tasks"],
    summary="Создание подзадачи.",
    status_code=status.HTTP_200_OK,
    response_model=Task,
)
async def create_subtask(
        task_id: task_id_annotation,
        body: CreateSubtaskRequest,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: TaskServiceDep,
):
    return await service.create_subtask(user_id=user_id, parent_id=task_id, title=body.title)
