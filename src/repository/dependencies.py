from typing import Annotated

from fastapi import Depends

from src.core.database import db
from src.repository.user import UserRepository


def get_user_repo() -> UserRepository:
    return UserRepository(pool=db.pool)


UserRepoDep = Annotated[UserRepository, Depends(get_user_repo)]
