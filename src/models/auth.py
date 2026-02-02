from pydantic import BaseModel, EmailStr


class SignUpRequest(BaseModel):
    """Запрос на регистрацию нового пользователя."""

    login: EmailStr
    password: str


class SignInRequest(BaseModel):
    """Запрос на аутентификацию пользователя."""

    login: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
