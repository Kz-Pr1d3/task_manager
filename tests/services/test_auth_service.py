from unittest.mock import MagicMock

from src.models.auth import SignUpRequest
from src.services.auth import AuthService

user_repo = MagicMock()


async def test__create_user__success():
    service = AuthService(repository=user_repo)
    cred = SignUpRequest(email="test2@test.com", password="test")
    token = await service.create_user(credentials=cred)
    assert token
