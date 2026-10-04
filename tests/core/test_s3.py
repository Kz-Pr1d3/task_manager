"""Smoke: put / head / delete против локального MinIO."""

import uuid

import pytest
from botocore.exceptions import ClientError

from src.core.config import configs
from src.core.s3 import S3Storage, create_s3_client_cm


@pytest.fixture
async def s3_storage():
    async with create_s3_client_cm() as client:
        storage = S3Storage(client=client, bucket=configs.s3_bucket)
        try:
            await storage.ensure_bucket()
        except ClientError as exc:
            pytest.skip(f"MinIO unavailable: {exc}")
        yield storage


async def test__put_head_delete__roundtrip(s3_storage: S3Storage) -> None:
    key = f"tmp/smoke/{uuid.uuid4().hex}.bin"
    body = b"s3-smoke-payload"
    content_type = "application/octet-stream"

    await s3_storage.put_object(key, body, content_type=content_type)

    head = await s3_storage.head_object(key)
    assert head["ContentLength"] == len(body)
    assert head["ContentType"] == content_type

    await s3_storage.delete_object(key)

    with pytest.raises(ClientError) as exc_info:
        await s3_storage.head_object(key)
    assert exc_info.value.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}
