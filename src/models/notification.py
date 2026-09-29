from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Notification(BaseModel):
    """Уведомление в API-ответах и репозитории."""

    model_config = ConfigDict(extra="ignore")

    id: int
    type: str
    category: str
    severity: Literal["normal", "important"]
    actor_id: int | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    title: str
    body: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    deep_link: str | None = None
    group_count: int = 1
    created_at: datetime
    read_at: datetime | None = None


class NotificationPage(BaseModel):
    """Страница уведомлений с cursor-пагинацией по id DESC."""

    items: list[Notification]
    has_more: bool
    next_before_id: int | None = None
    limit: int


class UnreadCountResponse(BaseModel):
    """Счётчики непрочитанных уведомлений."""

    total: int
    important: int
    by_category: dict[str, int] = Field(default_factory=dict)


class MarkNotificationsRead(BaseModel):
    """Тело POST /notifications/read: ids XOR all=true."""

    ids: list[int] = Field(default_factory=list, max_length=100)
    all: bool = False
    category: str | None = None

    @model_validator(mode="after")
    def validate_mode(self):
        """
        Требует ровно один режим: список ids или all=true.

        :returns: валидированная модель.
        :raises ValueError: если переданы оба режима или ни одного.
        """
        if self.all == bool(self.ids):
            raise ValueError("Передайте ids или all=true")
        return self


class MarkNotificationsUnread(BaseModel):
    """Тело POST /notifications/unread."""

    ids: list[int] = Field(min_length=1, max_length=100)


class NotificationMutationResult(BaseModel):
    """Результат mark read / unread."""

    updated_ids: list[int]


class SSETicketResponse(BaseModel):
    """Ответ POST /notifications/sse-ticket."""

    ticket: str


class NotificationEvent(BaseModel):
    """Контракт создания уведомления (emit / create_for_recipients)."""

    event_id: str
    type: str
    category: str = "tasks"
    severity: Literal["normal", "important"] = "normal"
    actor_id: int | None = None
    recipient_ids: set[int]
    entity_type: str | None = None
    entity_id: str | None = None
    title: str
    body: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    deep_link: str | None = None
    grouping_key: str | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
