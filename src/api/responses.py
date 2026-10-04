"""Переиспользуемые OpenAPI responses для роутеров."""

from fastapi import status

from src.models.errors import ErrorResponse

BAD_REQUEST = {
    status.HTTP_400_BAD_REQUEST: {
        "model": ErrorResponse,
        "description": "Bad request",
    },
}

UNAUTHORIZED = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Unauthorized",
    },
}

NOT_FOUND = {
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "Not found",
    },
}

CONFLICT = {
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponse,
        "description": "Conflict",
    },
}

UNPROCESSABLE = {
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ErrorResponse,
        "description": "Unprocessable entity",
    },
}

PAYLOAD_TOO_LARGE = {
    status.HTTP_413_CONTENT_TOO_LARGE: {
        "model": ErrorResponse,
        "description": "Payload too large",
    },
}
