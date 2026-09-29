from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.models.enums import TaskStatus, TaskPriority, TaskWriteStatus


class Task(BaseModel):
    """Модель задачи в API-ответах и репозитории."""

    model_config = ConfigDict(extra="ignore")

    id: int
    user_id: int
    list_id: int
    previous_list_id: int | None = None
    title: str = Field(max_length=50)
    description: str | None = None
    priority: TaskPriority | None = None
    due_date: datetime | None = None
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    deleted_at: datetime | None = None


class TaskPage(BaseModel):
    """Страница задач с cursor-пагинацией."""

    items: list[Task]
    next_cursor: int | None = None
    has_more: bool
    limit: int



class CreateTaskRequest(BaseModel):
    """Тело запроса на создание задачи в списке."""

    list_id: int
    title: str = Field(max_length=50)
    due_date: datetime | None = None


class UpdateTaskRequest(BaseModel):
    """Тело частичного обновления полей задачи."""

    title: str | None = Field(max_length=50, default=None)
    description: str | None = None
    priority: TaskPriority | None = None
    due_date: datetime | None = None


class MoveTaskRequest(BaseModel):
    """Тело запроса на перемещение задачи в список."""

    list_id: int


@dataclass(frozen=True)
class TaskWriteResult:
    """Результат create/move/restore: статус + задача при ``ok``."""

    status: TaskWriteStatus
    task: Task | None = None


@dataclass(frozen=True)
class DeadlineReminderCandidate:
    """Задача-кандидат на ``task.deadline_reminder``."""

    id: int
    title: str
    due_date: datetime
    user_id: int
