"""Happy-path download через nginx (:8080) + X-Accel → MinIO.

Используется CLI ``scripts/smoke_nginx_download.py`` и ``tests/smoke``.
Требует: compose (nginx+minio+db+redis), uvicorn ``--host 0.0.0.0:8000``,
``ATTACHMENT_DOWNLOAD_MODE=x_accel``.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from dataclasses import dataclass

import httpx

DEFAULT_BASE = "http://127.0.0.1:8080"
INBOX_LIST_ID = 1


class SmokeUnavailable(RuntimeError):
    """Стек недоступен (nginx/API не отвечают)."""


@dataclass(frozen=True)
class SmokeResult:
    """Результат smoke + данные для curl/Postman."""

    base_url: str
    download_url: str
    token: str
    task_id: int
    attachment_id: int
    body: bytes
    content_type: str
    filename: str
    server: str | None


def probe(base_url: str, *, timeout: float = 2.0) -> None:
    """
    Проверяет, что nginx проксирует API.

    :param base_url: например ``http://127.0.0.1:8080``.
    :param timeout: таймаут probe.
    :raises SmokeUnavailable: connection refused / 502.
    """
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/health", timeout=timeout)
    except httpx.TransportError as exc:
        raise SmokeUnavailable(
            f"не достучаться до {base_url} ({exc}). "
            "Подними docker compose + uvicorn --host 0.0.0.0 --port 8000",
        ) from exc
    if response.status_code == 502:
        raise SmokeUnavailable(
            f"{base_url} → 502 (nginx жив, upstream :8000 нет). "
            "Запусти uvicorn --host 0.0.0.0 --port 8000",
        )


def run_smoke(
        base_url: str = DEFAULT_BASE,
        *,
        keep: bool = False,
        timeout: float = 15.0,
) -> SmokeResult:
    """
    sign-up → task → upload → PUT MinIO → complete → GET download через nginx.

    :param base_url: URL nginx (не прямой uvicorn).
    :param keep: не удалять вложение (удобно для Postman после скрипта).
    :param timeout: HTTP timeout.
    :returns: ``SmokeResult`` с ``download_url`` / ``token``.
    :raises SmokeUnavailable: стек не поднят.
    :raises RuntimeError: неожиданный статус / байты / режим.
    """
    base = base_url.rstrip("/")
    probe(base, timeout=min(timeout, 2.0))

    email = f"smoke-{uuid.uuid4().hex}@example.com"
    password = "SmokePass123!"
    body = b"%PDF-1.4smoke-nginx"
    content_type = "application/pdf"
    filename = "smoke-nginx.pdf"

    with httpx.Client(base_url=base, timeout=timeout, follow_redirects=False) as client:
        # sign-up может вернуть 500 при кривой session — юзер часто уже создан
        client.post(
            "/api/v1/auth/sign-up",
            json={"email": email, "password": password},
        )
        sign_in = client.post(
            "/api/v1/auth/sign-in",
            json={"email": email, "password": password},
        )
        if sign_in.status_code != 200:
            raise RuntimeError(
                f"sign-in failed: {sign_in.status_code} {sign_in.text}",
            )
        token = sign_in.json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}

        task = client.post(
            "/api/v1/tasks/",
            headers=auth,
            json={"list_id": INBOX_LIST_ID, "title": "smoke-nginx"},
        )
        if task.status_code != 200:
            raise RuntimeError(f"create task: {task.status_code} {task.text}")
        task_id = int(task.json()["id"])

        initiated = client.post(
            f"/api/v1/tasks/{task_id}/attachments/upload",
            headers=auth,
            json={
                "filename": filename,
                "content_type": content_type,
                "size_bytes": len(body),
            },
        )
        if initiated.status_code != 200:
            raise RuntimeError(
                f"initiate upload: {initiated.status_code} {initiated.text}",
            )
        upload = initiated.json()
        attachment_id = int(upload["id"])
        put_url = upload["upload_url"]

        put = httpx.put(
            put_url,
            content=body,
            headers={"Content-Type": content_type},
            timeout=timeout,
        )
        if put.status_code >= 400:
            raise RuntimeError(f"MinIO PUT failed: {put.status_code} {put.text}")

        completed = client.post(
            f"/api/v1/tasks/{task_id}/attachments/{attachment_id}/complete",
            headers=auth,
        )
        if completed.status_code != 200:
            raise RuntimeError(
                f"complete: {completed.status_code} {completed.text}",
            )

        download_path = f"/api/v1/tasks/{task_id}/attachments/{attachment_id}/download"
        download = client.get(download_path, headers=auth)
        location = download.headers.get("location", "")
        if download.status_code == 307:
            raise RuntimeError(
                "download вернул 307 — похоже ATTACHMENT_DOWNLOAD_MODE=presigned. "
                "Поставь x_accel в .env и перезапусти uvicorn. "
                f"Location={location!r}",
            )
        if download.status_code != 200:
            raise RuntimeError(
                f"download: {download.status_code} body={download.text!r}",
            )
        if download.content != body:
            raise RuntimeError(
                f"bytes mismatch: got {download.content!r}, want {body!r}",
            )
        if "9000" in location:
            raise RuntimeError(f"утечка MinIO в Location: {location!r}")
        server = download.headers.get("server")
        if server is None or not server.lower().startswith("nginx"):
            raise RuntimeError(
                f"ожидали Server: nginx..., получили {server!r} "
                "(запрос ушёл мимо nginx?)",
            )

        internal = client.get("/internal-s3/smoke-probe")
        if internal.status_code != 404:
            raise RuntimeError(
                f"/internal-s3/ должен быть 404, получили {internal.status_code}",
            )

        if not keep:
            client.delete(
                f"/api/v1/tasks/{task_id}/attachments/{attachment_id}",
                headers=auth,
            )

    return SmokeResult(
        base_url=base,
        download_url=f"{base}{download_path}",
        token=token,
        task_id=task_id,
        attachment_id=attachment_id,
        body=body,
        content_type=content_type,
        filename=filename,
        server=server,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: прогон smoke + печать URL/token для Postman."""
    parser = argparse.ArgumentParser(
        description="Smoke: download вложения через nginx X-Accel",
    )
    parser.add_argument(
        "--base",
        default=DEFAULT_BASE,
        help=f"nginx base URL (default {DEFAULT_BASE})",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="не удалять вложение после проверки (для curl/Postman)",
    )
    args = parser.parse_args(argv)

    try:
        result = run_smoke(base_url=args.base, keep=args.keep)
    except SmokeUnavailable as exc:
        print(f"SKIP/UNAVAILABLE: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print("OK: nginx download smoke passed")
    print(f"BASE={result.base_url}")
    print(f"DOWNLOAD_URL={result.download_url}")
    print(f"TOKEN={result.token}")
    print(f"TASK_ID={result.task_id}")
    print(f"ATTACHMENT_ID={result.attachment_id}")
    print(f"SERVER={result.server}")
    if args.keep:
        print()
        print("# Postman / curl (вложение не удалено):")
        print(
            f'curl -H "Authorization: Bearer {result.token}" '
            f'-o /tmp/{result.filename} "{result.download_url}"',
        )
    else:
        print()
        print("# вложение удалено; для ручного curl перезапусти с --keep")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
