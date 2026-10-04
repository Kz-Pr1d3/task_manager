# План: Nginx перед API + X-Accel-Redirect → S3

План по **Части III** спецификации [S3_Redis_Nginx.docx](../S3_Redis_Nginx.docx): nginx как reverse proxy (§21) и раздача приватных вложений через `X-Accel-Redirect` (§25), без свечения endpoint MinIO/S3 клиенту.

Стек: FastAPI + MinIO (уже есть) + **nginx** в Docker. Upload остаётся **presigned PUT** ([s3_dev.md](../s3/s3_dev.md)) — тело файла мимо nginx/API. Этот план меняет только **download**.

Связанные: [s3_dev.md](../s3/s3_dev.md), [s3_multipart_dev.md](../s3/s3_multipart_dev.md), [notifications_mvp.md](../notifications/notifications_mvp.md) (SSE позже через тот же nginx).

---

## Статус реализации (код)

Обновлено: 2026-10-04.

| Область | Статус | Что есть |
|---------|--------|----------|
| Решения / контракт | ✅ | этот документ |
| `docker/nginx/` + сервис в compose | ❌ | nginx в проекте нет |
| Базовый reverse proxy → API | ❌ | API сейчас с хоста напрямую |
| `location /internal-s3/` + `internal` | ❌ | |
| Download: `X-Accel-Redirect` вместо 307 | ❌ | сейчас 307 → presigned GET |
| Feature flag / режим download | ❌ | |
| Тесты (заголовки, 404, без обхода internal) | ❌ | |
| limit_req / real_ip / SSE proxy | ⏭ | отдельный план / шаг позже (§22–§24, README TODO) |

**Этап:** план зафиксирован, реализация не начата.

---

## Решения (зафиксировано)

| Вопрос | Решение | Обоснование |
|--------|---------|-------------|
| Зачем nginx | Reverse proxy перед API + раздача файлов | §21: TLS/буфер/лимиты/файлы дешевле до Python |
| Upload | **Без изменений** — presigned PUT клиент → MinIO | §7, §26: `client_max_body_size` на upload не нужен |
| Download MVP раньше | 307 → presigned GET (endpoint хранилища виден) | [s3_dev.md](../s3/s3_dev.md) §6 |
| Download этот план | **X-Accel-Redirect** → nginx → MinIO | §25: скрыть адрес хранилища, байты мимо воркера |
| Доступ к приватному бакету | В `X-Accel-Redirect` кладём **path + query от short-lived presigned GET** | Бакет `anonymous=none`; пример docx с `Authorization ""` без подписи на приватном бакете **не взлетит** |
| Путь internal | `/internal-s3/` + `internal;` → `proxy_pass http://minio:9000/` | §25 пример; снаружи 404 |
| Кто строит путь | Только сервер из `storage_key` + presigned query | §25 грабля: не из user input |
| Content-Type / Disposition | Задаёт FastAPI в ответе с X-Accel | §25: иначе nginx угадает по расширению ключа |
| Режим без nginx (pytest / uvicorn напрямую) | `ATTACHMENT_DOWNLOAD_MODE=presigned\|x_accel` (default в тестах — `presigned`) | Без nginx X-Accel бесполезен; тесты API не требуют контейнера |
| Порт наружу (dev) | nginx `:8080` → API; MinIO `:9000` пока открыт ради presigned PUT | Upload всё ещё идёт на MinIO; закрытие 9000 — только с proxy upload / отдельный план |
| limit_req / limit_conn / dry_run | **Не в этом плане** | §22–§23, §27 → `nginx_limits_dev.md` позже |
| SSE / WebSocket proxy | **Не в этом плане** | README TODO #3; нужны `proxy_buffering off`, long timeouts |
| TLS | Dev: HTTP; prod: TLS на nginx (§21) | не блокер для X-Accel |

---

## Что должно работать

