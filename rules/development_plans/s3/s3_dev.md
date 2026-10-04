# План внедрения S3 (вложения к задачам)

План по **Части I** спецификации [S3_Redis_Nginx.docx](../S3_Redis_Nginx.docx): объектное хранилище, presigned URL, CORS, lifecycle. Redis — отдельный план позже. Nginx + X-Accel download → [nginx_dev.md](../nginx/nginx_dev.md).

Стек проекта: FastAPI + asyncpg + Redis. **Без** SQLAlchemy и Alembic. DDL — `db/scripts/init.sql`. Клиент S3 — **aiobotocore** (долгоживущий клиент в `lifespan`).

Связанные документы: [tasks_dev.md](../tasks/tasks_dev.md) (вложения раньше были «не MVP»), [tasks_tech.md](../tasks/tasks_tech.md), [notifications_mvp.md](../notifications/notifications_mvp.md) (паттерн плана).

---

## Статус реализации (код)

Обновлено: 2026-10-03.

| Область | Статус | Что есть |
|---------|--------|----------|
| MinIO / S3 в `docker-compose` | ✅ | свой образ `docker/minio`, volume `miniodata`, порты 9000/9001 |
| Настройки S3 в `Configs` | ✅ | endpoint/region/keys/bucket/TTL/лимиты + pending TTL / cleanup interval |
| `aiobotocore` клиент (lifespan) | ✅ | `src/core/s3.py` + `app.state.s3_storage` |
| DDL вложений | ✅ | `task_attachment` в `init.sql` |
| Repository | ✅ | `AttachmentRepository` (create/get/list/mark/delete/count/stale cleanup) |
| Service | ✅ | `AttachmentService` + `AttachmentCleanupService` |
| API upload / download / delete | ✅ | `/v1/tasks/{id}/attachments` + 307 + no-store |
| CORS на бакете | ✅ | MinIO: `MINIO_API_CORS_ALLOW_ORIGIN`; prod S3: `scripts/minio/cors.json` |
| Lifecycle (`tmp/`, abort multipart) | ✅ | `mc ilm import` tmp/pending; MinIO stale_uploads 168h |
| Фоновая чистка `pending` в БД | ✅ | `python -m src.workers.attachment_cleanup`; метрики pending/deleted |
| Тесты | ✅ | smoke S3 + repo CRUD + service (409/oversize) + API (auth/404/лимит 5) + cleanup |
| Prod checklist | ⏭ | нет прода; код/метрики готовы, IAM/NTP/алерт — при деплое (см. шаг 8) |

**Этап:** шаг 8 ⏭ (review без прода). План Части I закрыт на уровне кода; остаток — ops при появлении prod.

---

## Решения (зафиксировано)

| Вопрос | Решение | Обоснование (спека) |
|--------|---------|---------------------|
| Хранилище в dev | MinIO в Docker | §2: один код, `endpoint_url` + path-style |
| Хранилище в prod | S3-совместимое (AWS / Yandex / VK) | те же env, другой `endpoint_url` |
| Доступ к объектам | **Приватный бакет**, без публичных ACL | §4–§5 |
| Загрузка | **Presigned PUT** + шаг **complete** | §7: трафик мимо nginx/воркера |
| Ограничение размера при заливке | Проверка в API до выдачи URL + **`head_object` после PUT**; опционально Presigned POST | §7–§8: PUT не лимитирует размер подписью |
| Скачивание | **Presigned GET** → `307 RedirectResponse` | §6 |
| Ключ объекта | Генерирует **только сервер** | §1, §7 |
| Структура ключей | `tmp/pending/{user_id}/{uuid}{ext}` → `users/{user_id}/tasks/{task_id}/{uuid}{ext}` | §11: lifecycle по префиксу `tmp/` |
| Имя файла пользователя | В БД + `ResponseContentDisposition`; ключ не из user input | §1, §6 |
| Клиент S3 | Один на приложение, `AioConfig(s3={"addressing_style": "path"})` | §2–§3 |
| Проверка «есть ли объект» | `head_object`, не `get_object` | §3 |
| Multipart upload | **Отдельный план** → [s3_multipart_dev.md](s3_multipart_dev.md) | §10: порог ~100 МБ; max 300 MiB |
| CORS | На **бакете**, не в FastAPI | §9 |
| Удаление задачи | CASCADE вложений в БД + `delete_object` (best effort / worker) | §11 |

### Лимиты продукта (MVP вложений)

