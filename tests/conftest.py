import pytest
from starlette.testclient import TestClient

from src.core.keys import Keys
from src.main import app


@pytest.fixture(scope="session", autouse=True)
def _load_jwt_keys() -> None:
    Keys.load_keys()


@pytest.fixture
def client() -> TestClient:
    with TestClient(app=app) as test_client:
        yield test_client


@pytest.fixture
def select_three_rows() -> str:
    return """
    SELECT * FROM (VALUES 
        (1, 'Иван', 25),
        (2, 'Мария', 30),
        (3, 'Петр', 22)
    ) AS users(id, name, age);
    """


@pytest.fixture
def test_user_id() -> int:
    return 1


@pytest.fixture
def test_user_email() -> str:
    return "test_user@test.com"
