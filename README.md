# Task Manager

FastAPI-based task management API.

## TODO
1. ~~Добавить прикрепление файлов (minio)~~ — API/service готовы; bucket init — шаг 5
2. Уведомление в телеграм / вход через телеграм (OpenAuth 2.0)
3. ~~добавить Nginx~~ — reverse proxy `:8080` + `/internal-s3/` (X-Accel) ✅ [nginx_dev.md](rules/development_plans/nginx/nginx_dev.md); SSE-safe proxy ❌ [nginx_sse_dev.md](rules/development_plans/nginx/nginx_sse_dev.md); rate limit — отдельно
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
# Запуск (postgres + redis + minio + minio-init + nginx)
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
Загрузка: `POST /api/v1/tasks/{id}/attachments/upload` → PUT на MinIO → `…/complete`.

Cleanup брошенных pending (БД; объекты `tmp/` — lifecycle бакета):

```bash
python -m src.workers.attachment_cleanup
```

Env: `ATTACHMENT_PENDING_TTL` (default 24h), `ATTACHMENT_CLEANUP_INTERVAL_SEC` (default 3600).

**Prod:** отдельный IAM/user на бакет; CORS без `*`; бакет не публичный.

## Run

```bash
# API на хосте
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

Через nginx (после `docker compose up -d`): `http://localhost:8080` → uvicorn на хосте `:8000`.
Прямой доступ к API (`:8000`) остаётся; MinIO `:9000` открыт ради presigned PUT.

Download через nginx (скрыть MinIO endpoint): в `.env` поставь
`ATTACHMENT_DOWNLOAD_MODE=x_accel` (default `presigned` — для pytest / прямого uvicorn).

Ручная проверка proxy:

```bash
curl -sS -H "Authorization: Bearer <token>" http://localhost:8080/api/v1/lists/
# прямой обход internal location должен дать 404:
curl -sS -o /dev/null -w "%{http_code}\n" http://localhost:8080/internal-s3/anything
```

## Test

```bash
# unit / api / service (без nginx smoke)
pytest

# smoke: байты через nginx :8080 (нужен compose + uvicorn 0.0.0.0:8000 + x_accel)
pytest -m smoke
# или CLI с URL для Postman:
./scripts/smoke_nginx_download.sh --keep
```

### Smoke nginx download

Предусловия:

1. `docker compose up -d` (nginx + minio + postgres + redis)
2. в `.env`: `ATTACHMENT_DOWNLOAD_MODE=x_accel`
3. `uvicorn src.main:app --reload --host 0.0.0.0 --port 8000`

```bash
./scripts/smoke_nginx_download.sh --keep
# печатает DOWNLOAD_URL + TOKEN; пример:
# curl -H "Authorization: Bearer $TOKEN" -o /tmp/out.pdf "$DOWNLOAD_URL"
```

`SMOKE_BASE` (default `http://127.0.0.1:8080`) — если nginx на другом host/port.

## Lint

```bash
ruff check src tests
ruff format src tests
```
