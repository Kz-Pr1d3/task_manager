from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class CustomList(BaseModel):
    """Пользовательский список в ответе GET /lists."""

    # model_config = ConfigDict(from_attributes=True)

    id: int
    name: str = Field(max_length=255)
    position: int
    user_id: int
    created_at: datetime


class CustomListItems(BaseModel):
    """Обёртка списка пользовательских списков."""

    items: list[CustomList]


class CreateCustomListRequest(BaseModel):
    """Тело запроса на создание user-списка."""

    name: str = Field(max_length=255)


class RenameCustomListRequest(BaseModel):
    """Тело запроса на переименование user-списка."""

    name: str = Field(max_length=255)


class ReorderCustomListRequest(BaseModel):
    """Тело запроса на смену позиции user-списка."""

    position: int = Annotated[int, Field(ge=1, le=5)]
