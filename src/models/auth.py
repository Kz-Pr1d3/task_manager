from pydantic import BaseModel, EmailStr


class SignUpRequest(BaseModel):
    """Запрос на регистрацию нового пользователя."""

    email: EmailStr
    password: str


class SignInRequest(BaseModel):
    """Запрос на аутентификацию пользователя."""

    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    """Запрос на обновление пары JWT по refresh."""

    refresh_token: str


class TokenResponse(BaseModel):
    """Ответ с access/refresh токенами и типом Bearer."""

    access_token: str
    refresh_token: str
    type: str = "Bearer"
