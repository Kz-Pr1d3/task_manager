import pytest
from starlette.testclient import TestClient

from src.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app=app)


@pytest.fixture
def select_three_rows() -> str:
    return """
    SELECT * FROM (VALUES 
        (1, 'Иван', 25),
        (2, 'Мария', 30),
        (3, 'Петр', 22)
    ) AS users(id, name, age);
    """
