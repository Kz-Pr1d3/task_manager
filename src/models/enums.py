from enum import Enum


class TaskStatus(str, Enum):
    """Статусы жизненного цикла задачи."""

    active = "active"
    completed = "completed"


class TaskPriority(str, Enum):
    """Приоритеты задач: low / medium / high."""

    low = "low"
    medium = "medium"
    high = "high"


class TaskWriteStatus(str, Enum):
    """Исход атомарной записи задачи (create / move / restore)."""

    ok = "ok"
    forbidden = "forbidden"  # список недоступен
    limit = "limit"  # лимит задач в списке
    not_found = "not_found"  # задача отсутствует / не в нужном состоянии


class AttachmentStatus(str, Enum):
    """Статусы вложения: pending → ready | failed."""

    pending = "pending"
    ready = "ready"
    failed = "failed"


class AttachmentWriteStatus(str, Enum):
    """Исход атомарного create pending вложения."""

    ok = "ok"
    forbidden = "forbidden"  # задача недоступна / чужая
    limit = "limit"  # лимит файлов на задачу