| Параметр | Значение |
|----------|----------|
| Макс. размер одного файла | 10 MiB |
| Макс. файлов на задачу | 5 |
| Допустимые MIME (MVP) | `image/jpeg`, `image/png`, `image/webp`, `application/pdf` |
| TTL presigned PUT | 600 с |
| TTL presigned GET | 120 с |
| TTL записи `pending` | 24 ч (lifecycle на `tmp/` + чистка БД) |

При необходимости жёсткого лимита на стороне хранилища для браузера — заменить PUT на **Presigned POST** с `content-length-range` (§8) на шаге 4.

---

## Что должно работать

- Пользователь прикрепляет файл к **своей** задаче без прокачки тела через API.
- Скачивание только после проверки `user_id` ↔ `task_id` ↔ attachment; чужой объект → **404** (не 403).
- Брошенные загрузки не копятся бесконечно (`tmp/` + `status=pending`).
- Локально: `docker compose up` поднимает MinIO; приложение работает с тем же кодом, что и на prod S3.

---

## Архитектура (кратко)

```text
Загрузка (presigned PUT):
  POST /tasks/{id}/attachments/upload
    -> проверка task.owner, квот, MIME, size
    -> INSERT attachment (status=pending, storage_key=tmp/...)
    -> generate_presigned_url(put_object)
    -> { attachment_id, url, content_type }

  PUT url (клиент -> MinIO/S3 напрямую)

  POST /tasks/{id}/attachments/{attachment_id}/complete
    -> head_object (размер, Content-Type)
    -> если OK: COPY tmp -> users/.../tasks/... (или сразу финальный ключ + delete tmp)
    -> UPDATE status=ready, size, content_type
    -> иначе: delete_object + DELETE row / failed

Скачивание:
  GET /tasks/{id}/attachments/{attachment_id}/download
    -> проверка доступа
    -> presigned GET (Content-Disposition)
    -> 307 Redirect

Удаление:
  DELETE /tasks/{id}/attachments/{attachment_id}
    -> delete_object + DELETE row
```

**Не делаем в этом плане:** прокси файла через FastAPI (§6–§7). Скрытие endpoint хранилища при download — [nginx_dev.md](../nginx/nginx_dev.md) (X-Accel-Redirect, §25); upload остаётся presigned PUT.

---

## DDL

Добавить в `db/scripts/init.sql` (для существующего volume — SQL вручную).

```sql
CREATE TABLE IF NOT EXISTS task_attachment (
    id              BIGSERIAL PRIMARY KEY,
    task_id         INT NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    user_id         INT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    storage_key     TEXT NOT NULL,
    original_name   VARCHAR(255) NOT NULL,
    content_type    VARCHAR(127) NOT NULL,
    size_bytes      BIGINT,
    status          VARCHAR(16) NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ready_at        TIMESTAMPTZ,
    CONSTRAINT task_attachment_status_check
        CHECK (status IN ('pending', 'ready', 'failed')),
    CONSTRAINT task_attachment_size_nonneg
        CHECK (size_bytes IS NULL OR size_bytes >= 0)
);

CREATE INDEX IF NOT EXISTS task_attachment_task_idx
    ON task_attachment (task_id, created_at DESC);

CREATE INDEX IF NOT EXISTS task_attachment_pending_idx
    ON task_attachment (status, created_at)
    WHERE status = 'pending';
```

Инвариант: `user_id` должен совпадать с `tasks.user_id` — проверка в service (как для остальных операций с задачей).

---

## Конфигурация

Новые поля в `src/core/config.py` (имена env — UPPER_SNAKE):

| Поле | Пример (dev) | Примечание |
|------|--------------|------------|
| `s3_endpoint_url` | `http://localhost:9000` | MinIO |
| `s3_region` | `us-east-1` | обязателен для botocore (§2) |
| `s3_access_key_id` | | не root в prod |
| `s3_secret_access_key` | | только env / secrets |
| `s3_bucket` | `task-manager-media` | один бакет MVP |
| `s3_presigned_put_ttl_sec` | `600` | |
| `s3_presigned_get_ttl_sec` | `120` | |
| `attachment_max_bytes` | `10485760` | 10 MiB |
| `attachment_max_per_task` | `5` | |

`.env.example` / README — добавить блок без секретов.

---

## Инфраструктура (шаг 1)

### Docker Compose

```yaml
  minio:
    build:
      context: ./docker/minio
    image: task-manager-minio:local
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - ./miniodata:/data
```

Образ свой (`docker/minio/Dockerfile`): бинарник с GitHub releases — официальные
`minio/minio` / `quay.io/minio/minio` публично закрыты. Первый раз:
`docker compose build minio && docker compose up -d`.

После первого запуска (один раз на окружение):

