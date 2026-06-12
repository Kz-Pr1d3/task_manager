from fastapi import HTTPException, status

from src.core.security import Security, hash_password, verify_password
from src.models.auth import SignInRequest, SignUpRequest, TokenResponse
from src.models.user import User
from src.repository.user import UserRepository


class AuthService:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    async def create_user(self, credentials: SignUpRequest) -> TokenResponse:
        hashed_password = hash_password(credentials.password)
        user = await self.repository.create(
            email=credentials.email,
            password=hashed_password,
        )
        access_token, refresh_token = await Security.create_tokens(user_id=user.id)
        return TokenResponse(access_token=access_token, refresh_token=refresh_token)

    async def sign_in(self, credentials: SignInRequest) -> TokenResponse:
        user: User = await self.repository.get_by_email(email=credentials.email)
        if not user:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

        if not verify_password(plain=credentials.password, hashed=user.password):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

        access_token, refresh_token = await Security.create_tokens(user_id=user.id)
        return TokenResponse(access_token=access_token, refresh_token=refresh_token)

    async def refresh(self, refresh_token: str) -> TokenResponse:
        user_id = await Security.decode_refresh_token(refresh_token)

        access_token, refresh_token = await Security.create_tokens(user_id=user_id)
        return TokenResponse(access_token=access_token, refresh_token=refresh_token)
