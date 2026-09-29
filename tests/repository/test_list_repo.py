import pytest

from src.repository.base import BaseRepository
from src.repository.list import ListRepository


@pytest.fixture
async def create_list_data(base_repo: BaseRepository, test_user_id: int):
    query = """
        INSERT INTO lists (user_id, type, name, position)
        VALUES
            ($1, 'user', 'Работа',   1),
            ($1, 'user', 'Дом',      2),
            ($1, 'user', 'Покупки',  3);
    """
    await base_repo.query(query, test_user_id)

    yield

    await base_repo.query("DELETE FROM tasks WHERE user_id = $1", test_user_id)
    await base_repo.query(
        "DELETE FROM lists WHERE type = 'user' AND user_id = $1",
        test_user_id,
    )

    # fix serial id
    await base_repo.query(
        """
        SELECT setval(
            pg_get_serial_sequence('lists', 'id'),
            (SELECT COALESCE(MAX(id), 1) FROM lists)
        )
        """
    )
    await base_repo.query(
        """
        SELECT setval(
            pg_get_serial_sequence('tasks', 'id'),
            (SELECT COALESCE(MAX(id), 1) FROM tasks)
        )
        """
    )


async def test__get_user_lists__empty(list_repo: ListRepository, test_user_id: int):
    custom_lists = await list_repo.get_custom_lists(user_id=test_user_id)
    assert custom_lists == []


async def test__get_user_lists__success(create_list_data, list_repo: ListRepository, test_user_id: int):
    custom_lists = await list_repo.get_custom_lists(user_id=test_user_id)
    assert len(custom_lists) > 1

    first_list = custom_lists[0]
    assert first_list.user_id == test_user_id
    assert first_list.name in ["Работа", "Дом", "Покупки"]


async def test__create_custom_list__success(list_repo: ListRepository, test_user_id: int, base_repo: BaseRepository):
    test_list_name = "test list name"
    custom_list = await list_repo.create_custom_list(
        user_id=test_user_id,
        list_name=test_list_name,
        limit=5,
    )
    assert custom_list is not None
    assert custom_list.name == test_list_name
    assert custom_list.user_id == test_user_id
    assert custom_list.position == 1

    query = """
    DELETE FROM lists WHERE type = 'user' AND user_id = $1;
    """
    await base_repo.query(query, test_user_id)
    # fix serial id
    query = """
        SELECT setval(
            pg_get_serial_sequence('lists', 'id'),
            (SELECT COALESCE(MAX(id), 1) FROM lists)
        );
    """
    await base_repo.query(query)


async def test__create_custom_list__limit_reached(
    create_list_data, list_repo: ListRepository, test_user_id: int
):
    custom_list = await list_repo.create_custom_list(
        user_id=test_user_id,
        list_name="overflow",
        limit=3,
    )
    assert custom_list is None


async def test__create_custom_list__appends_position(
    create_list_data, list_repo: ListRepository, test_user_id: int
):
    custom_list = await list_repo.create_custom_list(
        user_id=test_user_id,
        list_name="Ещё один",
        limit=5,
    )
    assert custom_list is not None
    assert custom_list.position == 4


async def test__rename_custom_list__success(create_list_data, list_repo: ListRepository, test_user_id: int):
    custom_lists = await list_repo.get_custom_lists(user_id=test_user_id)
    list_id = custom_lists[0].id
    list_name = "New Работа"
    custom_list = await list_repo.rename_custom_list(user_id=test_user_id, list_id=list_id, list_name=list_name)

    assert custom_list.name == list_name


async def test__rename_custom_list__empty(list_repo: ListRepository):
    not_exists_user = 11
    list_id = 1
    list_name = "New Работа"
    custom_list = await list_repo.rename_custom_list(user_id=not_exists_user, list_id=list_id, list_name=list_name)

    assert not custom_list


async def test__reorder_custom_list__move_down(create_list_data, list_repo: ListRepository, test_user_id: int):
    custom_lists = await list_repo.get_custom_lists(user_id=test_user_id)
    # Работа=1, Дом=2, Покупки=3 → Работа на 3
    first = custom_lists[0]
    custom_list = await list_repo.reorder_custom_list(
        user_id=test_user_id, list_id=first.id, position=3
    )

    assert custom_list is not None
    assert custom_list.id == first.id
    assert custom_list.position == 3

    ordered = await list_repo.get_custom_lists(user_id=test_user_id)
    assert [item.name for item in ordered] == ["Дом", "Покупки", "Работа"]
    assert [item.position for item in ordered] == [1, 2, 3]


