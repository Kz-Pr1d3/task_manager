import datetime as dt
import uuid

import jwt
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
    async def _create_token(
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

        if token_type == "refresh":
            ttl = int(dt.timedelta(hours=token_expire).total_seconds())
            print(ttl)
            # TODO redis conn
            # await ConnectionsStorage.redis_client.setex(
            #     f"user:{user_id}:token:{jti}", ttl, token
            # )

        return token

    @classmethod
    async def create_tokens(cls, user_id: int) -> tuple[str, str]:
        # TODO: добавить когда появится RBAC
        # user_scopes = await users_crud.read_available_rules_for_user(user_id=user_id)
        # scope_names = [rule.name for rule in user_scopes.rules]

        access_token = await cls._create_token(
            user_id,
            "access",
            ACCESS_TOKEN_EXPIRE_HOURS,
        )
        refresh_token = await cls._create_token(
            user_id,
            "refresh",
            REFRESH_TOKEN_EXPIRE_HOURS,
        )

        return access_token, refresh_token

    @classmethod
    async def decode_refresh_token(cls, token: str):
        try:
            payload = jwt.decode(token, Keys.get_public_key(), algorithms=[ALGORITHM])
        except jwt.ExpiredSignatureError as e:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token expired") from e
        except jwt.InvalidTokenError as e:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from e

        if payload.get("type") != "refresh":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token type")

        # TODO check - redis conn
        # await ConnectionsStorage.redis_client.setex(
        #     f"user:{user_id}:token:{jti}", ttl, token
        # )
        return payload["sub"]
