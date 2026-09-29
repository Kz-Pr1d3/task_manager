from src.core.exceptions import ConflictException, NotFoundException
from src.models.lists import CustomList
from src.repository.list import ListRepository


class ListService:
    """Сервисный слой для пользовательских списков задач."""

    def __init__(self, repository: ListRepository):
        """
        Инициализирует сервис списков.

        :param repository: репозиторий списков.
        """
        self.repository = repository
        self.custom_lists_per_user = 5

    async def get_custom_lists(self, user_id: int) -> list[CustomList]:
        """
        Возвращает все user-списки владельца.

        :param user_id: идентификатор пользователя.
        :returns: список ``CustomList``.
        """
        return await self.repository.get_custom_lists(user_id=user_id)

    async def create_custom_list(self, user_id: int, list_name: str) -> CustomList:
        """
        Создаёт user-список с проверкой лимита.

        :param user_id: идентификатор пользователя.
        :param list_name: имя нового списка.
        :returns: созданный ``CustomList``.
        :raises ConflictException: если лимит списков исчерпан.
        """
        custom_list = await self.repository.create_custom_list(
            user_id=user_id,
            list_name=list_name,
            limit=self.custom_lists_per_user,
        )
        if custom_list is None:
            raise ConflictException(detail="The limit for creating custom lists has been reached")
        return custom_list

    async def rename_custom_list(self, user_id: int, list_id: int, new_list_name: str) -> CustomList:
        """
        Переименовывает существующий user-список.

        :param user_id: идентификатор пользователя.
        :param list_id: идентификатор списка.
        :param new_list_name: новое имя списка.
        :returns: обновлённый ``CustomList``.
        :raises NotFoundException: если список не найден.
        """
        custom_list = await self.repository.rename_custom_list(user_id=user_id, list_id=list_id, list_name=new_list_name)
        if not custom_list:
            raise NotFoundException()

        return custom_list

    async def reorder_custom_list(self, user_id: int, list_id: int, new_position: int):
        """
        Меняет позицию user-списка среди соседей.

        :param user_id: идентификатор пользователя.
        :param list_id: идентификатор списка.
        :param new_position: желаемая позиция.
        :returns: обновлённый ``CustomList``.
        :raises NotFoundException: если список не найден.
        """
        custom_list = await self.repository.reorder_custom_list(user_id=user_id, list_id=list_id, position=new_position)
        if not custom_list:
            raise NotFoundException()

        return custom_list

    async def delete_custom_list(self, user_id: int, list_id: int) -> CustomList:
        """
        Удаляет user-список (задачи уходят в trash).

        :param user_id: идентификатор пользователя.
        :param list_id: идентификатор списка.
        :returns: удалённый ``CustomList``.
        :raises NotFoundException: если список не найден.
        """
        custom_list = await self.repository.delete_custom_list(user_id=user_id, list_id=list_id)
        if not custom_list:
            raise NotFoundException()
        return custom_list
