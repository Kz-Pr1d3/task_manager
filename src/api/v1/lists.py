from typing import Annotated

from fastapi import Depends
from fastapi import APIRouter, status, Path

from src.api.dependencies import get_current_user_id
from src.models.lists import CustomList, RenameCustomListRequest, CreateCustomListRequest, ReorderCustomListRequest
from src.services.dependencies import ListServiceDep

lists_router = APIRouter(prefix="/lists")
custom_list_id = Annotated[int, Path(description="ID пользовательского списка.")]


@lists_router.get(
    "/",
    tags=["lists"],
    summary="Получение пользовательских списков задач",
    status_code=status.HTTP_200_OK,
    response_model=list[CustomList],
)
async def get_custom_lists(
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: ListServiceDep,
):
    custom_lists = await service.get_custom_lists(user_id=user_id)
    return custom_lists


@lists_router.post(
    "/",
    tags=["lists"],
    summary="Создание пользовательских списка задач",
    status_code=status.HTTP_200_OK,
    response_model=CustomList,
)
async def create_custom_list(
        user_id: Annotated[int, Depends(get_current_user_id)],
        create_data: CreateCustomListRequest,
        service: ListServiceDep,
):
    return await service.create_custom_list(user_id=user_id, list_name=create_data.name)


@lists_router.patch(
    "/{list_id}/rename",
    tags=["lists"],
    summary="Переименование пользовательских списка задач",
    status_code=status.HTTP_200_OK,
    response_model=CustomList,
)
async def rename_custom_list(
        list_id: custom_list_id,
        update_data: RenameCustomListRequest,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: ListServiceDep,
):
    return await service.rename_custom_list(user_id=user_id, list_id=list_id, new_list_name=update_data.name)


@lists_router.patch(
    "/{list_id}/reorder",
    tags=["lists"],
    summary="Смена позиции пользовательских списка задач",
    status_code=status.HTTP_200_OK,
    response_model=CustomList,
)
async def reorder_custom_list(
        list_id: custom_list_id,
        update_data: ReorderCustomListRequest,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: ListServiceDep,
):
    return await service.reorder_custom_list(user_id=user_id, list_id=list_id, new_position=update_data.position)


@lists_router.delete(
    "/{list_id}",
    tags=["lists"],
    summary="Удаление пользовательских списка задач",
    status_code=status.HTTP_200_OK,
    # response_model=UserList,
)
async def delete_custom_list(
        list_id: custom_list_id,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: ListServiceDep,
):
    ...
