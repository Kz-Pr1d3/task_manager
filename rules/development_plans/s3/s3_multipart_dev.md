# План: Multipart upload (вложения > 100 MiB)

Расширение [s3_dev.md](s3_dev.md) по **§10** спецификации [S3_Redis_Nginx.docx](../S3_Redis_Nginx.docx). Single PUT остаётся для файлов ≤ 100 MiB; multipart — отдельный API-путь.

Стек тот же: FastAPI + asyncpg + aiobotocore + MinIO. Фронт вне скоупа — контракт API + тесты.

Связанные: [s3_dev.md](s3_dev.md), [db.mdc](../../db/db.mdc), [tasks_dev.md](../tasks/tasks_dev.md).

---

## Статус реализации (код)

Обновлено: 2026-10-03.

| Область | Статус | Что есть |
|---------|--------|----------|
| Решения / контракт API | ✅ | этот документ |
| DDL `s3_upload_id` / `part_size` | ❌ | |
| `S3Storage` multipart ops | ❌ | |
| Service initiate / resign / complete / abort | ❌ | |
| API endpoints | ❌ | |
| Cleanup: abort incomplete | ❌ | pending cleanup есть, abort multipart — нет |
| Лимиты конфиг (300 MiB / threshold / part 16 MiB) | ❌ | сейчас `attachment_max_bytes=10 MiB` |
| Lifecycle AbortIncomplete (prod JSON) | 🟡 | MinIO: `STALE_UPLOADS_EXPIRY`; AWS rule — добавить в lifecycle |
| CORS `ExposeHeaders: ETag` | ✅ | `scripts/minio/cors.json` уже есть |
| Тесты | ❌ | |

**Этап:** план зафиксирован, реализация не начата.

---

## Решения (зафиксировано)

| Вопрос | Решение | Основание |
|--------|---------|-----------|
| Порог multipart | `size_bytes > 100 MiB` | §10: ~100 МБ; мелочь — single PUT |
| Max размер файла | **300 MiB** | **рандомное число** (продуктовый потолок «на сейчас», не из AWS/спеки); меняется конфигом |
| Single PUT max | **100 MiB** (порог inclusive: `≤ 100 MiB` → PUT) | ниже порога multipart |
| MIME | текущий whitelist (jpeg/png/webp/pdf), **расширяемый** | продукт; S3 требует только match Content-Type в подписи |
| Квота файлов | 5 на задачу; **pending сразу** в счётчике | как сейчас |
| `create_multipart_upload` | только бэкенд | §10 + ключ только сервер (§1, §7) |
| Presigned part URL | **все сразу** при initiate | мало частей при 300 MiB / 16 MiB |
| Re-sign | отдельный endpoint на выбранные `part_number` | TTL истёк mid-upload |
| Complete | клиент → `{parts:[{part_number, etag}]}` → бэкенд `complete_multipart_upload` | §10 + §7 «клиенту не верить» |
| ETag parts | ведёт **клиент**; в БД не кладём; **не** `list_parts` для complete | §10 грабля |
| Ключи | `tmp/pending/...` → copy → `users/...` | как s3_dev |
| Size guard | `head_object` после complete; **не** Conditions/POST policy | Conditions только §8 POST; multipart part — PUT-like |
| Abort | API `abort` + cleanup worker зовёт `abort_multipart_upload` + lifecycle 7d | §10, §11 |
| DDL | `s3_upload_id`, `part_size` | нужен для abort/resign/complete |
| Part size | фиксированные **16 MiB** (конфиг) | см. § «Расчёт part_size» ниже |
| Concurrency parts | на стороне клиента | §10 разрешает параллель, число не нормирует |
| Endpoint | **отдельный** от single PUT `/upload` | не ломать текущий контракт |
| Status в БД | `pending` (без нового enum) | отличие: `s3_upload_id IS NOT NULL` |

---

## Лимиты

| Параметр | Значение | Config |
|----------|----------|--------|
| Max файл (продукт) | 300 MiB (**рандом**, не канон AWS) | `attachment_max_bytes = 314_572_800` |
| Single PUT ceiling | 100 MiB | `attachment_multipart_threshold_bytes = 104_857_600` |
| Multipart | `threshold < size ≤ max` | иначе 413 / 422 |
| Part size | 16 MiB (см. расчёт ниже) | `attachment_part_size_bytes = 16_777_216` |
| Max parts (S3) | 10 000 | при 300/16 ≈ **19** parts — запас |
| Min part (S3) | 5 MiB (кроме last) | last может быть меньше |
| TTL part URL | 3600 с (отдельно от PUT 600) | `s3_presigned_part_ttl_sec` |
| MIME | jpeg/png/webp/pdf | `ALLOWED_MIME_SUFFIX`, расширять по необходимости |
| Файлов на задачу | 5 | без изменений |