async def test__reorder_custom_list__move_up(create_list_data, list_repo: ListRepository, test_user_id: int):
    custom_lists = await list_repo.get_custom_lists(user_id=test_user_id)
    # Работа=1, Дом=2, Покупки=3 → Покупки на 1
    last = custom_lists[-1]
    custom_list = await list_repo.reorder_custom_list(
        user_id=test_user_id, list_id=last.id, position=1
    )

    assert custom_list is not None
    assert custom_list.id == last.id
    assert custom_list.position == 1

    ordered = await list_repo.get_custom_lists(user_id=test_user_id)
    assert [item.name for item in ordered] == ["Покупки", "Работа", "Дом"]
    assert [item.position for item in ordered] == [1, 2, 3]


async def test__reorder_custom_list__clamp_and_noop(
    create_list_data, list_repo: ListRepository, test_user_id: int
):
    custom_lists = await list_repo.get_custom_lists(user_id=test_user_id)
    first = custom_lists[0]

    # position > cnt → clamp to 3 (move down)
    moved = await list_repo.reorder_custom_list(
        user_id=test_user_id, list_id=first.id, position=99
    )
    assert moved is not None
    assert moved.position == 3

    # noop: уже на 3
    same = await list_repo.reorder_custom_list(
        user_id=test_user_id, list_id=first.id, position=3
    )
    assert same is not None
    assert same.position == 3
    assert same.id == first.id


async def test__reorder_custom_list__not_found(list_repo: ListRepository, test_user_id: int):
    custom_list = await list_repo.reorder_custom_list(
        user_id=test_user_id, list_id=999999, position=1
    )
    assert custom_list is None


async def test__delete_custom_list__success_compacts_positions(
    create_list_data, list_repo: ListRepository, test_user_id: int
):
    custom_lists = await list_repo.get_custom_lists(user_id=test_user_id)
    # Работа=1, Дом=2, Покупки=3 → удаляем Дом
    middle = custom_lists[1]
    deleted = await list_repo.delete_custom_list(user_id=test_user_id, list_id=middle.id)

    assert deleted is not None
    assert deleted.id == middle.id
    assert deleted.name == "Дом"

    ordered = await list_repo.get_custom_lists(user_id=test_user_id)
    assert [item.name for item in ordered] == ["Работа", "Покупки"]
    assert [item.position for item in ordered] == [1, 2]


async def test__delete_custom_list__trashes_tasks_to_inbox(
    create_list_data,
    list_repo: ListRepository,
    base_repo: BaseRepository,
    test_user_id: int,
):
    custom_lists = await list_repo.get_custom_lists(user_id=test_user_id)
    target = custom_lists[0]

    task_row = await base_repo.one(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        VALUES ($1, $2, 'to trash', 'active')
        RETURNING id
        """,
        test_user_id,
        target.id,
    )
    task_id = task_row["id"]

    deleted = await list_repo.delete_custom_list(user_id=test_user_id, list_id=target.id)
    assert deleted is not None

    task = await base_repo.one(
        """
        SELECT list_id, previous_list_id, deleted_at, updated_at
        FROM tasks WHERE id = $1
        """,
        task_id,
    )
    assert task["deleted_at"] is not None
    assert task["updated_at"] is not None
    assert task["deleted_at"] == task["updated_at"]
    assert task["previous_list_id"] == target.id
    assert task["list_id"] == 1  # Inbox

    remaining = await list_repo.get_custom_lists(user_id=test_user_id)
    assert all(item.id != target.id for item in remaining)


async def test__delete_custom_list__already_trashed_moves_list_id(
    create_list_data,
    list_repo: ListRepository,
    base_repo: BaseRepository,
    test_user_id: int,
):
    custom_lists = await list_repo.get_custom_lists(user_id=test_user_id)
    target = custom_lists[0]

    task_row = await base_repo.one(
        """
        INSERT INTO tasks (user_id, list_id, title, status, previous_list_id, deleted_at)
        VALUES ($1, $2, 'already trash', 'active', $2, now())
        RETURNING id, deleted_at
        """,
        test_user_id,
        target.id,
    )
    task_id = task_row["id"]
    old_deleted_at = task_row["deleted_at"]

    deleted = await list_repo.delete_custom_list(user_id=test_user_id, list_id=target.id)
    assert deleted is not None

    task = await base_repo.one(
        """
        SELECT list_id, previous_list_id, deleted_at, updated_at
        FROM tasks WHERE id = $1
        """,
        task_id,
    )
    assert task["list_id"] == 1
    assert task["previous_list_id"] == target.id
    assert task["deleted_at"] == old_deleted_at
    assert task["updated_at"] is not None
    assert task["updated_at"] >= old_deleted_at


async def test__delete_custom_list__not_found(list_repo: ListRepository, test_user_id: int):
    assert await list_repo.delete_custom_list(user_id=test_user_id, list_id=999_999) is None


async def test__delete_custom_list__rejects_inbox(
    list_repo: ListRepository, test_user_id: int
):
    assert await list_repo.delete_custom_list(user_id=test_user_id, list_id=1) is None
