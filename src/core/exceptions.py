from fastapi import HTTPException, status


class AppException(HTTPException):
    """Базовое HTTP-исключение приложения."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_detail: str = "Internal server error"

    def __init__(self, detail: str | None = None) -> None:
        """
        Создаёт HTTP-исключение со status_code класса.

        :param detail: текст ошибки; иначе ``default_detail``.
        """
        super().__init__(
            status_code=self.status_code,
            detail=detail if detail is not None else self.default_detail,
        )


class BadRequestException(AppException):
    """HTTP 400: некорректный запрос клиента."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Bad request"


class UnauthorizedException(AppException):
    """HTTP 401: требуется или неудачная аутентификация."""

    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "Unauthorized"


class NotFoundException(AppException):
    """HTTP 404: запрошенный ресурс не найден."""

    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "Not found"


class ConflictException(AppException):
    """HTTP 409: конфликт состояния ресурса."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "Conflict"


class PayloadTooLargeException(AppException):
    """HTTP 413: размер тела/файла превышает лимит."""

    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    default_detail = "Payload too large"


class UnprocessableEntityException(AppException):
    """HTTP 422: сущность понятна, но обработать нельзя."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    default_detail = "Unprocessable entity"
