from typing import Annotated

from fastapi import Depends

from src.repository.dependencies import UserRepoDep
from src.services.auth import AuthService


def get_auth_service(repo: UserRepoDep) -> AuthService:
    return AuthService(repo)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
