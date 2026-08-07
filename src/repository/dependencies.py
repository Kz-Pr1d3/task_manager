from typing import Annotated

from fastapi import Depends

from src.core.database import db
from src.repository.list import ListRepository
from src.repository.task import TaskRepository
from src.repository.user import UserRepository


def get_user_repo() -> UserRepository:
    return UserRepository(pool=db.pool)


def get_list_repo() -> ListRepository:
    return ListRepository(pool=db.pool)


def get_task_repo() -> TaskRepository:
    return TaskRepository(pool=db.pool)


UserRepoDep = Annotated[UserRepository, Depends(get_user_repo)]
ListRepoDep = Annotated[ListRepository, Depends(get_list_repo)]
TaskRepoDep = Annotated[TaskRepository, Depends(get_task_repo)]
