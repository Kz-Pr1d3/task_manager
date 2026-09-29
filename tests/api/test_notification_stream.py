import pytest
from fakeredis import FakeAsyncRedis
from starlette.testclient import TestClient

from src.core import cache
from src.core.security import Security


@pytest.fixture
def auth_headers(test_user_id: int) -> dict[str, str]:
    access, _ = Security.create_tokens(user_id=test_user_id)
    return {"Authorization": f"Bearer {access}"}


@pytest.fixture
def sse_client(client: TestClient):
    """
    TestClient с FakeAsyncRedis для ticket (изоляция от реального Redis).

    Lifespan уже поднял SSEHub в ``app.state``.
    """
    fake = FakeAsyncRedis()
    previous = cache.redis_client
    cache.redis_client = fake
    try:
        yield client
    finally:
        cache.redis_client = previous


@pytest.fixture
def finite_sse_stream(monkeypatch: pytest.MonkeyPatch):
    """
    ASGITransport httpx ждёт конца стрима; max lifetime=0 → только ready.
    """
    monkeypatch.setattr(
        "src.api.v1.notification_stream.SSE_CONNECTION_MAX_SEC",
        0,
    )


def test__stream__without_ticket_unauthorized(sse_client: TestClient):
    response = sse_client.get("/v1/notifications/stream")
    assert response.status_code == 401


def test__stream__invalid_ticket_unauthorized(sse_client: TestClient):
    response = sse_client.get(
        "/v1/notifications/stream",
        params={"ticket": "not-a-real-ticket"},
    )
    assert response.status_code == 401


def test__sse_ticket__unauthorized(sse_client: TestClient):
    response = sse_client.post("/v1/notifications/sse-ticket")
    assert response.status_code == 401


def test__sse_ticket__success(sse_client: TestClient, auth_headers: dict[str, str]):
    response = sse_client.post(
        "/v1/notifications/sse-ticket",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["ticket"], str)
    assert len(data["ticket"]) > 10


def test__stream__content_type_and_ready(
        sse_client: TestClient,
        auth_headers: dict[str, str],
        finite_sse_stream,
):
    ticket_response = sse_client.post(
        "/v1/notifications/sse-ticket",
        headers=auth_headers,
    )
    assert ticket_response.status_code == 200
    ticket = ticket_response.json()["ticket"]

    response = sse_client.get(
        "/v1/notifications/stream",
        params={"ticket": ticket},
    )
    assert response.status_code == 200
    content_type = response.headers["content-type"]
    assert content_type.startswith("text/event-stream")
    assert "event: ready" in response.text
    assert "retry: 3000" in response.text
    assert '"type":"ready"' in response.text or '"type": "ready"' in response.text


def test__stream__ticket_is_single_use(
        sse_client: TestClient,
        auth_headers: dict[str, str],
        finite_sse_stream,
):
    ticket = sse_client.post(
        "/v1/notifications/sse-ticket",
        headers=auth_headers,
    ).json()["ticket"]

    first = sse_client.get(
        "/v1/notifications/stream",
        params={"ticket": ticket},
    )
    assert first.status_code == 200
    assert "event: ready" in first.text

    reuse = sse_client.get(
        "/v1/notifications/stream",
        params={"ticket": ticket},
    )
    assert reuse.status_code == 401
