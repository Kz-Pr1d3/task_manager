from typing import Annotated

import redis.asyncio as redis
from fastapi import Depends

from src.core.cache import get_redis
from src.repository.dependencies import UserRepoDep
from src.services.auth import AuthService


def get_auth_service(
        repo: UserRepoDep,
        redis_conn: Annotated[redis.Redis, Depends(get_redis)],
) -> AuthService:
    return AuthService(repository=repo, redis_client=redis_conn)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
