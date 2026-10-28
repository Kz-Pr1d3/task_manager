"""HTTP API вложений задач: presigned upload / complete / download."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response, status
from fastapi.responses import RedirectResponse

from src.api.dependencies import get_current_user_id
from src.api.responses import (
    CONFLICT,
    NOT_FOUND,
    PAYLOAD_TOO_LARGE,
    UNAUTHORIZED,
    UNPROCESSABLE,
)
from src.models.attachments import (
    DownloadAccelResult,
    InitiateUploadRequest,
    InitiateUploadResponse,
    TaskAttachment,
)
from src.services.dependencies import AttachmentServiceDep

attachments_router = APIRouter(
    prefix="/tasks/{task_id}/attachments",
    responses=UNAUTHORIZED,
)

task_id_annotation = Annotated[int, Path(description="ID задачи.")]
attachment_id_annotation = Annotated[int, Path(description="ID вложения.")]


@attachments_router.get(
    "/",
    tags=["attachments"],
    summary="Список ready-вложений задачи.",
    status_code=status.HTTP_200_OK,
    response_model=list[TaskAttachment],
)
async def list_attachments(
        task_id: task_id_annotation,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: AttachmentServiceDep,
):
    """
    Возвращает ready-вложения задачи текущего пользователя.

    :param task_id: идентификатор задачи.
    :param user_id: id из access-токена.
    :param service: сервис вложений.
    :returns: список ``TaskAttachment`` (status=ready).
    """
    return await service.list_ready(user_id=user_id, task_id=task_id)


@attachments_router.post(
    "/upload",
    tags=["attachments"],
    summary="Initiate upload: pending + presigned PUT.",
    status_code=status.HTTP_200_OK,
    response_model=InitiateUploadResponse,
    responses={**NOT_FOUND, **CONFLICT, **PAYLOAD_TOO_LARGE, **UNPROCESSABLE},
)
async def initiate_upload(
        task_id: task_id_annotation,
        body: InitiateUploadRequest,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: AttachmentServiceDep,
        response: Response,
):
    """
    Создаёт pending-вложение и выдаёт presigned PUT URL.

    :param task_id: идентификатор задачи.
    :param body: filename, content_type, size_bytes.
    :param user_id: id из access-токена.
    :param service: сервис вложений.
    :param response: для ``Cache-Control: no-store``.
    :returns: id + upload_url + TTL.
    """
    result = await service.initiate_upload(
        user_id=user_id,
        task_id=task_id,
        filename=body.filename,
        content_type=body.content_type,
        size_bytes=body.size_bytes,
    )
    response.headers["Cache-Control"] = "no-store"
    return result


@attachments_router.post(
    "/{attachment_id}/complete",
    tags=["attachments"],
    summary="Complete upload после PUT клиента в S3.",
    status_code=status.HTTP_200_OK,
    response_model=TaskAttachment,
    responses={**NOT_FOUND, **CONFLICT, **PAYLOAD_TOO_LARGE},
)
async def complete_upload(
        task_id: task_id_annotation,
        attachment_id: attachment_id_annotation,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: AttachmentServiceDep,
):
    """
    Проверяет объект в S3 и переводит вложение в ready.

    :param task_id: идентификатор задачи.
    :param attachment_id: id pending-вложения.
    :param user_id: id из access-токена.
    :param service: сервис вложений.
    :returns: ready ``TaskAttachment``.
    """
    return await service.complete_upload(
        user_id=user_id,
        task_id=task_id,
        attachment_id=attachment_id,
    )


@attachments_router.get(
    "/{attachment_id}/download",
    tags=["attachments"],
    summary="Скачивание: 307 presigned GET или 200 X-Accel-Redirect.",
    response_model=None,
    responses={
        **NOT_FOUND,
        **CONFLICT,
        status.HTTP_200_OK: {
            "description": "X-Accel (ATTACHMENT_DOWNLOAD_MODE=x_accel)",
        },
        status.HTTP_307_TEMPORARY_REDIRECT: {
            "description": "Presigned GET (ATTACHMENT_DOWNLOAD_MODE=presigned)",
        },
    },
)
async def download_attachment(
        task_id: task_id_annotation,
        attachment_id: attachment_id_annotation,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: AttachmentServiceDep,
):
    """
    Скачивание ready-вложения.

    - ``presigned``: ``307`` Location = presigned GET на S3 endpoint.
    - ``x_accel``: ``200`` пустое тело + ``X-Accel-Redirect`` для nginx.

    :param task_id: идентификатор задачи.
    :param attachment_id: id ready-вложения.
    :param user_id: id из access-токена.
    :param service: сервис вложений.
    :returns: ``RedirectResponse`` 307 или ``Response`` 200.
    """
    result = await service.get_download_url(
        user_id=user_id,
        task_id=task_id,
        attachment_id=attachment_id,
    )
    if isinstance(result, DownloadAccelResult):
        return Response(
            status_code=status.HTTP_200_OK,
            content=b"",
            headers={
                "X-Accel-Redirect": result.x_accel_redirect,
                "Content-Type": result.content_type,
                "Content-Disposition": result.content_disposition,
                "Cache-Control": "no-store",
            },
        )
    return RedirectResponse(
        url=result.url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Cache-Control": "no-store"},
    )


@attachments_router.delete(
    "/{attachment_id}",
    tags=["attachments"],
    summary="Удаление вложения (БД + S3).",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=NOT_FOUND,
)
async def delete_attachment(
        task_id: task_id_annotation,
        attachment_id: attachment_id_annotation,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: AttachmentServiceDep,
):
    """
    Удаляет вложение из БД и объект из S3 (best-effort).

    :param task_id: идентификатор задачи.
    :param attachment_id: id вложения.
    :param user_id: id из access-токена.
    :param service: сервис вложений.
    """
    await service.delete_attachment(
        user_id=user_id,
        task_id=task_id,
        attachment_id=attachment_id,
    )
