from src.repository.user import UserRepository


# async def test__create__success(user_repo: UserRepository):
#     res = await user_repo.create(email="test2@test.com", password="test")
#     assert res

async def test__get_by_email__not_exists(user_repo: UserRepository):
    not_exists_email = "not_exists_email@email.com"
    res = await user_repo.get_by_email(email=not_exists_email)
    assert not res


async def test__get_by_email__success(user_repo: UserRepository, test_user_email):
    res = await user_repo.get_by_email(email=test_user_email)
    assert res.email == test_user_email


async def test__get_by_id__success(user_repo: UserRepository, test_user_id):
    res = await user_repo.get_by_id(user_id=test_user_id)
    assert res.id == test_user_id
