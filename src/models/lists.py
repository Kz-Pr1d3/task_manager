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
    items: list[CustomList]


class CreateCustomListRequest(BaseModel):
    name: str = Field(max_length=255)


class RenameCustomListRequest(BaseModel):
    name: str = Field(max_length=255)


class ReorderCustomListRequest(BaseModel):
    position: int = Annotated[int, Field(ge=1, le=5)]
