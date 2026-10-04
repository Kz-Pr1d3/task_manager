# Task Manager

FastAPI-based task management API.

## TODO
1. ~~Добавить прикрепление файлов (minio)~~ — API/service готовы; bucket init — шаг 5
2. Уведомление в телеграм / вход через телеграм (OpenAuth 2.0)
3. добавить Nginx - работа с SSE и websocket / Ratelimiter
4. WebSocket - общий чат для юзеров (как на твиче)
5. Веб интерфейс - простой, чтобы проверить функционал
6. Grafana - дашборды по метрикам из прометеуса
7. Межсервисное взаимодействие через JsonRPC - нужно придумать как распилить сервис

## Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment variables
cp .env.example .env
```

## Database / infra

```bash
# Запуск (postgres + redis + minio + minio-init)
docker compose up -d

# Остановка
docker compose down

# Остановка + удаление данных (чистый старт)
docker compose down -v && rm -rf db/data miniodata && docker compose up -d

# Зайти в psql внутри контейнера
docker exec -it task_manager_db psql -U user -d task_manager
```

### MinIO / S3 (вложения)

- API: `http://localhost:9000`, console: `http://localhost:9001`
- Dev login: `minioadmin` / `minioadmin`
- Бакет: `task-manager-media` (создаётся `minio-init`)

Образ MinIO собирается локально (`docker/minio/Dockerfile`) — официальные
`minio/minio` / `quay.io/minio/minio` публично недоступны. Первый раз:

```bash
docker compose build minio minio-init
docker compose up -d
```

`minio-init` (one-shot после healthy MinIO) идемпотентно:

1. создаёт бакет `task-manager-media`;
2. `anonymous set none` — без публичного доступа (только presigned / креды);
3. lifecycle: expire `tmp/pending/` через 1 день (`scripts/minio/lifecycle.json`).

CORS и abort incomplete multipart на **сервере** MinIO (env в `docker-compose`):

| Env | Dev default | Зачем |
|-----|-------------|--------|
| `MINIO_API_CORS_ALLOW_ORIGIN` | `http://localhost:5173` | браузерный PUT/GET на бакет |
| `MINIO_API_STALE_UPLOADS_EXPIRY` | `168h` | ~7d abort incomplete multipart |
| `MINIO_API_STALE_UPLOADS_CLEANUP_INTERVAL` | `6h` | период чистки |

Почему не `PutBucketCors` / `AbortIncompleteMultipartUpload` в lifecycle: текущий MinIO бинарник отвечает `NotImplemented` / отклоняет XML — для AWS/Yandex S3 в prod используй bucket CORS + lifecycle как в `scripts/minio/cors.json` и спеке (§8–§11). Шаблон CORS для prod S3 лежит в `scripts/minio/cors.json`.

Скрипт с хоста (нужен `mc` в PATH):

```bash
./scripts/minio-init.sh
```

Переменные приложения — в `.env.example` (`S3_*`, `ATTACHMENT_*`).
Загрузка: `POST /v1/tasks/{id}/attachments/upload` → PUT на MinIO → `…/complete`.

Cleanup брошенных pending (БД; объекты `tmp/` — lifecycle бакета):

```bash
python -m src.workers.attachment_cleanup
```

Env: `ATTACHMENT_PENDING_TTL` (default 24h), `ATTACHMENT_CLEANUP_INTERVAL_SEC` (default 3600).

**Prod:** отдельный IAM/user на бакет; CORS без `*`; бакет не публичный.

## Run

```bash
uvicorn src.main:app --reload
```

## Test

```bash
pytest
```

## Lint

```bash
ruff check src tests
ruff format src tests
```
