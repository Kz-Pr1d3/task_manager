from fastapi import Request
from fastapi import APIRouter, status

from src.api.responses import UNAUTHORIZED
from src.models.auth import RefreshRequest, SignInRequest, SignUpRequest, TokenResponse
from src.services.dependencies import AuthServiceDep

auth_router = APIRouter(prefix="/auth")


@auth_router.post(
    "/sign-up",
    tags=["Auth"],
    summary="Регистрация нового пользователя",
    status_code=status.HTTP_200_OK,
    response_model=TokenResponse,
)
async def sign_up(credentials: SignUpRequest, service: AuthServiceDep, request: Request):
    """
    Регистрирует пользователя и сохраняет refresh в сессии.

    :param credentials: email и пароль для регистрации.
    :param service: сервис аутентификации.
    :param request: HTTP-запрос (для записи session).
    :returns: пара access и refresh токенов.
    """
    tokens = await service.create_user(credentials=credentials)
    request.session["refresh"] = tokens.refresh_token
    return tokens


@auth_router.post(
    "/sign-in",
    tags=["Auth"],
    summary="Вход",
    status_code=status.HTTP_200_OK,
    response_model=TokenResponse,
    responses=UNAUTHORIZED,
)
async def sign_in(credentials: SignInRequest, service: AuthServiceDep, request: Request):
    """
    Выполняет вход и сохраняет refresh в сессии.

    :param credentials: email и пароль для входа.
    :param service: сервис аутентификации.
    :param request: HTTP-запрос (для записи session).
    :returns: пара access и refresh токенов.
    """
    tokens = await service.sign_in(credentials=credentials)
    request.session["refresh"] = tokens.refresh_token
    return tokens


@auth_router.post(
    "/refresh",
    tags=["Auth"],
    summary="Обновление токена",
    status_code=status.HTTP_200_OK,
    response_model=TokenResponse,
    responses=UNAUTHORIZED,
)
async def refresh(body: RefreshRequest, service: AuthServiceDep, request: Request):
    """
    Обновляет пару токенов по refresh JWT.

    :param body: тело с refresh_token.
    :param service: сервис аутентификации.
    :param request: HTTP-запрос (для записи session).
    :returns: новая пара access и refresh токенов.
    """
    tokens = await service.refresh(refresh_token=body.refresh_token)
    request.session["refresh"] = tokens.refresh_token
    return tokens


@auth_router.post(
    "/logout",
    tags=["Auth"],
    summary="Чистка пользовательской сессии",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=UNAUTHORIZED,
)
async def logout(body: RefreshRequest, service: AuthServiceDep, request: Request):
    """
    Отзывает refresh-токен и очищает session.

    :param body: тело с refresh_token.
    :param service: сервис аутентификации.
    :param request: HTTP-запрос (для очистки session).
    """
    await service.logout(refresh_token=body.refresh_token)
    request.session.clear()