Маршрутизация на клиенте (бэкенд валидирует):

```text
size ≤ 0                    → 422
size ≤ 100 MiB              → POST .../upload          (single PUT)
100 MiB < size ≤ 300 MiB    → POST .../upload/multipart
size > 300 MiB              → 413
```

Если клиент ударил multipart с `size ≤ threshold` → **422** (лишняя сложность, §10).  
Если single PUT с `size > threshold` → **413** или 422 «use multipart» — зафиксировать **422** с явным detail.

---

## Что должно работать

- Файл 100 MiB < size ≤ 300 MiB грузится частями напрямую в MinIO/S3, без прокси через FastAPI.
- Initiate: квоты, MIME, ключ, `create_multipart_upload`, N presigned `upload_part` URL.
- Клиент заливает parts (можно параллельно), копит ETag, при протухании URL — resign.
- Complete: бэкенд склеивает по parts+ETag, `head_object` (size/Content-Type), copy в final, `ready`.
- Abort / timeout / cleanup: `abort_multipart_upload`, строка `failed` или delete; lifecycle добивает брошенные.
- Single PUT путь (`/upload` + `/complete`) не ломается; его ceiling поднимается до 100 MiB.

---

## Архитектура

```text
Initiate:
  POST /tasks/{id}/attachments/upload/multipart
    -> auth, task owner, count < 5, MIME, threshold < size ≤ max
    -> key = tmp/pending/{user_id}/{uuid}{ext}
    -> create_multipart_upload(Key, ContentType)
    -> INSERT pending (s3_upload_id, part_size, size_bytes=declared)
    -> parts_count = ceil(size / part_size)
    -> generate_presigned_url(upload_part) × parts_count
    -> { id, s3_upload_id, part_size, parts_count, expires_in,
         parts: [{ part_number, url }, ...] }

Upload (клиент → S3):
  PUT parts[i].url  (Body = slice)
  сохранить ETag из ответа (нужен ExposeHeaders)

Re-sign (опц.):
  POST .../{attachment_id}/multipart/resign
    body: { part_numbers: [2, 5] }
    -> те же UploadId/Key, новые URL только на эти номера

Complete:
  POST .../{attachment_id}/multipart/complete
    body: { parts: [{ part_number, etag }, ...] }
    -> validate pending + s3_upload_id, parts 1..N без дыр
    -> complete_multipart_upload(UploadId, Parts)
    -> head_object: ContentLength ≤ max, ContentType match
    -> copy tmp → users/... ; delete tmp
    -> status=ready, size_bytes=head, s3_upload_id=NULL (или оставить)

Abort:
  POST .../{attachment_id}/multipart/abort
    -> abort_multipart_upload
    -> DELETE row / status=failed + delete best-effort
```

**Не делаем:** `list_parts` для сборки complete; Conditions/content-length-range на parts; прокси байтов через API.

---

## DDL

В `db/scripts/init.sql` (+ ручной `ALTER` на существующий volume):

```sql
ALTER TABLE task_attachment
    ADD COLUMN IF NOT EXISTS s3_upload_id TEXT,
    ADD COLUMN IF NOT EXISTS part_size BIGINT;

-- part_size только для multipart pending/in-flight; после ready можно NULL
ALTER TABLE task_attachment
    DROP CONSTRAINT IF EXISTS task_attachment_part_size_check;
ALTER TABLE task_attachment
    ADD CONSTRAINT task_attachment_part_size_check
    CHECK (part_size IS NULL OR part_size > 0);
```

Инвариант в service (не обязательно CHECK):

- single PUT: `s3_upload_id IS NULL`, `part_size IS NULL`;
- multipart pending: оба NOT NULL;
- после ready: `s3_upload_id` очистить (abort больше не нужен); `part_size` можно NULL.

Обновить [db.mdc](../../db/db.mdc) после внедрения.

---

## Конфигурация

