from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.core.security import Security

security_scheme = HTTPBearer()


# ── Auth dependency ──────────────────────────────────────


async def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
) -> int:
    """
    Извлекает user_id из Bearer access-токена.

    :param credentials: Authorization: Bearer credentials.
    :returns: идентификатор текущего пользователя.
    :raises UnauthorizedException: если токен невалиден или истёк.
    """
    return Security.decode_access_token(credentials.credentials)
