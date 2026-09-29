import pytest
from fakeredis import FakeAsyncRedis

from src.core.exceptions import UnauthorizedException
from src.core.security import Security, hash_password, verify_password


def test__hash_password__is_hashed():
    password = "test"
    hashed_pass = hash_password(password=password)
    assert hashed_pass != password
    assert hashed_pass.startswith("$argon2")


def test__hash_password__salting_success():
    password = "test"
    hashed_pass_1 = hash_password(password=password)
    hashed_pass_2 = hash_password(password=password)

    assert hashed_pass_1 != hashed_pass_2


def test__verify_password__success():
    password = "test"
    hashed_pass = hash_password(password=password)

    is_correct = verify_password(plain=password, hashed=hashed_pass)
    assert is_correct


async def test__revoke_refresh_token__success():
    redis_client = FakeAsyncRedis()
    _, refresh_token = Security.create_tokens(user_id=1)
    await Security.store_refresh_token(user_id=1, token=refresh_token, redis_client=redis_client)

    await Security.revoke_refresh_token(token=refresh_token, redis_client=redis_client)

    with pytest.raises(UnauthorizedException, match="revoked or not found"):
        await Security.decode_refresh_token(token=refresh_token, redis_client=redis_client)


async def test__revoke_refresh_token__idempotent():
    redis_client = FakeAsyncRedis()
    _, refresh_token = Security.create_tokens(user_id=1)
    await Security.store_refresh_token(user_id=1, token=refresh_token, redis_client=redis_client)

    await Security.revoke_refresh_token(token=refresh_token, redis_client=redis_client)
    await Security.revoke_refresh_token(token=refresh_token, redis_client=redis_client)


async def test__revoke_refresh_token__invalid_token():
    redis_client = FakeAsyncRedis()

    with pytest.raises(UnauthorizedException, match="Invalid refresh token"):
        await Security.revoke_refresh_token(token="not-a-jwt", redis_client=redis_client)


async def test__revoke_refresh_token__access_token_rejected():
    redis_client = FakeAsyncRedis()
    access_token, _ = Security.create_tokens(user_id=1)

    with pytest.raises(UnauthorizedException, match="Invalid token type"):
        await Security.revoke_refresh_token(token=access_token, redis_client=redis_client)
