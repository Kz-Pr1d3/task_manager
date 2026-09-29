from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Тело HTTP-ошибки (как у FastAPI HTTPException)."""

    detail: str
