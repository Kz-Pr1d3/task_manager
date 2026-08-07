from fastapi import HTTPException, status


class AppException(HTTPException):
    """Базовое HTTP-исключение приложения."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_detail: str = "Internal server error"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(
            status_code=self.status_code,
            detail=detail if detail is not None else self.default_detail,
        )


class BadRequestException(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Bad request"


class UnauthorizedException(AppException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "Unauthorized"


class NotFoundException(AppException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "Not found"


class ConflictException(AppException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Conflict"


class UnprocessableEntityException(AppException):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    default_detail = "Unprocessable entity"
