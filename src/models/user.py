from datetime import datetime

from pydantic import BaseModel, EmailStr


class User(BaseModel):
    id: int
    email: EmailStr
    password: str | None
    created_at: datetime | None