- Клиент качает вложение: `GET /v1/tasks/{id}/attachments/{aid}/download` с Bearer → **200** (пустое тело) + `X-Accel-Redirect` (через nginx) → файл с правильным `Content-Type` / `Content-Disposition`.
- В браузере/Network **нет** редиректа на `localhost:9000` / внешний S3 endpoint — URL остаётся на домене API (nginx).
- Чужой attachment → **404** (как сейчас); путь `/internal-s3/...` снаружи → **404**.
- Upload / complete / delete **не ломаются**.
- `docker compose up` поднимает nginx; локальный uvicorn доступен через nginx.

---

## Архитектура

```text
Upload (без изменений):
  Client -> API (presigned PUT) -> Client PUT -> MinIO

Download (новый путь):
  Client
    -> nginx :8080
      -> proxy_pass API
         -> auth + ownership
         -> generate_presigned_url(get_object)  # короткий TTL
         -> Response 200, body empty, headers:
              X-Accel-Redirect: /internal-s3/{bucket}/{key}?X-Amz-...
              Content-Type: ...
              Content-Disposition: attachment; filename="..."
              Cache-Control: no-store
      <- nginx видит X-Accel-Redirect, ответ API отбрасывает
      -> location /internal-s3/ (internal)
         -> proxy_pass http://minio:9000/{bucket}/{key}?X-Amz-...
      <- байты клиенту
```

```text
Режим ATTACHMENT_DOWNLOAD_MODE=presigned (текущее поведение / без nginx):
  GET download -> 307 Location=<полный presigned URL>
```

### Почему presigned query внутри X-Accel

Docx §25 показывает `proxy_set_header Authorization ""` и путь вида `/internal-s3/media/users/42/report.pdf`. Это ок, если объект читается без подписи (публичный префикс / отдельная политика). У нас бакет полностью приватный → MinIO вернёт 403 без SigV4.

Варианты:

| Вариант | Плюс | Минус |
|---------|------|-------|
| **A. Presigned query в X-Accel URI** (берём) | Переиспользуем `S3Storage.generate_presigned_url`; бакет остаётся private | Query длинный; TTL всё ещё важен |
| B. Nginx AWS auth (lua / модуль) | Подпись на стороне nginx | Новый стек, сложнее образ |
| C. Открыть GetObject с внутренней сети | «Простой» proxy_pass | Легко промахнуться политикой; MinIO/AWS модели разные |

Выбор: **A**.

Алгоритм в сервисе:

1. Как сейчас: найти ready attachment, проверить owner → иначе 404.
2. `url = await s3.generate_presigned_url(get_object, ..., ExpiresIn=get_ttl)`.
3. Вырезать `path + query` из URL (без схемы/хоста).
4. Собрать `X-Accel-Redirect: {s3_x_accel_prefix}{path_and_query}`  
   где prefix = `/internal-s3/` и path уже содержит `/{bucket}/{key}` (path-style).
5. Вернуть `Response(200, headers=...)` без тела.

Важно: presigned URL должен быть подписан на **тот host/endpoint, который увидит MinIO** при запросе от nginx (`http://minio:9000` в docker-сети), а не на `localhost:9000` с хоста. Иначе SignatureDoesNotMatch.

→ В конфиге нужен явный **внутренний** endpoint для подписи download под X-Accel, отдельно от endpoint, который видит браузер при PUT:

| Env | Назначение |
|-----|------------|
| `S3_ENDPOINT_URL` | Как сейчас: для API→S3 ops и **presigned PUT** (клиентский host) |
| `S3_X_ACCEL_ENDPOINT_URL` | Host:port, под который подписываем GET для nginx→MinIO (dev: `http://minio:9000`) |

Если `ATTACHMENT_DOWNLOAD_MODE=presigned` — подпись как сейчас на `S3_ENDPOINT_URL`.  
Если `x_accel` — GET подписываем на `S3_X_ACCEL_ENDPOINT_URL`, в заголовок кладём path+query.

---

## Nginx (dev)

### Файлы

