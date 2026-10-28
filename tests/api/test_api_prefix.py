from starlette.testclient import TestClient


def test__old_auth_path__not_found(client: TestClient):
    response = client.post(
        "/auth/sign-in",
        json={"email": "old@example.com", "password": "x"},
    )
    assert response.status_code == 404


def test__unversioned_api_auth_path__not_found(client: TestClient):
    response = client.post(
        "/api/auth/sign-in",
        json={"email": "old@example.com", "password": "x"},
    )
    assert response.status_code == 404


def test__old_v1_path__not_found(client: TestClient):
    response = client.get("/v1/lists/")
    assert response.status_code == 404
