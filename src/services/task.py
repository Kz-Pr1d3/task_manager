from datetime import datetime
from typing import Any, Optional

from src.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
    UnprocessableEntityException,
)
from src.models.tasks import Task, TaskPage
from src.repository.task import TaskRepository

INBOX_LIST_ID = 1


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
        task = await self.repository.get_task(user_id=user_id, task_id=task_id)
        if task is None or task.deleted_at is not None:
            raise NotFoundException()

        if task.parent_id is not None:
            raise UnprocessableEntityException(
                detail="Cannot move a subtask; move the parent task instead"
            )

        if task.list_id == list_id:
            return task

        moved = await self.repository.move_task(
            user_id=user_id,
            task_id=task_id,
            list_id=list_id,
            limit=self.tasks_per_list,
        )
        if moved is not None:
            return moved

        if not await self.repository.is_writable_list(user_id=user_id, list_id=list_id):
            raise NotFoundException()

        raise ConflictException(detail="The limit for tasks in this list has been reached")

    async def complete_task(self, user_id: int, task_id: int) -> Task:
        """Завершает задачу с каскадом подзадач.

        :param user_id: владелец.
        :param task_id: задача.
        :returns: обновлённая задача.
        :raises NotFoundException: задача не найдена / чужая.
        """
        task = await self.repository.complete_task(user_id=user_id, task_id=task_id)
        if not task:
            raise NotFoundException()
        return task

    async def trash_task(self, user_id: int, task_id: int) -> Task:
        """Перемещает задачу в корзину (soft delete + каскад).

        :param user_id: владелец.
        :param task_id: задача.
        :returns: задача с deleted_at.
        :raises NotFoundException: задача не найдена / чужая.
        """
        task = await self.repository.trash_task(user_id=user_id, task_id=task_id)
        if not task:
            raise NotFoundException()
        return task

    async def restore_task(self, user_id: int, task_id: int) -> Task:
        """Восстанавливает задачу из корзины в previous_list_id или Inbox.

        :param user_id: владелец.
        :param task_id: задача в корзине.
        :returns: восстановленная задача.
        :raises NotFoundException: нет задачи или не в корзине.
        :raises ConflictException: лимит 100 в целевом списке.
        """
        task = await self.repository.get_task(user_id=user_id, task_id=task_id)
        if not task or task.deleted_at is None:
            raise NotFoundException()

        target_list_id = task.previous_list_id
        if target_list_id is None or not await self.repository.is_writable_list(
            user_id=user_id,
            list_id=target_list_id,
        ):
            target_list_id = INBOX_LIST_ID

        restored = await self.repository.restore_task(
            user_id=user_id,
            task_id=task_id,
            list_id=target_list_id,
            limit=self.tasks_per_list,
        )
        if restored is not None:
            return restored

        raise ConflictException(detail="The limit for tasks in this list has been reached")

    async def hard_delete_task(self, user_id: int, task_id: int) -> None:
        """Безвозвратно удаляет задачу из корзины.

        :param user_id: владелец.
        :param task_id: задача.
        :raises NotFoundException: задача не найдена / чужая.
        :raises UnprocessableEntityException: задача не в корзине.
        """
        task = await self.repository.get_task(user_id=user_id, task_id=task_id)
        if not task:
            raise NotFoundException()
        if task.deleted_at is None:
            raise UnprocessableEntityException(detail="Task is not in trash")

        deleted = await self.repository.hard_delete_task(user_id=user_id, task_id=task_id)
        if not deleted:
            raise NotFoundException()

    async def get_subtasks(self, user_id: int, task_id: int) -> list[Task]:
        """Список подзадач; 404 если родителя нет.

        :param user_id: владелец.
        :param task_id: id родительской задачи.
        :returns: неудалённые дети родителя.
        :raises NotFoundException: родитель не найден / чужой.
        """
        parent = await self.repository.get_task(user_id=user_id, task_id=task_id)
        if not parent:
            raise NotFoundException()

        return await self.repository.get_subtasks(user_id=user_id, parent_id=task_id)

    async def create_subtask(self, user_id: int, parent_id: int, title: str) -> Task:
        """Создаёт подзадачу с list_id родителя и due_date=NULL.

        :param user_id: владелец.
        :param parent_id: id родительской задачи.
        :param title: заголовок подзадачи.
        :returns: созданная подзадача.
        :raises NotFoundException: родителя нет, он удалён или список недоступен.
        :raises ConflictException: лимит задач в списке родителя.
        """
        parent = await self.repository.get_task(user_id=user_id, task_id=parent_id)
        if not parent or parent.deleted_at is not None:
            raise NotFoundException()

        task = await self.repository.create_task(
            user_id=user_id,
            list_id=parent.list_id,
            title=title,
            due_date=None,
            parent_id=parent_id,
            limit=self.tasks_per_list,
        )
        if task is not None:
            return task

        if not await self.repository.is_writable_list(
            user_id=user_id, list_id=parent.list_id
        ):
            raise NotFoundException()

        raise ConflictException(detail="The limit for tasks in this list has been reached")
