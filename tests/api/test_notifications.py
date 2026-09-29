import asyncpg
import pytest
from starlette.testclient import TestClient

from src.core.config import configs
from src.core.security import Security
from src.models.notification import NotificationEvent
from src.repository.notification import NotificationRepository


@pytest.fixture
def auth_headers(test_user_id: int) -> dict[str, str]:
    access, _ = Security.create_tokens(user_id=test_user_id)
    return {"Authorization": f"Bearer {access}"}


@pytest.fixture
def other_auth_headers() -> dict[str, str]:
    access, _ = Security.create_tokens(user_id=99999)
    return {"Authorization": f"Bearer {access}"}


@pytest.fixture
async def seed_notifications(test_user_id: int, auth_headers: dict[str, str]):
    """Сидит 3 уведомления отдельным pool (не loop TestClient)."""
    pool = await asyncpg.create_pool(dsn=configs.database_url)
    repo = NotificationRepository(pool=pool)
    for i, severity in enumerate(("important", "normal", "normal")):
        await repo.create_for_recipients(
            event=NotificationEvent(
                event_id=f"api-seed-{i}",
                type="task.deadline_reminder",
                severity=severity,
                recipient_ids={test_user_id},
                title=f"Notif {i}",
                metadata={"i": i},
                deep_link=f"/tasks/{i}",
            ),
        )
    yield auth_headers
    await repo.query("DELETE FROM notification WHERE recipient_id = $1", test_user_id)
    await pool.close()


def test__list_notifications__unauthorized(client: TestClient):
    response = client.get("/v1/notifications/")
    assert response.status_code == 401


def test__list_notifications__success(client: TestClient, seed_notifications):
    response = client.get("/v1/notifications/", headers=seed_notifications)
    assert response.status_code == 200
    data = response.json()
    assert data["has_more"] is False
    assert data["limit"] == 20
    assert len(data["items"]) == 3
    assert data["items"][0]["id"] > data["items"][1]["id"]


def test__list_notifications__limit_over_100(client: TestClient, seed_notifications):
    response = client.get(
        "/v1/notifications/",
        headers=seed_notifications,
        params={"limit": 101},
    )
    assert response.status_code == 422


def test__list_notifications__cursor(client: TestClient, seed_notifications):
    first = client.get(
        "/v1/notifications/",
        headers=seed_notifications,
        params={"limit": 2},
    ).json()
    assert first["has_more"] is True
    assert first["next_before_id"] == first["items"][-1]["id"]

    second = client.get(
        "/v1/notifications/",
        headers=seed_notifications,
        params={"limit": 2, "before_id": first["next_before_id"]},
    ).json()
    assert second["has_more"] is False
    assert len(second["items"]) == 1
    assert second["items"][0]["id"] < first["next_before_id"]


def test__unread_count__success(client: TestClient, seed_notifications):
    response = client.get("/v1/notifications/unread-count", headers=seed_notifications)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert data["important"] == 1
    assert data["by_category"]["tasks"] == 3


def test__mark_read_and_unread__success(client: TestClient, seed_notifications):
    listed = client.get("/v1/notifications/", headers=seed_notifications).json()
    nid = listed["items"][0]["id"]

    read = client.post(
        "/v1/notifications/read",
        headers=seed_notifications,
        json={"ids": [nid]},
    )
    assert read.status_code == 200
    assert read.json()["updated_ids"] == [nid]

    counts = client.get("/v1/notifications/unread-count", headers=seed_notifications).json()
    assert counts["total"] == 2

    unread = client.post(
        "/v1/notifications/unread",
        headers=seed_notifications,
        json={"ids": [nid]},
    )
    assert unread.status_code == 200
    assert unread.json()["updated_ids"] == [nid]

    counts = client.get("/v1/notifications/unread-count", headers=seed_notifications).json()
    assert counts["total"] == 3


def test__mark_read_all__success(client: TestClient, seed_notifications):
    response = client.post(
        "/v1/notifications/read",
        headers=seed_notifications,
        json={"all": True},
    )
    assert response.status_code == 200
    assert len(response.json()["updated_ids"]) == 3

    counts = client.get("/v1/notifications/unread-count", headers=seed_notifications).json()
    assert counts["total"] == 0


def test__mark_read__cannot_touch_foreign(client: TestClient, seed_notifications, other_auth_headers):
    listed = client.get("/v1/notifications/", headers=seed_notifications).json()
    nid = listed["items"][0]["id"]

    response = client.post(
        "/v1/notifications/read",
        headers=other_auth_headers,
        json={"ids": [nid]},
    )
    assert response.status_code == 200
    assert response.json()["updated_ids"] == []

    counts = client.get("/v1/notifications/unread-count", headers=seed_notifications).json()
    assert counts["total"] == 3


def test__mark_read__invalid_body(client: TestClient, seed_notifications):
    response = client.post(
        "/v1/notifications/read",
        headers=seed_notifications,
        json={"ids": [], "all": False},
    )
    assert response.status_code == 422
