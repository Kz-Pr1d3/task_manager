from datetime import datetime
from typing import Any

from src.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
    UnprocessableEntityException,
)
from src.models.enums import TaskWriteStatus
from src.models.tasks import Task, TaskPage
from src.repository.task import TaskRepository

INBOX_LIST_ID = 1
_TASK_LIMIT_DETAIL = "The limit for tasks in this list has been reached"


class TaskService:
    """Сервис задач: оркестрация repo и доменных ошибок."""

    def __init__(self, repository: TaskRepository):
        """
        Инициализирует сервис задач.

        :param repository: репозиторий задач.
        """
        self.repository = repository
        self.tasks_per_list = 100

    async def get_task(self, user_id: int, task_id: int) -> Task:
        """
        Возвращает задачу пользователя по id.

        :param user_id: владелец задачи.
        :param task_id: идентификатор задачи.
        :returns: найденная задача.
        :raises NotFoundException: задача не найдена / чужая.
        """
        task = await self.repository.get_task(user_id=user_id, task_id=task_id)
        if not task:
            raise NotFoundException()

        return task

    async def list_tasks(
            self,
            user_id: int,
            list_id: int,
            limit: int = 20,
            cursor: int | None = None,
            cursor_created_at: datetime | None = None,
    ) -> TaskPage:
        """
        Страница задач физического списка.

        Курсор и companion обязательны парой. has_more / next_cursor
        через limit+1 (как notifications), без COUNT.
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

        # limit+1: точный has_more без ложного true на последней полной странице
        rows = await self.repository.list_tasks(
            user_id=user_id,
            list_id=list_id,
            limit=limit + 1,
            cursor=cursor,
            cursor_created_at=cursor_created_at,
        )
        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = items[-1].id if has_more and items else None
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
            due_date: datetime | None = None,
    ) -> Task:
        """
        Создаёт задачу в списке с проверкой лимита.

        :param user_id: владелец задачи.
        :param list_id: целевой список.
        :param title: заголовок задачи.
        :param due_date: опциональный дедлайн.
        :returns: созданная задача.
        :raises NotFoundException: список недоступен.
        :raises ConflictException: достигнут лимит задач в списке.
        """
        result = await self.repository.create_task(
            user_id=user_id,
            list_id=list_id,
            title=title,
            due_date=due_date,
            limit=self.tasks_per_list,
        )
        if result.status is TaskWriteStatus.ok:
            return result.task
        if result.status is TaskWriteStatus.forbidden:
            raise NotFoundException()
        raise ConflictException(detail=_TASK_LIMIT_DETAIL)

    async def update_task(self, user_id: int, task_id: int, info: dict[str, Any]) -> Task:
        """
        Частично обновляет поля задачи.

        :param user_id: владелец задачи.
        :param task_id: идентификатор задачи.
        :param info: поля для обновления (непустой dict).
        :returns: обновлённая задача.
        :raises BadRequestException: пустой набор полей.
        :raises NotFoundException: задача не найдена / чужая.
        """
        if not info:
            raise BadRequestException(detail="No fields to update")

        task = await self.repository.update_task_info(user_id=user_id, task_id=task_id, info=info)
        if not task:
            raise NotFoundException()

        return task

    async def move_task(self, user_id: int, task_id: int, list_id: int) -> Task:
        """
        Перемещает задачу в другой список.

        :param user_id: владелец задачи.
        :param task_id: идентификатор задачи.
        :param list_id: целевой список.
        :returns: задача после перемещения.
        :raises NotFoundException: задача/список недоступны.
        :raises ConflictException: лимит задач в целевом списке.
        """
        result = await self.repository.move_task(
            user_id=user_id,
            task_id=task_id,
            list_id=list_id,
            limit=self.tasks_per_list,
        )
        if result.status is TaskWriteStatus.ok:
            return result.task
        if result.status in (TaskWriteStatus.not_found, TaskWriteStatus.forbidden):
            raise NotFoundException()
        raise ConflictException(detail=_TASK_LIMIT_DETAIL)

    async def complete_task(self, user_id: int, task_id: int) -> Task:
        """
        Помечает задачу как завершённую.

        :param user_id: владелец задачи.
        :param task_id: идентификатор задачи.
        :returns: обновлённая задача.
        :raises NotFoundException: задача не найдена / чужая.
        """
        task = await self.repository.complete_task(user_id=user_id, task_id=task_id)
        if not task:
            raise NotFoundException()
        return task

    async def trash_task(self, user_id: int, task_id: int) -> Task:
        """
        Перемещает задачу в корзину (soft delete).

        :param user_id: владелец задачи.
        :param task_id: идентификатор задачи.
        :returns: задача с deleted_at.
        :raises NotFoundException: задача не найдена / чужая.
        """
        task = await self.repository.trash_task(user_id=user_id, task_id=task_id)
        if not task:
            raise NotFoundException()
        return task

    async def restore_task(self, user_id: int, task_id: int) -> Task:
        """
        Восстанавливает задачу из корзины в previous_list_id.

        Fallback в Inbox, если previous_list недоступен.
        :param user_id: владелец задачи.
        :param task_id: задача в корзине.
        :returns: восстановленная задача.
        :raises NotFoundException: нет задачи или не в корзине.
        :raises ConflictException: лимит 100 в целевом списке.
        """
        task = await self.repository.get_task(user_id=user_id, task_id=task_id)
        if not task or task.deleted_at is None:
            raise NotFoundException()

        target_list_id = task.previous_list_id or INBOX_LIST_ID
        result = await self.repository.restore_task(
            user_id=user_id,
            task_id=task_id,
            list_id=target_list_id,
            limit=self.tasks_per_list,
        )
        if result.status is TaskWriteStatus.ok:
            return result.task

        if result.status is TaskWriteStatus.forbidden and target_list_id != INBOX_LIST_ID:
            result = await self.repository.restore_task(
                user_id=user_id,
                task_id=task_id,
                list_id=INBOX_LIST_ID,
                limit=self.tasks_per_list,
            )
            if result.status is TaskWriteStatus.ok:
                return result.task

        if result.status is TaskWriteStatus.limit:
            raise ConflictException(detail=_TASK_LIMIT_DETAIL)
        raise NotFoundException()

    async def hard_delete_task(self, user_id: int, task_id: int) -> None:
        """
        Безвозвратно удаляет задачу из корзины.

        :param user_id: владелец задачи.
        :param task_id: идентификатор задачи.
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
