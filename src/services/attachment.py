"""Сервис вложений задач: ключи, квоты, presigned, complete."""

import logging
import uuid
from pathlib import PurePosixPath

from botocore.exceptions import ClientError

from src.core.config import Configs, configs
from src.core.exceptions import (
    ConflictException,
    NotFoundException,
    PayloadTooLargeException,
    UnprocessableEntityException,
)
from src.core.s3 import S3Storage
from src.models.attachments import (
    DownloadUrlResult,
    InitiateUploadResponse,
    TaskAttachment,
)
from src.models.enums import AttachmentStatus, AttachmentWriteStatus
from src.repository.attachment import AttachmentRepository

logger = logging.getLogger(__name__)

# MIME → суффикс ключа (не из имени файла пользователя)
ALLOWED_MIME_SUFFIX: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}

_LIMIT_DETAIL = "The limit for attachments on this task has been reached"
_UNSUPPORTED_TYPE_DETAIL = "Unsupported content type"
_SIZE_DETAIL = "Attachment size exceeds the limit"
_MISSING_OBJECT_DETAIL = "Uploaded object not found"
_CONTENT_TYPE_MISMATCH_DETAIL = "Uploaded Content-Type does not match"
_NOT_PENDING_DETAIL = "Attachment is not pending"
_NOT_READY_DETAIL = "Attachment is not ready"


