import redis.asyncio as redis
from src.core.exceptions import UnauthorizedException
from src.core.security import Security, hash_password, verify_password
from src.models.auth import SignInRequest, SignUpRequest, TokenResponse
from src.models.user import User
from src.repository.user import UserRepository


class AuthService:
    """Сервис регистрации, входа и обновления токенов."""

    def __init__(self, repository: UserRepository, redis_client: redis.Redis):
        """
        Инициализирует сервис аутентификации.

        :param repository: репозиторий пользователей.
        :param redis_client: клиент Redis для refresh-токенов.
        """
        self.repository = repository
        self.redis = redis_client

    async def create_user(self, credentials: SignUpRequest) -> TokenResponse:
        """
        Регистрирует пользователя и выдаёт пару токенов.

        :param credentials: email и пароль для регистрации.
        :returns: ``TokenResponse`` с access и refresh токенами.
        """
        hashed_password = hash_password(credentials.password)
        user = await self.repository.create(
            email=credentials.email,
            password=hashed_password,
        )
        access_token, refresh_token = Security.create_tokens(user_id=user.id)
        await Security.store_refresh_token(
            user_id=user.id,
            token=refresh_token,
            redis_client=self.redis,
        )

        return TokenResponse(access_token=access_token, refresh_token=refresh_token)

    async def sign_in(self, credentials: SignInRequest) -> TokenResponse:
        """
        Аутентифицирует пользователя по email и паролю.

        :param credentials: email и пароль для входа.
        :returns: ``TokenResponse`` с access и refresh токенами.
        :raises UnauthorizedException: при неверных учётных данных.
        """
        user: User = await self.repository.get_by_email(email=credentials.email)
        if not user:
            raise UnauthorizedException(detail="Invalid credentials")

        if not verify_password(plain=credentials.password, hashed=user.password):
            raise UnauthorizedException(detail="Invalid credentials")

        access_token, refresh_token = Security.create_tokens(user_id=user.id)
        await Security.store_refresh_token(
            user_id=user.id,
            token=refresh_token,
            redis_client=self.redis,
        )

        return TokenResponse(access_token=access_token, refresh_token=refresh_token)

    async def refresh(self, refresh_token: str) -> TokenResponse:
        """
        Обменивает refresh-токен на новую пару токенов.

        :param refresh_token: действующий refresh JWT.
        :returns: новая пара access и refresh токенов.
        :raises UnauthorizedException: если токен невалиден или отозван.
        """
        user_id = await Security.decode_refresh_token(token=refresh_token, redis_client=self.redis)

        access_token, refresh_token = Security.create_tokens(user_id=user_id)
        await Security.store_refresh_token(
            user_id=user_id,
            token=refresh_token,
            redis_client=self.redis,
        )

        return TokenResponse(access_token=access_token, refresh_token=refresh_token)

    async def logout(self, refresh_token: str) -> None:
        """
        Отзывает refresh-токен (logout пользователя).

        :param refresh_token: refresh JWT для отзыва.
        :raises UnauthorizedException: если токен невалиден.
        """
        await Security.revoke_refresh_token(token=refresh_token, redis_client=self.redis)
