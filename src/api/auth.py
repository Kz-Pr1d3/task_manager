from fastapi import APIRouter, status

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
async def sign_up(credentials: SignUpRequest, service: AuthServiceDep):
    return await service.create_user(credentials=credentials)


@auth_router.post(
    "/sign-in",
    tags=["Auth"],
    summary="Вход",
    status_code=status.HTTP_200_OK,
    response_model=TokenResponse,
)
async def sign_in(credentials: SignInRequest, service: AuthServiceDep):
    return await service.sign_in(credentials=credentials)


@auth_router.post(
    "/refresh",
    tags=["Auth"],
    summary="Обновление токена",
    status_code=status.HTTP_200_OK,
    response_model=TokenResponse,
)
async def refresh(request: RefreshRequest, service: AuthServiceDep):
    return await service.refresh(refresh_token=request)


@auth_router.post(
    "/logout",
    tags=["Auth"],
    summary="Чистка пользовательской сессии",
    status_code=status.HTTP_200_OK,
    response_model=TokenResponse,
)
async def logout():
    pass
