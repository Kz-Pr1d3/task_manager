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
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
