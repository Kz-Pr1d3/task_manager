from unittest.mock import MagicMock, AsyncMock

from src.models.auth import SignUpRequest
from src.services.auth import AuthService

user_repo = AsyncMock(return_value=1)
redis = AsyncMock(return_value=True)


async def test__create_user__success():
    service = AuthService(repository=user_repo, redis_client=redis)
    cred = SignUpRequest(email="test2@test.com", password="test")
    token = await service.create_user(credentials=cred)
    assert token
