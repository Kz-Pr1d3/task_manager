import datetime as dt
import uuid

import jwt
import redis.asyncio as redis
from passlib.context import CryptContext

from src.core.exceptions import UnauthorizedException
from src.core.keys import Keys

pwd_context = CryptContext(
    schemes=["argon2"],
    argon2__memory_cost=131072,
    argon2__parallelism=4,
    argon2__time_cost=3,
)

ALGORITHM = "RS256"
ACCESS_TOKEN_EXPIRE_HOURS = 12
REFRESH_TOKEN_EXPIRE_HOURS = ACCESS_TOKEN_EXPIRE_HOURS * 7


def hash_password(password: str) -> str:
    """
    Хэширует пароль через Argon2 (passlib).

    :param password: пароль в открытом виде.
    :returns: строка хэша Argon2.
    """
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """
    Сверяет пароль с сохранённым Argon2-хэшем.

    :param plain: пароль в открытом виде.
    :param hashed: сохранённый хэш.
    :returns: ``True``, если пароль совпадает.
    """
    return pwd_context.verify(plain, hashed)


class Security:
    """JWT access/refresh токены и хранение JTI в Redis."""

    @staticmethod
    def _get_refresh_token_key(user_id: int, jti: str):
        """
        Собирает Redis-ключ для refresh JTI.

        :param user_id: идентификатор пользователя.
        :param jti: JWT ID refresh-токена.
        :returns: строка ключа Redis.
        """
        return f"user:{user_id}:refresh:{jti}"

    @staticmethod
    def _create_token(
        user_id: int,
        token_type: str,
        token_expire: int,
        # scopes: list[str],  # TODO: добавить когда появится RBAC
    ) -> str:
        """
        Подписывает JWT (RS256) с типом и сроком жизни.

        :param user_id: subject токена.
        :param token_type: ``access`` или ``refresh``.
        :param token_expire: срок жизни в часах.
        :returns: закодированная JWT-строка.
        """
        now = dt.datetime.now(dt.UTC)
        jti = str(uuid.uuid4())

        payload = {
            "sub": str(user_id),
            "exp": now + dt.timedelta(hours=token_expire),
            "iat": now,
            "jti": jti,
            "type": token_type,
            # "scopes": scopes,  # TODO: добавить когда появится RBAC
        }
        token = jwt.encode(payload, Keys.get_private_key(), algorithm=ALGORITHM)
        return token

    @classmethod
    def create_tokens(cls, user_id: int) -> tuple[str, str]:
        """
        Создаёт пару access и refresh JWT для user_id.

        :param user_id: идентификатор пользователя.
        :returns: кортеж ``(access_token, refresh_token)``.
        """
        # TODO: добавить когда появится RBAC
        # user_scopes = await users_crud.read_available_rules_for_user(user_id=user_id)
        # scope_names = [rule.name for rule in user_scopes.rules]

        access_token = cls._create_token(
            user_id,
            "access",
            ACCESS_TOKEN_EXPIRE_HOURS,
        )
        refresh_token = cls._create_token(
            user_id,
            "refresh",
            REFRESH_TOKEN_EXPIRE_HOURS,
        )

        return access_token, refresh_token

    @classmethod
    def decode_access_token(cls, token: str) -> int:
        """
        Декодирует access JWT и возвращает user_id.

        :param token: строка access JWT.
        :returns: идентификатор пользователя из ``sub``.
        :raises UnauthorizedException: при истечении или невалидности.
        """
        try:
            payload = jwt.decode(token, Keys.get_public_key(), algorithms=[ALGORITHM])
        except jwt.ExpiredSignatureError as e:
            raise UnauthorizedException(detail="Token expired") from e
        except jwt.InvalidTokenError as e:
            raise UnauthorizedException(detail="Invalid token") from e

        if payload.get("type") != "access":
            raise UnauthorizedException(detail="Invalid token type")

        return int(payload["sub"])

    @classmethod
    async def decode_refresh_token(cls, token: str, redis_client: redis.Redis):
        """
        Валидирует refresh JWT и одноразово снимает JTI.

        :param token: строка refresh JWT.
        :param redis_client: клиент Redis с JTI.
        :returns: идентификатор пользователя из ``sub``.
        :raises UnauthorizedException: при истечении, отзыве или невалидности.
        """
        try:
            payload = jwt.decode(token, Keys.get_public_key(), algorithms=[ALGORITHM])
        except jwt.ExpiredSignatureError as e:
            raise UnauthorizedException(detail="Refresh token expired") from e
        except jwt.InvalidTokenError as e:
            raise UnauthorizedException(detail="Invalid refresh token") from e

        if payload.get("type") != "refresh":
            raise UnauthorizedException(detail="Invalid token type")

        user_id = int(payload["sub"])
        jti = payload["jti"]

        key = cls._get_refresh_token_key(user_id=user_id, jti=jti)
        exists = await redis_client.delete(key)
        if not exists:
            raise UnauthorizedException(detail="Refresh token revoked or not found")

        return user_id

    @classmethod
    async def store_refresh_token(cls, user_id: int, token: str, redis_client: redis.Redis) -> None:
        """
        Сохраняет JTI refresh-токена в Redis с TTL.

        :param user_id: идентификатор пользователя.
        :param token: строка refresh JWT.
        :param redis_client: клиент Redis.
        """
        payload = jwt.decode(token, Keys.get_public_key(), algorithms=[ALGORITHM])
        jti = payload["jti"]
        key = cls._get_refresh_token_key(user_id=user_id, jti=jti)
        await redis_client.setex(key, REFRESH_TOKEN_EXPIRE_HOURS, "1")

    @classmethod
    async def revoke_refresh_token(cls, token: str, redis_client: redis.Redis) -> None:
        """
        Отзывает refresh JTI в Redis (идемпотентно).

        :param token: строка refresh JWT.
        :param redis_client: клиент Redis.
        :raises UnauthorizedException: если токен невалиден.
        """
        try:
            payload = jwt.decode(
                token,
                Keys.get_public_key(),
                algorithms=[ALGORITHM],
                options={"verify_exp": False},
            )
        except jwt.InvalidTokenError as e:
            raise UnauthorizedException(detail="Invalid refresh token") from e

        if payload.get("type") != "refresh":
            raise UnauthorizedException(detail="Invalid token type")

        user_id = int(payload["sub"])
        jti = payload["jti"]
        key = cls._get_refresh_token_key(user_id=user_id, jti=jti)
        await redis_client.delete(key)