```text
docker/nginx/
  Dockerfile          # опционально; можно nginx:1.27-alpine + mount conf
  nginx.conf          # или conf.d/default.conf
```

### Минимальный `nginx.conf` (идея)

```nginx
upstream api {
    server host.docker.internal:8000;  # uvicorn на хосте; в prod — app:8000
    keepalive 32;
}

server {
    listen 8080;
    server_name _;

    # API: JSON/auth, тела маленькие (presigned upload)
    location / {
        client_max_body_size 16k;          # §26: не раздувать глобально
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection        "";
        proxy_pass http://api;
    }

    # §25: только internal redirect из X-Accel-Redirect
    location /internal-s3/ {
        internal;
        proxy_pass http://minio:9000/;
        proxy_set_header Authorization "";
        proxy_set_header Host $proxy_host;
        proxy_hide_header x-amz-id-2;
        proxy_hide_header x-amz-request-id;
        proxy_hide_header x-amz-request-id-2;
        # длинные скачивания
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
```

Грабли из §25, которые фиксируем в плане:

- **`internal` обязателен** — иначе обход auth одной строкой URL.
- Слэши в `location` / `proxy_pass` согласовать до выката (классика `proxy_pass` trailing slash).
- Тело ответа API — пустое.
- Не собирать redirect-path из `original_name` / user input.

### `docker-compose.yml`

```yaml
nginx:
  image: nginx:1.27-alpine
  container_name: task_manager_nginx
  ports:
    - "8080:8080"
  volumes:
    - ./docker/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
  extra_hosts:
    - "host.docker.internal:host-gateway"
  depends_on:
    minio:
      condition: service_healthy
```

API в compose пока нет — `upstream` на хост. Когда появится сервис `app`, заменить на `app:8000` и убрать `extra_hosts`.

---

## Изменения в приложении

| Слой | Файл | Что сделать |
|------|------|-------------|
| Config | `src/core/config.py`, `.env.example` | `attachment_download_mode`, `s3_x_accel_endpoint_url`, `s3_x_accel_prefix` (`/internal-s3`) |
| Service | `src/services/attachment.py` | ветка download: presigned 307 vs X-Accel headers; подпись GET на нужный endpoint |
| S3 | `src/core/s3.py` | либо второй клиент/метод presign с override `endpoint_url`, либо утилита «переподписать/собрать URL под internal host» (предпочтительно: отдельный short-lived client или параметр endpoint при generate — **без** второго долгоживущего пула, если botocore позволяет подпись локально с другим endpoint) |
| API | `src/api/v1/attachments.py` | при `x_accel`: `Response` 200 + заголовки; при `presigned`: текущий `RedirectResponse` 307 |
| Models | `src/models/attachments.py` | при необходимости DTO `DownloadAccelResult` (url path / headers) |

### Контракт download

| Mode | Status | Заголовки |
|------|--------|-----------|
| `presigned` | 307 | `Location`, `Cache-Control: no-store` |
| `x_accel` | 200 | `X-Accel-Redirect`, `Content-Type`, `Content-Disposition`, `Cache-Control: no-store` |

Публичный URL эндпоинта тот же: `GET .../attachments/{id}/download`.

---

## Шаги реализации

### Шаг 1 — nginx reverse proxy в Docker

- [ ] `docker/nginx/nginx.conf` (upstream API + `/internal-s3/`)
- [ ] сервис `nginx` в `docker-compose.yml`
- [ ] README: «API через http://localhost:8080»
- [ ] Ручная проверка: `curl -H "Authorization: ..." http://localhost:8080/v1/...` → JSON как напрямую с :8000

### Шаг 2 — конфиг + сервис X-Accel

- [ ] Env / `Configs`
- [ ] Логика сборки `X-Accel-Redirect` + подпись на `S3_X_ACCEL_ENDPOINT_URL`
- [ ] API response branch
- [ ] Default: dev может оставить `presigned` до поднятого nginx; в compose-доке рекомендовать `x_accel`

### Шаг 3 — тесты