class AttachmentService:
    """Оркестрация вложений: БД + S3 (presigned / head / copy / delete)."""

    def __init__(
            self,
            repository: AttachmentRepository,
            s3: S3Storage,
            settings: Configs | None = None,
    ):
        """
        Инициализирует сервис вложений.

        :param repository: репозиторий ``task_attachment``.
        :param s3: обёртка над бакетом.
        :param settings: лимиты/TTL; по умолчанию глобальный ``configs``.
        """
        self.repository = repository
        self.s3 = s3
        self.settings = settings or configs

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """
        Имя для БД / Content-Disposition: без пути, ≤255.

        :param filename: сырое имя от клиента.
        :returns: безопасное имя.
        :raises UnprocessableEntityException: пустое после санитизации.
        """
        name = PurePosixPath(filename.replace("\\", "/")).name.strip()
        name = name.replace('"', "").replace("\x00", "")
        if not name:
            raise UnprocessableEntityException(detail="Invalid filename")
        return name[:255]

    @staticmethod
    def normalize_content_type(content_type: str) -> str:
        """
        Нормализует MIME: без параметров, lower.

        :param content_type: сырой Content-Type.
        :returns: ``type/subtype``.
        """
        return content_type.split(";", 1)[0].strip().lower()

    @classmethod
    def suffix_for_mime(cls, content_type: str) -> str:
        """
        Whitelist MIME → суффикс ключа.

        :param content_type: MIME (уже нормализованный или сырой).
        :returns: суффикс (``.jpg`` …).
        :raises UnprocessableEntityException: MIME вне whitelist.
        """
        mime = cls.normalize_content_type(content_type)
        suffix = ALLOWED_MIME_SUFFIX.get(mime)
        if suffix is None:
            raise UnprocessableEntityException(detail=_UNSUPPORTED_TYPE_DETAIL)
        return suffix

    @staticmethod
    def build_tmp_key(*, user_id: int, object_id: str, suffix: str) -> str:
        """Ключ pending: ``tmp/pending/{user_id}/{uuid}{ext}``."""
        return f"tmp/pending/{user_id}/{object_id}{suffix}"

    @staticmethod
    def build_final_key(
            *,
            user_id: int,
            task_id: int,
            object_id: str,
            suffix: str,
    ) -> str:
        """Ключ ready: ``users/{user_id}/tasks/{task_id}/{uuid}{ext}``."""
        return f"users/{user_id}/tasks/{task_id}/{object_id}{suffix}"

    @staticmethod
    def object_id_and_suffix_from_tmp_key(storage_key: str) -> tuple[str, str]:
        """
        Достаёт ``(object_id, suffix)`` из tmp-ключа.

        :param storage_key: ``tmp/pending/.../{uuid}{ext}``.
        :returns: object_id и суффикс с точкой.
        :raises ConflictException: ключ не парсится.
        """
        leaf = storage_key.rsplit("/", 1)[-1]
        dot = leaf.rfind(".")
        if dot <= 0:
            raise ConflictException(detail="Invalid storage key")
        return leaf[:dot], leaf[dot:]

    @staticmethod
    def content_disposition(filename: str) -> str:
        """
        ``Content-Disposition`` для presigned GET.

        :param filename: имя из БД (уже санитизированное).
        :returns: значение заголовка.
        """
        safe = filename.replace('"', "")
        return f"attachment; filename=\"{safe}\""

    def _assert_size_allowed(self, size_bytes: int) -> None:
        """
        Проверяет заявленный/фактический размер против лимита.

        :param size_bytes: размер в байтах.
        :raises PayloadTooLargeException: размер > лимита.
        """
        if size_bytes > self.settings.attachment_max_bytes:
            raise PayloadTooLargeException(detail=_SIZE_DETAIL)

    async def initiate_upload(
            self,
            *,
            user_id: int,
            task_id: int,
            filename: str,
            content_type: str,
            size_bytes: int,
    ) -> InitiateUploadResponse:
        """
        Создаёт pending + выдаёт presigned PUT на tmp-ключ.

        :param user_id: владелец.
        :param task_id: задача.
        :param filename: имя файла пользователя.
        :param content_type: заявленный MIME.
        :param size_bytes: заявленный размер.
        :returns: id вложения и upload URL.
        :raises PayloadTooLargeException: size > лимита.
        :raises UnprocessableEntityException: MIME / имя.
        :raises NotFoundException: задача недоступна.
        :raises ConflictException: лимит файлов на задачу.
        """
        self._assert_size_allowed(size_bytes)
        original_name = self.sanitize_filename(filename)
        mime = self.normalize_content_type(content_type)
        suffix = self.suffix_for_mime(mime)

        object_id = uuid.uuid4().hex
        storage_key = self.build_tmp_key(
            user_id=user_id,
            object_id=object_id,
            suffix=suffix,
        )

        result = await self.repository.create_pending(
            user_id=user_id,
            task_id=task_id,
            storage_key=storage_key,
            original_name=original_name,
            content_type=mime,
            size_bytes=size_bytes,
            limit=self.settings.attachment_max_per_task,
        )
        if result.status is AttachmentWriteStatus.forbidden:
            raise NotFoundException()
        if result.status is AttachmentWriteStatus.limit:
            raise ConflictException(detail=_LIMIT_DETAIL)

        attachment = result.attachment
        if attachment is None:
            raise NotFoundException()

        expires_in = self.settings.s3_presigned_put_ttl_sec
        upload_url = await self.s3.generate_presigned_url(
            "put_object",
            key=storage_key,
            expires_in=expires_in,
            content_type=mime,
        )
        return InitiateUploadResponse(
            id=attachment.id,
            upload_url=upload_url,
            content_type=mime,
            expires_in=expires_in,
        )

    async def complete_upload(
            self,
            *,
            user_id: int,
            task_id: int,
            attachment_id: int,
    ) -> TaskAttachment:
        """
        После PUT клиента: head → квоты → copy tmp→final → ready.

        :param user_id: владелец.
        :param task_id: задача.
        :param attachment_id: id pending-вложения.
        :returns: ready-вложение.
        :raises NotFoundException: нет строки / чужая.
        :raises ConflictException: не pending / нет объекта / MIME mismatch.
        :raises PayloadTooLargeException: ContentLength > лимита.
        """
        attachment = await self.repository.get_by_id(
            attachment_id=attachment_id,
            task_id=task_id,
            user_id=user_id,
        )
        if attachment is None:
            raise NotFoundException()
        if attachment.status is not AttachmentStatus.pending:
            raise ConflictException(detail=_NOT_PENDING_DETAIL)

        tmp_key = attachment.storage_key
        try:
            head = await self.s3.head_object(tmp_key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            http_status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in {"404", "NoSuchKey", "NotFound"} or http_status == 404:
                raise ConflictException(detail=_MISSING_OBJECT_DETAIL) from exc
            raise

        size_bytes = int(head["ContentLength"])
        actual_mime = self.normalize_content_type(str(head.get("ContentType") or ""))

        if size_bytes > self.settings.attachment_max_bytes:
            await self._fail_and_drop_object(
                attachment_id=attachment_id,
                task_id=task_id,
                user_id=user_id,
                storage_key=tmp_key,
            )
            raise PayloadTooLargeException(detail=_SIZE_DETAIL)

        expected_mime = self.normalize_content_type(attachment.content_type)
        if actual_mime != expected_mime:
            await self._fail_and_drop_object(
                attachment_id=attachment_id,
                task_id=task_id,
                user_id=user_id,
                storage_key=tmp_key,
            )
            raise ConflictException(detail=_CONTENT_TYPE_MISMATCH_DETAIL)

        object_id, suffix = self.object_id_and_suffix_from_tmp_key(tmp_key)
        final_key = self.build_final_key(
            user_id=user_id,
            task_id=task_id,
            object_id=object_id,
            suffix=suffix,
        )

        await self.s3.copy_object(source_key=tmp_key, dest_key=final_key)
        try:
            await self.s3.delete_object(tmp_key)
        except ClientError:
            logger.warning(
                "Failed to delete tmp object after copy",
                extra={"storage_key": tmp_key},
                exc_info=True,
            )

        ready = await self.repository.mark_ready(
            attachment_id=attachment_id,
            task_id=task_id,
            user_id=user_id,
            storage_key=final_key,
            size_bytes=size_bytes,
            content_type=expected_mime,
        )
        if ready is None:
            # гонка / уже не pending — убрать финальный объект best-effort
            try:
                await self.s3.delete_object(final_key)
            except ClientError:
                logger.warning(
                    "Failed to delete orphan final object",
                    extra={"storage_key": final_key},
                    exc_info=True,
                )
            raise ConflictException(detail=_NOT_PENDING_DETAIL)
        return ready

    async def _fail_and_drop_object(
            self,
            *,
            attachment_id: int,
            task_id: int,
            user_id: int,
            storage_key: str,
    ) -> None:
        """mark_failed + best-effort delete_object."""
        try:
            await self.s3.delete_object(storage_key)
        except ClientError:
            logger.warning(
                "Failed to delete object on fail path",
                extra={"storage_key": storage_key},
                exc_info=True,
            )
        await self.repository.mark_failed(
            attachment_id=attachment_id,
            task_id=task_id,
            user_id=user_id,
        )

    async def list_ready(
            self,
            *,
            user_id: int,
            task_id: int,
    ) -> list[TaskAttachment]:
        """
        Ready-вложения задачи владельца.

        :param user_id: владелец.
        :param task_id: задача.
        :returns: список ready (пустой, если задачи нет / чужая).
        """
        return await self.repository.list_ready(task_id=task_id, user_id=user_id)

    async def get_download_url(
            self,
            *,
            user_id: int,
            task_id: int,
            attachment_id: int,
    ) -> DownloadUrlResult:
        """
        Presigned GET для ready-вложения.

        :param user_id: владелец.
        :param task_id: задача.
        :param attachment_id: id вложения.
        :returns: URL + TTL.
        :raises NotFoundException: нет / чужое.
        :raises ConflictException: не ready.
        """
        attachment = await self.repository.get_by_id(
            attachment_id=attachment_id,
            task_id=task_id,
            user_id=user_id,
        )
        if attachment is None:
            raise NotFoundException()
        if attachment.status is not AttachmentStatus.ready:
            raise ConflictException(detail=_NOT_READY_DETAIL)

        expires_in = self.settings.s3_presigned_get_ttl_sec
        url = await self.s3.generate_presigned_url(
            "get_object",
            key=attachment.storage_key,
            expires_in=expires_in,
            response_content_disposition=self.content_disposition(
                attachment.original_name,
            ),
        )
        return DownloadUrlResult(url=url, expires_in=expires_in)

    async def delete_attachment(
            self,
            *,
            user_id: int,
            task_id: int,
            attachment_id: int,
    ) -> None:
        """
        Удаляет строку БД и объект в S3 (best-effort).

        :param user_id: владелец.
        :param task_id: задача.
        :param attachment_id: id вложения.
        :raises NotFoundException: нет / чужое.
        """
        deleted = await self.repository.delete(
            attachment_id=attachment_id,
            task_id=task_id,
            user_id=user_id,
        )
        if deleted is None:
            raise NotFoundException()

        try:
            await self.s3.delete_object(deleted.storage_key)
        except ClientError:
            logger.warning(
                "Failed to delete S3 object after DB delete",
                extra={"storage_key": deleted.storage_key},
                exc_info=True,
            )
