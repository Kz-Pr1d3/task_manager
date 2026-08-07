from typing import Annotated

import redis.asyncio as redis
from fastapi import Depends

from src.core.cache import get_redis
from src.repository.dependencies import UserRepoDep, ListRepoDep, TaskRepoDep
from src.services.auth import AuthService
from src.services.list import ListService
from src.services.task import TaskService


def get_auth_service(
        repo: UserRepoDep,
        redis_conn: Annotated[redis.Redis, Depends(get_redis)],
) -> AuthService:
    return AuthService(repository=repo, redis_client=redis_conn)


def get_list_service(repo: ListRepoDep) -> ListService:
    return ListService(repository=repo)


def get_task_service(repo: TaskRepoDep) -> TaskService:
    return TaskService(repository=repo)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
ListServiceDep = Annotated[ListService, Depends(get_list_service)]
TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