- создать бакет `task-manager-media`;
- Block Public Access / политика «всё закрыто» (§4);
- CORS для origin фронта (§9): `GET`, `PUT`, `HEAD`, `ExposeHeaders: ETag` если позже multipart;
- lifecycle JSON (§11): expiration `tmp/` через 1 день; `AbortIncompleteMultipartUpload` 7 дней.

Скрипт инициализации: `db/scripts/` или `scripts/minio-init.sh` с `mc` — по аналогии с `init.sql`.

### Зависимости

```
aiobotocore>=2.15
types-aiobotocore-s3  # опционально, для ty
```

---

## Код: слои

| Слой | Файлы | Ответственность |
|------|-------|-----------------|
| Core | `src/core/s3.py` | фабрика клиента, `generate_presigned_url`, `head_object`, `delete_object`, copy/rename |
| Core | `src/main.py` | `app.state.s3_client` / контекст в lifespan, закрытие при shutdown |
| Models | `src/models/attachments.py` | request/response схемы |
| Repository | `src/repository/attachment.py` | CRUD, count ready per task |
| Service | `src/services/attachment.py` | квоты, ключи, complete, presigned |
| API | `src/api/v1/attachments.py` или роуты в `tasks.py` | HTTP |
| Worker (опц.) | `src/workers/attachment_cleanup.py` | pending старше 24h без объекта в S3 |

Паттерны: как [notification](../notifications/notifications_mvp.md) — repo без лишних моков; S3-слой — реальный MinIO (skip, если недоступен).

### Ключи (канон)

```text
tmp/pending/{user_id}/{uuid4_hex}{suffix_lower}
users/{user_id}/tasks/{task_id}/{uuid4_hex}{suffix_lower}
```

- `suffix` — из whitelist расширений по MIME, не из произвольного имени.
- `original_name` — только в БД, санитизация длины 255.

### Complete (критично)

1. `head_object` на `storage_key` pending.
2. `ContentLength` ≤ `attachment_max_bytes`, иначе delete + `failed` / 413.
3. Сверка `Content-Type` с тем, что подписывали (§7).
4. Перенос: `copy_object` + `delete_object` на tmp **или** сразу финальный ключ при создании записи (тогда complete только flip status — проще, но tmp lifecycle всё равно нужен для брошенных PUT).

Рекомендация MVP: **финальный ключ сразу в `users/...`**, presigned PUT на него; при отмене/timeout — lifecycle по префиксу `users/...` не подходит → держать pending только под `tmp/pending/...`, после complete — copy в финальный ключ.

---

## HTTP API (черновик)

Префикс: `/api/v1/tasks/{task_id}/attachments` (auth как у tasks).

| Метод | Путь | Тело | Ответ |
|-------|------|------|-------|
| POST | `/upload` | `{ filename, content_type, size_bytes }` | `{ id, upload_url, content_type, expires_in }` |
| POST | `/{attachment_id}/complete` | — | `{ id, status, size_bytes, ... }` |
| GET | `/` | — | список `ready` |
| GET | `/{attachment_id}/download` | — | **307** Location presigned |
| DELETE | `/{attachment_id}` | — | 204 |

Ответы с presigned URL: `Cache-Control: no-store` (§6).

Ошибки: 404 (нет задачи / чужая / нет вложения), 409 (complete без объекта), 413 (size), 409 (лимит 5 файлов).

---

## CORS (бакет / MinIO)

**AWS / Yandex / VK S3 (prod):** CORS на бакете, не в FastAPI. Пример — `scripts/minio/cors.json`:

```json
[
  {
    "AllowedOrigins": ["http://localhost:5173"],
    "AllowedMethods": ["GET", "PUT", "HEAD"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3000
  }
]
```

Prod: без `*` в `AllowedOrigins` (§9).

**MinIO (dev):** `PutBucketCors` на используемом бинарнике → `NotImplemented`.
CORS задаём на сервере: `MINIO_API_CORS_ALLOW_ORIGIN` в `docker-compose` (default `http://localhost:5173`).

---

## Lifecycle (бакет)

**Expire abandoned tmp** (и MinIO, и S3) — `scripts/minio/lifecycle.json`:

```json
{
  "Rules": [
    {
      "ID": "drop-abandoned-tmp",
      "Status": "Enabled",
      "Filter": { "Prefix": "tmp/pending/" },
      "Expiration": { "Days": 1 }
    }
  ]
}
```

Применяется `minio-init` через `mc ilm import`.

**Abort incomplete multipart:**

- **S3 prod:** правило `AbortIncompleteMultipartUpload` Days=7 (спека §11) — добавить в lifecycle JSON окружения.
- **MinIO dev:** тот же XML отклоняется; вместо него
  `MINIO_API_STALE_UPLOADS_EXPIRY=168h` (+ cleanup interval) на сервисе `minio`.