| Поле | Default | Примечание |
|------|---------|------------|
| `attachment_max_bytes` | `314572800` | 300 MiB (**меняет** текущие 10 MiB) |
| `attachment_multipart_threshold_bytes` | `104857600` | 100 MiB; multipart если `>` |
| `attachment_part_size_bytes` | `16777216` | 16 MiB ≥ 5 MiB |
| `s3_presigned_part_ttl_sec` | `3600` | отдельно от PUT 600 |
| `s3_presigned_put_ttl_sec` | `600` | без изменений (single) |

`.env.example` / README — блок multipart.

---

## Код: слои

| Слой | Изменения |
|------|-----------|
| `src/core/s3.py` | `create_multipart_upload`, `generate_presigned_url(upload_part)`, `complete_multipart_upload`, `abort_multipart_upload` |
| `src/core/config.py` | поля выше; поднять `attachment_max_bytes` |
| `src/models/attachments.py` | request/response multipart + PartETag |
| `src/repository/attachment.py` | create с `s3_upload_id`/`part_size`; clear upload_id on ready; list stale с upload_id |
| `src/services/attachment.py` | initiate/resign/complete/abort multipart; single PUT ceiling = threshold |
| `src/services/attachment_cleanup.py` | для pending с `s3_upload_id` → `abort_multipart_upload` перед delete row |
| `src/api/v1/attachments.py` | 4 новых роута |
| `scripts/minio/lifecycle.json` | для prod S3: правило `AbortIncompleteMultipartUpload` Days=7 (MinIO по-прежнему env) |

### Расчёт part_size

Ограничения S3 (§10): part ∈ **[5 MiB … 5 GiB]** (кроме last), parts ≤ **10 000**.  
Док: *«размер части считают от размера файла»* — формулы константы AWS не даёт.

**Как выбрали 16 MiB (зафиксированный метод):**

1. Берём продуктовый max: `M = attachment_max_bytes` (сейчас 300 MiB, рандом).
2. Нижняя граница S3: `MIN_PART = 5 MiB`. При `part_size = MIN_PART` → `ceil(M / MIN_PART) = 60` parts — работает, но много round-trip.
3. Верхняя граница «ещё удобно»: не раздувать part до десятков MiB без нужды; степень двойки удобна для слайсов.
4. Фиксируем константу `PART = 16 MiB = 16 * 1024 * 1024`:
   - `PART ≥ MIN_PART` ✓
   - `parts_count(M) = ceil(M / PART) ≈ 19` ≪ 10 000 ✓
   - меньше запросов, чем при 5 MiB (60 → 19), JSON initiate с URL остаётся коротким
5. Динамику `max(5 MiB, ceil(M / 10000))` **не** используем: при M ≤ 300 MiB она всегда схлопывается в 5 MiB; фиксированная константа проще и предсказуемее для клиента.

Если поднимем `attachment_max_bytes`, пересчитать:

```text
parts_count_at_max = ceil(attachment_max_bytes / attachment_part_size_bytes)
# должно быть ≤ 10000; иначе увеличить part_size (кратно, ≥ 5 MiB)
```

**Формула на initiate (код):**

```python
part_size = settings.attachment_part_size_bytes  # 16 MiB
parts_count = (size_bytes + part_size - 1) // part_size
last_part = size_bytes - part_size * (parts_count - 1)  # может быть < 5 MiB — ок
```

Клиент **обязан** резать ровно так. Иначе complete с другим N → 422.

### Complete: валидация parts

1. Отсортировать по `part_number`.
2. Ровно `1..parts_count`, без дыр и дублей.
3. ETag непустой (нормализовать кавычки — S3 иногда отдаёт `"\"abc\""`).
4. `complete_multipart_upload`.
5. `head_object`: length ≤ `attachment_max_bytes`, length ≈ declared (допуск? — **строго ≤ max**; расхождение с declared > 0 при oversize уже поймает max; under-size — разрешить, писать факт из head).
6. Content-Type match с записью.
7. Copy + delete tmp + mark ready; при ошибке после complete — объект уже в tmp: delete_object / mark failed.

### Abort / cleanup

- Явный abort API.
- Worker: stale pending + `s3_upload_id` → abort (ignore NoSuchUpload) → delete row.
- Lifecycle: AbortIncomplete 7d (prod JSON); MinIO `MINIO_API_STALE_UPLOADS_EXPIRY=168h` уже в compose.

