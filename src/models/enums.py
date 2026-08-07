from enum import Enum


class TaskStatus(str, Enum):
    """Статусы задачи."""

    active = "active"
    completed = "completed"


class TaskPriority(str, Enum):
    """Приоритеты задач"""

    low = "low"
    medium = "medium"
    high = "high"
