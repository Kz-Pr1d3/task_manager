import datetime as dt
import uuid

import jwt
import redis.asyncio as redis
from fastapi import HTTPException, status
from passlib.context import CryptContext

from src.core.keys import Keys

pwd_context = CryptContext(
    schemes=["argon2"],
    argon2__memory_cost=131072,
    argon2__parallelism=4,
    argon2__time_cost=3,
)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 12
REFRESH_TOKEN_EXPIRE_HOURS = ACCESS_TOKEN_EXPIRE_HOURS * 7


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


class Security:

    @staticmethod
    def _get_refresh_token_key(user_id: int, jti: str):
        return f"user:{user_id}:refresh:{jti}"

    @staticmethod
    def _create_token(
        user_id: int,
        token_type: str,
        token_expire: int,
        # scopes: list[str],  # TODO: добавить когда появится RBAC
    ) -> str:
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
    async def decode_refresh_token(cls, token: str, redis_client: redis.Redis):
        try:
            payload = jwt.decode(token, Keys.get_public_key(), algorithms=[ALGORITHM])
        except jwt.ExpiredSignatureError as e:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token expired") from e
        except jwt.InvalidTokenError as e:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from e

        if payload.get("type") != "refresh":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token type")

        user_id = int(payload["sub"])
        jti = payload["jti"]

        key = cls._get_refresh_token_key(user_id=user_id, jti=jti)
        exists = await redis_client.delete(key)
        if not exists:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token revoked or not found")

        return user_id

    @classmethod
    async def store_refresh_token(cls, user_id: int, token: str, redis_client: redis.Redis) -> None:
        """Store refresh token JTI in Redis with TTL."""
        payload = jwt.decode(token, Keys.get_private_key(), algorithms=ALGORITHM)
        jti = payload["jti"]
        key = cls._get_refresh_token_key(user_id=user_id, jti=jti)
        await redis_client.setex(key, REFRESH_TOKEN_EXPIRE_HOURS, "1")
