# Структура проекта Task Manager

Карта репо для агентов. Детали фич — не здесь: `rules/index.md` → папка фичи.
Стиль кода: `rules/code/`. Схема БД: `rules/db/db.mdc` + `db/scripts/init.sql`.

## Обзор

FastAPI API, Python ≥ 3.11 (dev venv 3.13), Clean Architecture, **без ORM** (`asyncpg`).
Dev-инфра: Postgres 17 + Redis 7 + MinIO + nginx (`docker compose up -d`).

## Дерево

```
task_manager/
├── src/
│   ├── main.py                 # FastAPI app, lifespan (DB/Redis/S3/SSE bus), /health, /metrics
│   ├── api/
│   │   ├── dependencies.py     # get_current_user_id (JWT Bearer)
│   │   ├── responses.py        # OpenAPI error maps
│   │   └── v1/
│   │       ├── router.py       # prefix /v1; main include prefix=/api
│   │       ├── auth.py         # POST /api/v1/auth/sign-up|sign-in|refresh|logout
│   │       ├── lists.py        # CRUD пользовательских списков
│   │       ├── tasks.py        # CRUD + move/complete/trash/restore
│   │       ├── attachments.py  # presigned upload / complete / download / delete
│   │       ├── notifications.py
│   │       └── notification_stream.py  # SSE ticket + /stream
│   ├── services/               # бизнес-логика; DI: dependencies.py
│   │   ├── auth.py, list.py, task.py, notification.py
│   │   ├── attachment.py, attachment_cleanup.py
│   │   └── deadline_reminders.py
│   ├── repository/             # asyncpg, 1 RTT / CTE; DI: dependencies.py
│   │   ├── base.py             # pool helpers: one/query/transaction
│   │   ├── user.py, list.py, task.py, notification.py, attachment.py
│   ├── models/                 # Pydantic v2 схемы (не ORM)
│   │   ├── auth.py, user.py, lists.py, tasks.py, enums.py
│   │   ├── attachments.py, notification.py, errors.py
│   ├── core/
│   │   ├── config.py           # pydantic-settings ← .env
│   │   ├── database.py         # asyncpg pool
│   │   ├── cache.py            # Redis client
│   │   ├── security.py, keys.py
│   │   ├── exceptions.py       # AppException иерархия
│   │   ├── s3.py               # aiobotocore S3Storage (lifespan)
│   │   ├── sse_hub.py, redis_notification_bus.py
│   │   └── attachment_metrics.py, notification_metrics.py
│   ├── middleware/             # logging, tracing, metrics
│   └── workers/                # отдельные процессы, не в uvicorn
│       ├── attachment_cleanup.py    # python -m src.workers.attachment_cleanup
│       └── deadline_reminders.py
├── tests/                      # зеркало src/; стиль: rules/code/tests.md
│   ├── conftest.py             # client, общие константы
│   ├── api/, core/, repository/, services/, middleware/
│   └── smoke/                  # pytest -m smoke (nginx :8080); default прогон исключает
├── db/scripts/init.sql         # DDL + seed Inbox; данные: db/data/ (gitignore)
├── docker/
│   ├── nginx/nginx.conf        # :8080; location /api/ + /; internal /internal-s3/ → minio:9000
│   └── minio/                  # Dockerfile сервера + Dockerfile.init (mc bucket)
├── scripts/
│   ├── minio-init.sh, minio/cors.json, minio/lifecycle.json
│   └── smoke_nginx_download.sh|.py
├── rules/                      # memory bank; вход: rules/index.md
├── docker-compose.yml          # postgres, redis, minio, minio-init, nginx, prometheus
├── pyproject.toml              # ruff, pytest, ty
├── requirements.txt
└── .env / .env.example
```

Новый модуль: файл в слое + DI в `*/dependencies.py` + роутер в `v1/router.py` (если HTTP) + зеркало в `tests/<layer>/`.

## Слои

```
API  →  Service  →  Repository  →  Postgres (asyncpg)
                 ↘  core (Redis, S3, SSE, security)
```

Верх зависит от низа, не наоборот. SQL только в `repository/`. HTTP-схемы только в `models/` + `api/`.

## Стек

| Категория | Инструмент |
|-----------|------------|
| App | FastAPI ≥ 0.135, Uvicorn 0.40, Pydantic 2.12 |
| DB | PostgreSQL 17, asyncpg 0.31 (без SQLAlchemy/Alembic) |
| Cache / bus | Redis 5.x, fakeredis в тестах |
| S3 | aiobotocore, MinIO (dev image `docker/minio`) |
| Auth | PyJWT RS256, argon2, SessionMiddleware |
| Observability | prometheus-client, OpenTelemetry (флаги в конфиге) |
| Test/lint | pytest 9 + pytest-asyncio, ruff 0.14, ty 0.0.13, httpx |

## Конфиг (`src/core/config.py`)

Обязательные: `database_url`, `secret_key`, `session_key`, RSA key paths + password.
Группы env: `REDIS_URL`; `S3_*` + `ATTACHMENT_*` + `S3_X_ACCEL_*`; `DEADLINE_*`; `ENABLE_TRACING` / `ENABLE_METRICS`.
Download: `ATTACHMENT_DOWNLOAD_MODE=presigned|x_accel` (default `presigned` — pytest / прямой uvicorn).

## Эндпоинты (факт)

| Метод | Путь | Модуль |
|-------|------|--------|
| GET | `/health` | `main.py` |
| GET | `/metrics` | mount, если `enable_metrics` |
| GET | `/api/docs`, `/api/redoc`, `/api/openapi.json` | FastAPI |
| POST | `/api/v1/auth/sign-up`, `.../sign-in`, `.../refresh`, `.../logout` | `api/v1/auth.py` |
| GET/POST | `/api/v1/lists/` | `api/v1/lists.py` |
| PATCH | `/api/v1/lists/{id}/rename`, `.../reorder` | |
| DELETE | `/api/v1/lists/{id}` | |
| GET/POST | `/api/v1/tasks/` (`list_id`) | `api/v1/tasks.py` |
| GET/PATCH/DELETE | `/api/v1/tasks/{id}` | DELETE = hard delete из trash |
| POST | `/api/v1/tasks/{id}/move\|complete\|trash\|restore` | |
| GET/POST | `/api/v1/tasks/{id}/attachments/`, `.../upload` | `api/v1/attachments.py` |
| POST/GET/DELETE | `.../attachments/{id}/complete\|download` | download: 307 или X-Accel |
| GET | `/api/v1/notifications/`, `/unread-count` | `api/v1/notifications.py` |
| POST | `/api/v1/notifications/read`, `/unread` | |
| POST/GET | `/api/v1/notifications/sse-ticket`, `/stream` | `notification_stream.py` |

Нет: virtual views, multipart upload, password policy, rate limit.

## Инфра (dev)

`docker compose up -d` → postgres `:5432`, redis `:6379`, minio `:9000/:9001`, nginx `:8080` → uvicorn на хосте `:8000`.
API: `uvicorn src.main:app --reload --host 0.0.0.0 --port 8000`.
Тесты: `pytest` (без smoke); `pytest -m smoke` нужен compose + uvicorn + `x_accel`.
Воркеры: `python -m src.workers.attachment_cleanup`, `python -m src.workers.deadline_reminders`.
