from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from src.models.enums import TaskStatus, TaskPriority


class Task(BaseModel):
    id: int
    user_id: int
    list_id: int
    previous_list_id: Optional[int] = None
    parent_id: Optional[int] = None
    title: str = Field(max_length=50)
    description: Optional[str] = None
    priority: Optional[TaskPriority] = None
    due_date: Optional[datetime] = None
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


class TaskPage(BaseModel):
    items: list[Task]
    next_cursor: Optional[int] = None
    has_more: bool
    limit: int


class CreateTaskRequest(BaseModel):
    list_id: int
    title: str = Field(max_length=50)
    due_date: Optional[datetime] = None


class UpdateTaskRequest(BaseModel):
    title: Optional[str] = Field(max_length=50, default=None)
    description: Optional[str] = None
    priority: Optional[TaskPriority] = None
    due_date: Optional[datetime] = None


class MoveTaskRequest(BaseModel):
    list_id: int


class CreateSubtaskRequest(BaseModel):
    title: str = Field(max_length=50)
