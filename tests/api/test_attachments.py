"""API-тесты вложений: auth, upload, complete, download, delete."""

import tempfile
from pathlib import Path

import asyncpg
import httpx
import pytest
from starlette.testclient import TestClient

from src.core.config import configs
from src.core.security import Security

INBOX_LIST_ID = 1


@pytest.fixture
def auth_headers(test_user_id: int) -> dict[str, str]:
    access, _ = Security.create_tokens(user_id=test_user_id)
    return {"Authorization": f"Bearer {access}"}


@pytest.fixture
def other_auth_headers() -> dict[str, str]:
    access, _ = Security.create_tokens(user_id=99999)
    return {"Authorization": f"Bearer {access}"}


@pytest.fixture
async def task_id(test_user_id: int):
    pool = await asyncpg.create_pool(dsn=configs.database_url)
    row = await pool.fetchrow(
        """
        INSERT INTO tasks (user_id, list_id, title, status)
        VALUES ($1, $2, 'api-attach-test', 'active')
        RETURNING id
        """,
        test_user_id,
        INBOX_LIST_ID,
    )
    tid = row["id"]
    yield tid
    await pool.execute("DELETE FROM task_attachment WHERE task_id = $1", tid)
    await pool.execute("DELETE FROM tasks WHERE id = $1", tid)
    await pool.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('task_attachment', 'id'),
            (SELECT COALESCE(MAX(id), 1) FROM task_attachment)
        )
        """
    )
    await pool.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('tasks', 'id'),
            (SELECT COALESCE(MAX(id), 1) FROM tasks)
        )
        """
    )
    await pool.close()


def _upload_url(task_id: int) -> str:
    return f"/v1/tasks/{task_id}/attachments/upload"


def _attachments_url(task_id: int) -> str:
    return f"/v1/tasks/{task_id}/attachments/"


def _complete_url(task_id: int, attachment_id: int) -> str:
    return f"/v1/tasks/{task_id}/attachments/{attachment_id}/complete"


def _download_url(task_id: int, attachment_id: int) -> str:
    return f"/v1/tasks/{task_id}/attachments/{attachment_id}/download"


def _delete_url(task_id: int, attachment_id: int) -> str:
    return f"/v1/tasks/{task_id}/attachments/{attachment_id}"


def test__list_attachments__unauthorized(client: TestClient, task_id: int):
    response = client.get(_attachments_url(task_id))
    assert response.status_code == 401


def test__initiate_upload__unauthorized(client: TestClient, task_id: int):
    response = client.post(
        _upload_url(task_id),
        json={
            "filename": "a.png",
            "content_type": "image/png",
            "size_bytes": 10,
        },
    )
    assert response.status_code == 401


def test__initiate_upload__success(
        client: TestClient,
        auth_headers: dict[str, str],
        task_id: int,
):
    response = client.post(
        _upload_url(task_id),
        headers=auth_headers,
        json={
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "size_bytes": 1024,
        },
    )
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"
    data = response.json()
    assert data["id"] > 0
    assert data["content_type"] == "image/jpeg"
    assert data["expires_in"] == configs.s3_presigned_put_ttl_sec


def test__initiate_upload__foreign_task(
        client: TestClient,
        other_auth_headers: dict[str, str],
        task_id: int,
):
    response = client.post(
        _upload_url(task_id),
        headers=other_auth_headers,
        json={
            "filename": "a.png",
            "content_type": "image/png",
            "size_bytes": 10,
        },
    )
    assert response.status_code == 404


def test__download__unauthorized(client: TestClient, task_id: int):
    response = client.get(
        _download_url(task_id, 1),
        follow_redirects=False,
    )
    assert response.status_code == 401


def test__download__foreign_task(
        client: TestClient,
        auth_headers: dict[str, str],
        other_auth_headers: dict[str, str],
        task_id: int,
):
    initiated = client.post(
        _upload_url(task_id),
        headers=auth_headers,
        json={
            "filename": "secret.png",
            "content_type": "image/png",
            "size_bytes": 4,
        },
    )
    assert initiated.status_code == 200
    attachment_id = initiated.json()["id"]

    response = client.get(
        _download_url(task_id, attachment_id),
        headers=other_auth_headers,
        follow_redirects=False,
    )
    assert response.status_code == 404


