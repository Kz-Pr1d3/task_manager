from typing import Annotated

from fastapi import Depends

from src.core.database import db
from src.repository.list import ListRepository
from src.repository.notification import NotificationRepository
from src.repository.task import TaskRepository
from src.repository.user import UserRepository


def get_user_repo() -> UserRepository:
    """
    Фабрика FastAPI-зависимости UserRepository.

    :returns: экземпляр ``UserRepository`` на общем пуле.
    """
    return UserRepository(pool=db.pool)


def get_list_repo() -> ListRepository:
    """
    Фабрика FastAPI-зависимости ListRepository.

    :returns: экземпляр ``ListRepository`` на общем пуле.
    """
    return ListRepository(pool=db.pool)


def get_task_repo() -> TaskRepository:
    """
    Фабрика FastAPI-зависимости TaskRepository.

    :returns: экземпляр ``TaskRepository`` на общем пуле.
    """
    return TaskRepository(pool=db.pool)


def get_notification_repo() -> NotificationRepository:
    """
    Фабрика FastAPI-зависимости NotificationRepository.

    :returns: экземпляр ``NotificationRepository`` на общем пуле.
    """
    return NotificationRepository(pool=db.pool)


UserRepoDep = Annotated[UserRepository, Depends(get_user_repo)]
ListRepoDep = Annotated[ListRepository, Depends(get_list_repo)]
TaskRepoDep = Annotated[TaskRepository, Depends(get_task_repo)]
NotificationRepoDep = Annotated[NotificationRepository, Depends(get_notification_repo)]
