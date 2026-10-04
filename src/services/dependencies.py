from typing import Annotated

import redis.asyncio as redis
from fastapi import Depends, Request

from src.core.cache import get_redis
from src.core.redis_notification_bus import RedisNotificationBus
from src.core.s3 import S3Storage, get_s3_storage
from src.repository.dependencies import (
    AttachmentRepoDep,
    UserRepoDep,
    ListRepoDep,
    TaskRepoDep,
    NotificationRepoDep,
)
from src.services.attachment import AttachmentService
from src.services.auth import AuthService
from src.services.list import ListService
from src.services.notification import NotificationService
from src.services.task import TaskService


def get_auth_service(
        repo: UserRepoDep,
        redis_conn: Annotated[redis.Redis, Depends(get_redis)],
) -> AuthService:
    """
    Фабрика FastAPI-зависимости AuthService.

    :param repo: репозиторий пользователей.
    :param redis_conn: клиент Redis из DI.
    :returns: экземпляр ``AuthService``.
    """
    return AuthService(repository=repo, redis_client=redis_conn)


def get_list_service(repo: ListRepoDep) -> ListService:
    """
    Фабрика FastAPI-зависимости ListService.

    :param repo: репозиторий списков.
    :returns: экземпляр ``ListService``.
    """
    return ListService(repository=repo)


def get_task_service(repo: TaskRepoDep) -> TaskService:
    """
    Фабрика FastAPI-зависимости TaskService.

    :param repo: репозиторий задач.
    :returns: экземпляр ``TaskService``.
    """
    return TaskService(repository=repo)


def get_notification_service(repo: NotificationRepoDep) -> NotificationService:
    """
    Фабрика FastAPI-зависимости NotificationService.

    :param repo: репозиторий уведомлений.
    :returns: экземпляр ``NotificationService``.
    """
    return NotificationService(repository=repo)


def get_s3_storage_dep() -> S3Storage:
    """
    FastAPI-зависимость глобального ``S3Storage`` (lifespan).

    :returns: экземпляр ``S3Storage``.
    """
    return get_s3_storage()


def get_attachment_service(
        repo: AttachmentRepoDep,
        s3: Annotated[S3Storage, Depends(get_s3_storage_dep)],
) -> AttachmentService:
    """
    Фабрика FastAPI-зависимости AttachmentService.

    :param repo: репозиторий вложений.
    :param s3: хранилище S3/MinIO.
    :returns: экземпляр ``AttachmentService``.
    """
    return AttachmentService(repository=repo, s3=s3)


def get_notification_bus(request: Request) -> RedisNotificationBus:
    """
    Достаёт ``RedisNotificationBus`` из ``app.state`` (lifespan).

    :param request: текущий HTTP-запрос.
    :returns: bus текущего процесса.
    """
    return request.app.state.notification_bus


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
ListServiceDep = Annotated[ListService, Depends(get_list_service)]
TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
NotificationServiceDep = Annotated[NotificationService, Depends(get_notification_service)]
AttachmentServiceDep = Annotated[AttachmentService, Depends(get_attachment_service)]
NotificationBusDep = Annotated[RedisNotificationBus, Depends(get_notification_bus)]