---

## HTTP API

Префикс: `/api/v1/tasks/{task_id}/attachments` (auth как у tasks).  
Ответы с URL: `Cache-Control: no-store`.

| Метод | Путь | Тело | Ответ |
|-------|------|------|-------|
| POST | `/upload/multipart` | `{ filename, content_type, size_bytes }` | см. ниже |
| POST | `/{id}/multipart/resign` | `{ part_numbers: int[] }` | `{ parts, expires_in }` |
| POST | `/{id}/multipart/complete` | `{ parts: [{ part_number, etag }] }` | `TaskAttachment` ready |
| POST | `/{id}/multipart/abort` | — | 204 |

### Initiate response (черновик)

```json
{
  "id": 42,
  "s3_upload_id": "...",
  "part_size": 16777216,
  "parts_count": 19,
  "content_type": "application/pdf",
  "expires_in": 3600,
  "parts": [
    { "part_number": 1, "url": "https://..." },
    { "part_number": 2, "url": "https://..." }
  ]
}
```

Ошибки: 404 (задача/чужое), 409 (лимит 5), 413 (> max), 422 (MIME / size ≤ threshold на multipart / битые parts), 409 (complete когда upload уже aborted / объект невалиден).

Существующие `POST /upload` и `POST /{id}/complete` — без изменения формы; только ceiling size → threshold.

---

## Порядок внедрения (чеклист)

### Шаг 1 — Config + S3Storage

- [ ] Поля конфига + `.env.example`
- [ ] Методы multipart в `S3Storage`
- [ ] Smoke против MinIO: create → 2 parts → complete → head → abort path

### Шаг 2 — DDL + repository

- [ ] Колонки `s3_upload_id`, `part_size` в `init.sql` + заметка ALTER
- [ ] Repo: create multipart pending, clear upload_id, stale с upload_id
- [ ] Обновить `db.mdc`

### Шаг 3 — Service

- [ ] `initiate_multipart_upload`
- [ ] `resign_parts`
- [ ] `complete_multipart_upload` (validate parts → S3 complete → head → copy)
- [ ] `abort_multipart_upload`
- [ ] Single PUT: max = threshold; отклонять size > threshold

### Шаг 4 — API

- [ ] 4 роута + OpenAPI
- [ ] no-store на JSON с URL

### Шаг 5 — Cleanup + lifecycle

- [ ] Worker abort перед удалением pending
- [ ] Prod `lifecycle.json`: AbortIncompleteMultipartUpload 7d (док для AWS/Yandex)
- [ ] Метрики: опц. counter abort / multipart complete

### Шаг 6 — Тесты

- [ ] S3 smoke multipart (skip if MinIO down)
- [ ] Service: size ≤ threshold → 422; oversize head → abort/delete; bad parts → 422
- [ ] API: auth, квота 5, resign, abort
- [ ] Cleanup вызывает abort

### Шаг 7 — Docs

- [ ] Статус в этом файле
- [ ] Ссылка/лимиты в [s3_dev.md](s3_dev.md) и [index.md](../../index.md)
- [ ] README: dual path PUT vs multipart

---

## Риски

| Риск | Митигация |
|------|-----------|
| Клиент шлёт чужие/пустые ETag | S3 complete падает → 409; не mark ready |
| `list_parts` для complete | запрещено планом и §10 |
| Part URL TTL при медленной сети | resign; TTL part 3600 |
| Incomplete parts тарифицируются | abort API + worker + lifecycle |
| Поднять max single до 100 MiB | nginx `client_max_body_size` не участвует (presigned); ок |
| ETag с кавычками | нормализовать перед complete |
| Complete успешен, copy упал | объект в tmp; retry copy или failed + delete; lifecycle подстрахует tmp |

---

## Вне скоупа

- Фронтенд / SDK UI
- Resumable через сохранение ETag на сервере
- Parallelism caps / rate limit (Часть II Redis)
- Presigned POST вместо multipart
- Видео/zip MIME — только расширение whitelist по отдельному решению
- Превью, антивирус, CDN

---

## После реализации

- Обновить «Статус реализации» здесь
- Поправить лимиты MVP в [s3_dev.md](s3_dev.md) (10 → dual: 100 PUT / 300 multipart)
- Колонки в [db.mdc](../../db/db.mdc)
- Ссылка уже в [index.md](../../index.md)