---

## Порядок внедрения (чеклист)

### Шаг 1 — Infra + клиент

- [x] MinIO в `docker-compose.yml`, volume, порты
- [x] `Configs`: поля S3
- [x] `src/core/s3.py` + lifespan в `main.py`
- [x] Smoke: `put_object` / `head_object` / `delete_object` из CLI или pytest

### Шаг 2 — DDL + repository

- [x] Таблица `task_attachment` в `init.sql`
- [x] `AttachmentRepository`: create pending, get by id+task+user, list ready, mark ready/failed, delete, count ready

### Шаг 3 — Service

- [x] Генерация ключей, лимиты, presigned PUT
- [x] `complete_upload`: head_object, copy/delete, транзакция БД
- [x] `presigned_download`, delete с S3

### Шаг 4 — API

- [x] Роуты + OpenAPI
- [x] Подключить в `v1/router.py`
- [x] 307 на download, no-store на JSON с URL

### Шаг 5 — Bucket policy

- [x] Скрипт init бакета: CORS + lifecycle + private
- [x] Документировать в README

### Шаг 6 — Cleanup

- [x] Worker/cron: `pending` старше 24h → delete row; объект в tmp удалит lifecycle
- [x] (опц.) метрика «висящих pending»

### Шаг 7 — Тесты

- [x] Repo: CRUD
- [x] Service: complete без объекта → 409; oversize head → delete
- [x] API: auth, 404 на чужую задачу, лимит 5

### Шаг 8 — Prod checklist

**Контекст (2026-10-03):** прода нет — пункты ниже не верифицируются на живом S3/IAM.
Саммари: что уже заложено в коде/доках vs что делать при первом деплое.

| Пункт | Статус без прода | Что есть сейчас | При деплое |
|-------|------------------|-----------------|------------|
| IAM/user только на бакет (§2) | ⏭ N/A | Dev: `minioadmin`; README: «отдельный IAM»; env через `S3_*` | Создать scoped user/policy на один бакет; не root; секреты не в репо |
| NTP (§5 SignatureDoesNotMatch) | ⏭ N/A | Не применимо локально (один хост) | chrony/NTP на app-нодах; ловить clock skew |
| Короткие TTL presigned | ✅ в коде | PUT 600s / GET 120s (`Configs` + `.env.example`); `Cache-Control: no-store` на upload/download | Не раздувать TTL в prod env; origin CORS без `*` |
| Алерт на `tmp/pending/` (опц.) | 🟡 метрика есть | Gauge `attachment_pending_total` + cleanup counters; scrape `/metrics` | Alertmanager rule на рост gauge; опц. S3 prefix size |

Чеклист (для будущего деплоя):

- [ ] Отдельный IAM/user только на один бакет (§2) — **при первом prod**
- [ ] NTP на нодах (§5 SignatureDoesNotMatch) — **при первом prod**
- [x] Короткие TTL presigned — defaults + no-store уже в приложении
- [ ] Алерт на рост `tmp/pending/` (опц.) — метрика готова, rule — при появлении мониторинга в prod

Шаблоны prod-бакета (не шаг 8, но рядом): `scripts/minio/cors.json`, `lifecycle.json` (+ AbortIncompleteMultipartUpload для AWS/Yandex).

---

## Риски и грабли (из спеки)

| Риск | Митигация |
|------|-----------|
| PUT без лимита размера | POST policy или post-upload head + delete |
| Нет complete | lifecycle + pending cleanup |
| CORS только на бэкенде | править бакет |
| Клиент на каждый запрос | один клиент в lifespan |
| Body stream не закрыт | `async with resp["Body"]` при любом get |
| Presigned URL в кэше | `Cache-Control: no-store` |
| Часы разъехались | NTP |
| Публичный бакет «для простоты» | не делать; только presigned |

---

## Вне скоупа этого плана

- Rate limiting (Redis) — Часть II docx → отдельный `redis_rate_limit_dev.md`
- Nginx reverse proxy + X-Accel download — [nginx_dev.md](../nginx/nginx_dev.md); `limit_req` — следующий nginx-план
- Multipart upload > 100 MiB → [s3_multipart_dev.md](s3_multipart_dev.md)
- Превью/трансcoding изображений
- Антивирус, CDN, версионирование бакета
- Шаринг задач между пользователями

---

## После реализации

- Обновить секцию «Статус реализации» в этом файле
- Обновить [tasks_dev.md](../tasks/tasks_dev.md): вложения в MVP / таблица статусов
- Добавить ссылку в [rules/index.md](../../index.md)
