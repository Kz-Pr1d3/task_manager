"""Модели вложений задач (S3 / MinIO)."""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.models.enums import AttachmentStatus, AttachmentWriteStatus


class TaskAttachment(BaseModel):
    """Вложение задачи в API-ответах и репозитории."""

    model_config = ConfigDict(extra="ignore")

    id: int
    task_id: int
    user_id: int
    storage_key: str
    original_name: str = Field(max_length=255)
    content_type: str = Field(max_length=127)
    size_bytes: int | None = None
    status: AttachmentStatus
    created_at: datetime
    ready_at: datetime | None = None


@dataclass(frozen=True)
class AttachmentWriteResult:
    """Результат create pending: статус + вложение при ``ok``."""

    status: AttachmentWriteStatus
    attachment: TaskAttachment | None = None


class InitiateUploadRequest(BaseModel):
    """Тело запроса на выдачу presigned PUT."""

    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=127)
    size_bytes: int = Field(gt=0)


class InitiateUploadResponse(BaseModel):
    """Ответ initiate upload: id + presigned PUT."""

    id: int
    upload_url: str
    content_type: str
    expires_in: int


class DownloadUrlResult(BaseModel):
    """Presigned GET для редиректа на скачивание."""

    url: str
    expires_in: int