- [ ] Unit/service: при `x_accel` заголовок начинается с `/internal-s3/`, есть query `X-Amz-Signature`, нет утечки `s3_endpoint` в Location
- [ ] API: 200 + `X-Accel-Redirect` (без follow через реальный nginx — достаточно заголовков)
- [ ] API: foreign → 404; pending → 409 (как сейчас)
- [ ] Режим `presigned` — старые тесты 307 не краснеют
- [ ] (Опционально) compose smoke: curl через nginx получает байты файла

### Шаг 4 — документация / правила

- [ ] Статус-таблица в этом файле → ✅
- [ ] [s3_dev.md](../s3/s3_dev.md): download — ссылка сюда; убрать «X-Accel вне MVP»
- [ ] [index.md](../../index.md) — пункт nginx
- [ ] README TODO #3 — частично: proxy + X-Accel; limits/SSE отдельно

---

## Конфиг (черновик)

| Ключ | Default | Комментарий |
|------|---------|-------------|
| `ATTACHMENT_DOWNLOAD_MODE` | `presigned` | `presigned` \| `x_accel` |
| `S3_X_ACCEL_ENDPOINT_URL` | `http://minio:9000` | host для SigV4 GET под nginx |
| `S3_X_ACCEL_PREFIX` | `/internal-s3` | должен совпадать с `location` в nginx |
| `S3_PRESIGNED_GET_TTL_SEC` | `120` | без изменений |

---

## Область плана

| Входит | Не входит |
|--------|-----------|
| nginx в compose, proxy на API | TLS / Let's Encrypt |
| `internal` proxy на MinIO | Раздача файлов с диска (`alias`) |
| X-Accel download для attachments | Смена upload на proxy через nginx |
| Feature flag download mode | Закрытие публичного порта MinIO |
| Тесты заголовков / регрессия download | limit_req, limit_conn, real_ip, dry_run |
| | Redis rate limit (§12–§19) |
| | SSE/WebSocket tuning |
| | CDN перед nginx |

---

## Риски и грабли

| Риск | Как не словить |
|------|----------------|
| SignatureDoesNotMatch | Подпись GET на тот же endpoint/host, с которого nginx ходит в MinIO |
| Обход `/internal-s3/` | Только `internal;`; smoke: `curl localhost:8080/internal-s3/...` → 404 |
| Path traversal в redirect | Только `storage_key` из БД + bucket из конфига |
| Тесты без nginx зелёные, в compose 403 | Прогнать один ручной/smoke download через :8080 |
| `Content-Disposition` сломан | Как сейчас: `quote` / `filename*` |
| Двойной Trailing slash → кривой ключ | Зафиксировать пример реального `X-Accel-Redirect` в тесте-фикстуре |
| HTTP/2 + будущий limit_conn | Не включать limit_conn на API (§23); только когда будет files-location отдельно |

---

## Критерии готовности

- [ ] `curl` download через nginx отдаёт тело файла, в ответе API-этапа был X-Accel (в access log nginx — internal redirect)
- [ ] Прямой GET `/internal-s3/...` снаружи → 404
- [ ] Presigned-режим и существующие attachment-тесты живы
- [ ] Upload по-прежнему напрямую в MinIO
- [ ] План и index обновлены

---

## Вне скоупа → следующие планы

1. **`nginx_limits_dev.md`** — `limit_req` / `limit_req_status 429` / zones login vs api / dry_run (§22, §27), `real_ip` (§24).
2. **SSE/WebSocket proxy** — buffering off, timeouts (notifications + будущий chat).
3. **Закрыть MinIO с хоста** — только docker-network + (если нужен browser PUT) отдельный nginx location или остаться на presigned с публичным endpoint.

---

## Итог выбора (из docx)

| Способ | Трафик | У нас |
|--------|--------|-------|
| Через приложение | client → nginx → worker → S3 | не берём |
| Presigned GET 307 | client → S3 напрямую | было / fallback |
| X-Accel-Redirect | client → nginx → S3 | **цель этого плана** |