def test__initiate_upload__limit(
        client: TestClient,
        auth_headers: dict[str, str],
        task_id: int,
):
    payload = {
        "filename": "slot.png",
        "content_type": "image/png",
        "size_bytes": 10,
    }
    for i in range(configs.attachment_max_per_task):
        response = client.post(
            _upload_url(task_id),
            headers=auth_headers,
            json={**payload, "filename": f"slot-{i}.png"},
        )
        assert response.status_code == 200, response.text

    over = client.post(
        _upload_url(task_id),
        headers=auth_headers,
        json={**payload, "filename": "over.png"},
    )
    assert over.status_code == 409
    assert "limit" in over.json()["detail"].lower()


def test__initiate_upload__bad_mime(
        client: TestClient,
        auth_headers: dict[str, str],
        task_id: int,
):
    response = client.post(
        _upload_url(task_id),
        headers=auth_headers,
        json={
            "filename": "x.bin",
            "content_type": "application/octet-stream",
            "size_bytes": 10,
        },
    )
    assert response.status_code == 422


def test__initiate_upload__oversize(
        client: TestClient,
        auth_headers: dict[str, str],
        task_id: int,
):
    response = client.post(
        _upload_url(task_id),
        headers=auth_headers,
        json={
            "filename": "big.jpg",
            "content_type": "image/jpeg",
            "size_bytes": configs.attachment_max_bytes + 1,
        },
    )
    assert response.status_code == 413


def test__complete_upload__missing_object(
        client: TestClient,
        auth_headers: dict[str, str],
        task_id: int,
):
    initiated = client.post(
        _upload_url(task_id),
        headers=auth_headers,
        json={
            "filename": "gone.png",
            "content_type": "image/png",
            "size_bytes": 10,
        },
    )
    assert initiated.status_code == 200
    attachment_id = initiated.json()["id"]

    response = client.post(
        _complete_url(task_id, attachment_id),
        headers=auth_headers,
    )
    assert response.status_code == 409


def test__upload_complete_download_delete__roundtrip(
        client: TestClient,
        auth_headers: dict[str, str],
        task_id: int,
):
    body = b"%PDF-1.4api"
    content_type = "application/pdf"

    initiated = client.post(
        _upload_url(task_id),
        headers=auth_headers,
        json={
            "filename": "doc.pdf",
            "content_type": content_type,
            "size_bytes": len(body),
        },
    )
    assert initiated.status_code == 200
    upload = initiated.json()
    attachment_id = upload["id"]

    put = httpx.put(
        upload["upload_url"],
        content=body,
        headers={"Content-Type": content_type},
        timeout=10.0,
    )
    if put.status_code >= 400:
        pytest.skip(f"MinIO PUT failed: {put.status_code} {put.text}")
    assert put.status_code in {200, 204}

    completed = client.post(
        _complete_url(task_id, attachment_id),
        headers=auth_headers,
    )
    assert completed.status_code == 200
    ready = completed.json()
    assert ready["status"] == "ready"
    assert ready["size_bytes"] == len(body)
    assert ready["original_name"] == "doc.pdf"

    listed = client.get(_attachments_url(task_id), headers=auth_headers)
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()}
    assert attachment_id in ids

    download = client.get(
        _download_url(task_id, attachment_id),
        headers=auth_headers,
        follow_redirects=False,
    )
    assert download.status_code == 307
    assert download.headers.get("cache-control") == "no-store"
    location = download.headers.get("location")
    assert location is not None
    assert location.startswith("http")

    fetched = httpx.get(location, timeout=10.0)
    assert fetched.status_code == 200
    with tempfile.TemporaryDirectory() as tmp_dir:
        downloaded_path = Path(tmp_dir) / "doc.pdf"
        downloaded_path.write_bytes(fetched.content)
        assert downloaded_path.read_bytes() == body

    deleted = client.delete(
        _delete_url(task_id, attachment_id),
        headers=auth_headers,
    )
    assert deleted.status_code == 204

    listed_after = client.get(_attachments_url(task_id), headers=auth_headers)
    assert attachment_id not in {item["id"] for item in listed_after.json()}


def test__download__pending_conflict(
        client: TestClient,
        auth_headers: dict[str, str],
        task_id: int,
):
    initiated = client.post(
        _upload_url(task_id),
        headers=auth_headers,
        json={
            "filename": "pending.png",
            "content_type": "image/png",
            "size_bytes": 4,
        },
    )
    attachment_id = initiated.json()["id"]

    response = client.get(
        _download_url(task_id, attachment_id),
        headers=auth_headers,
        follow_redirects=False,
    )
    assert response.status_code == 409


def test__delete__not_found(
        client: TestClient,
        auth_headers: dict[str, str],
        task_id: int,
):
    response = client.delete(
        _delete_url(task_id, 999_999_999),
        headers=auth_headers,
    )
    assert response.status_code == 404
