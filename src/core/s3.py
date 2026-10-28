"""S3/MinIO: фабрика клиента и операции с объектами."""

from typing import Any

from aiobotocore.config import AioConfig
from aiobotocore.session import get_session
from botocore.exceptions import ClientError

from src.core.config import Configs, configs

# aiobotocore S3 client (типизация через Any; types-aiobotocore-s3 — опционально)
S3Client = Any

_s3_storage: "S3Storage | None" = None


def create_s3_client_cm(
        settings: Configs | None = None,
        *,
        endpoint_url: str | None = None,
):
    """
    Async context manager S3-клиента (path-style).

    :param settings: настройки; по умолчанию глобальный ``configs``.
    :param endpoint_url: override host (для short-lived подписи X-Accel).
    :returns: ``ClientCreatorContext`` aiobotocore.
    """
    settings = settings or configs
    session = get_session()
    return session.create_client(
        "s3",
        endpoint_url=endpoint_url or settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
        config=AioConfig(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
    )


class S3Storage:
    """Обёртка над aiobotocore S3-клиентом для одного бакета."""

    def __init__(self, client: S3Client, bucket: str):
        """
        :param client: открытый aiobotocore S3 client.
        :param bucket: имя бакета.
        """
        self._client = client
        self.bucket = bucket

    @property
    def client(self) -> S3Client:
        """Сырой aiobotocore-клиент (для редких операций)."""
        return self._client

    async def put_object(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        """
        Загружает объект в бакет.

        :param key: ключ объекта.
        :param body: тело.
        :param content_type: Content-Type (опционально).
        :returns: ответ ``put_object``.
        """
        params: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": body,
        }
        if content_type is not None:
            params["ContentType"] = content_type
        return await self._client.put_object(**params)

    async def head_object(self, key: str) -> dict[str, Any]:
        """
        Метаданные объекта без скачивания тела.

        :param key: ключ объекта.
        :returns: ответ ``head_object``.
        """
        return await self._client.head_object(Bucket=self.bucket, Key=key)

    async def delete_object(self, key: str) -> dict[str, Any]:
        """
        Удаляет объект.

        :param key: ключ объекта.
        :returns: ответ ``delete_object``.
        """
        return await self._client.delete_object(Bucket=self.bucket, Key=key)

    async def copy_object(self, source_key: str, dest_key: str) -> dict[str, Any]:
        """
        Копирует объект внутри бакета.

        :param source_key: исходный ключ.
        :param dest_key: целевой ключ.
        :returns: ответ ``copy_object``.
        """
        return await self._client.copy_object(
            Bucket=self.bucket,
            CopySource={"Bucket": self.bucket, "Key": source_key},
            Key=dest_key,
        )

    async def generate_presigned_url(
        self,
        client_method: str,
        *,
        key: str,
        expires_in: int,
        content_type: str | None = None,
        response_content_disposition: str | None = None,
        endpoint_url: str | None = None,
        settings: Configs | None = None,
    ) -> str:
        """
        Presigned URL (aiobotocore async).

        :param client_method: ``put_object`` / ``get_object``.
        :param key: ключ объекта.
        :param expires_in: TTL в секундах.
        :param content_type: для PUT — Content-Type в Params.
        :param response_content_disposition: для GET — Content-Disposition.
        :param endpoint_url: если задан — short-lived клиент с этим host
            (подпись GET под nginx→MinIO без второго пула).
        :param settings: креды/region для short-lived клиента.
        :returns: URL.
        """
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if content_type is not None:
            params["ContentType"] = content_type
        if response_content_disposition is not None:
            params["ResponseContentDisposition"] = response_content_disposition
        if endpoint_url is None:
            return await self._client.generate_presigned_url(
                ClientMethod=client_method,
                Params=params,
                ExpiresIn=expires_in,
            )
        async with create_s3_client_cm(
                settings,
                endpoint_url=endpoint_url,
        ) as client:
            return await client.generate_presigned_url(
                ClientMethod=client_method,
                Params=params,
                ExpiresIn=expires_in,
            )

    async def ensure_bucket(self) -> None:
        """Создаёт бакет, если его ещё нет (idempotent для MinIO/dev)."""
        try:
            await self._client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            http_status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code not in {"404", "403", "NoSuchBucket", "NotFound"} and http_status not in {
                404,
                403,
            }:
                raise
            await self._client.create_bucket(Bucket=self.bucket)


def get_s3_storage() -> S3Storage:
    """
    Глобальный ``S3Storage`` (инициализируется в lifespan).

    :returns: экземпляр ``S3Storage``.
    :raises RuntimeError: если клиент ещё не создан.
    """
    if _s3_storage is None:
        raise RuntimeError("S3 storage is not initialized")
    return _s3_storage


def set_s3_storage(storage: S3Storage | None) -> None:
    """Устанавливает/сбрасывает глобальный ``S3Storage``."""
    global _s3_storage
    _s3_storage = storage
