from fastapi import APIRouter, status

from src.models.auth import SignUpRequest, TokenResponse, SignInRequest

auth_router = APIRouter(prefix="/auth")


@auth_router.post(
    "/sign-up",
    tags=["Auth"],
    summary="Регистрация нового пользователя",
    status_code=status.HTTP_200_OK,
    response_model=TokenResponse,
)
async def sign_up(credentials: SignUpRequest):
    pass


@auth_router.post(
    "/sign-in",
    tags=["Auth"],
    summary="Вход",
    status_code=status.HTTP_200_OK,
    response_model=TokenResponse,
)
async def sign_in(credentials: SignInRequest):
    pass


@auth_router.post(
    "/refresh",
    tags=["Auth"],
    summary="Обновление токена",
    status_code=status.HTTP_200_OK,
    response_model=TokenResponse,
)
async def refresh():
    pass
