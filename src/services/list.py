from src.core.exceptions import ConflictException, NotFoundException
from src.models.lists import CustomList
from src.repository.list import ListRepository


class ListService:
    def __init__(self, repository: ListRepository):
        self.repository = repository
        self.custom_lists_per_user = 5

    async def get_custom_lists(self, user_id: int) -> list[CustomList]:
        return await self.repository.get_custom_lists(user_id=user_id)

    async def create_custom_list(self, user_id: int, list_name: str) -> CustomList:
        custom_list = await self.repository.create_custom_list(
            user_id=user_id,
            list_name=list_name,
            limit=self.custom_lists_per_user,
        )
        if custom_list is None:
            raise ConflictException(detail="The limit for creating custom lists has been reached")
        return custom_list

    async def rename_custom_list(self, user_id: int, list_id: int, new_list_name: str) -> CustomList:
        custom_list = await self.repository.rename_custom_list(user_id=user_id, list_id=list_id, list_name=new_list_name)
        if not custom_list:
            raise NotFoundException()

        return custom_list

    async def reorder_custom_list(self, user_id: int, list_id: int, new_position: int):
        custom_list = await self.repository.reorder_custom_list(user_id=user_id, list_id=list_id, position=new_position)
        if not custom_list:
            raise NotFoundException()

        return custom_list

    async def delete_custom_list(self, user_id: int, list_id: int): ...  # TODO in transaction
