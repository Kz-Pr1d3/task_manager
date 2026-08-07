from datetime import datetime
from typing import Any, Optional

from src.core.exceptions import BadRequestException, ConflictException, NotFoundException
from src.models.tasks import Task, TaskPage
from src.repository.task import TaskRepository


class TaskService:
    def __init__(self, repository: TaskRepository):
        self.repository = repository
        self.tasks_per_list = 100

    async def get_task(self, user_id: int, task_id: int) -> Task:
        task = await self.repository.get_task(user_id=user_id, task_id=task_id)
        if not task:
            raise NotFoundException()

        return task

    async def list_tasks(
            self,
            user_id: int,
            list_id: int,
            limit: int = 20,
            cursor: Optional[int] = None,
            cursor_created_at: Optional[datetime] = None,
    ) -> TaskPage:
        """Страница корневых задач физического списка.

        Курсор и companion обязательны парой. has_more / next_cursor
        считаются по факту длины ответа (не COUNT).
        :param user_id: владелец.
        :param list_id: физический список.
        :param limit: размер страницы.
        :param cursor: id с предыдущей страницы.
        :param cursor_created_at: companion к cursor.
        :returns: TaskPage с items и курсором следующей страницы.
        :raises BadRequestException: cursor без companion или наоборот.
        """
        if (cursor is None) != (cursor_created_at is None):
            raise BadRequestException(
                detail="cursor and cursor_created_at must be provided together"
            )

        items = await self.repository.list_tasks(
            user_id=user_id,
            list_id=list_id,
            limit=limit,
            cursor=cursor,
            cursor_created_at=cursor_created_at,
        )
        has_more = len(items) == limit
        next_cursor = items[-1].id if has_more else None
        return TaskPage(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            limit=limit,
        )

    async def create_task(
            self,
            user_id: int,
            list_id: int,
            title: str,
            due_date: Optional[datetime] = None,
    ) -> Task:
        task = await self.repository.create_task(
            user_id=user_id,
            list_id=list_id,
            title=title,
            due_date=due_date,
            limit=self.tasks_per_list,
        )
        if task is not None:
            return task

        if not await self.repository.is_writable_list(user_id=user_id, list_id=list_id):
            raise NotFoundException()

        raise ConflictException(detail="The limit for tasks in this list has been reached")

    async def update_task(self, user_id: int, task_id: int, info: dict[str, Any]) -> Task:
        if not info:
            raise BadRequestException(detail="No fields to update")

        task = await self.repository.update_task_info(user_id=user_id, task_id=task_id, info=info)
        if not task:
            raise NotFoundException()

        return task

    async def move_task(self, user_id: int, task_id: int, list_id: int) -> Task:
        ...

    async def complete_task(self, user_id: int, task_id: int) -> Task:
        ...

    async def trash_task(self, user_id: int, task_id: int) -> Task:
        ...

    async def restore_task(self, user_id: int, task_id: int) -> Task:
        ...

    async def hard_delete_task(self, user_id: int, task_id: int) -> None:
        ...

    async def get_subtasks(self, user_id: int, task_id: int) -> list[Task]:
        ...

    async def create_subtask(self, user_id: int, parent_id: int, title: str) -> Task:
        ...
