# План: публичный префикс `/api` + auth в v1

Все прикладные HTTP-роуты живут под `/api/v1`, включая auth: `/api/v1/auth/*`, `/api/v1/lists/*`, … Зачем: свободный `/` для будущей SPA, нормальный `location /api/` в nginx, одна версия для всего API (auth не сирота снаружи `/v1`).

Это **смена публичного URL**, не rewrite в nginx. TestClient и клиент за `:8080` видят одни и те же пути. Старых `/auth`, `/api/auth`, `/v1` не оставляем.

Связанные: [nginx_dev.md](nginx/nginx_dev.md) (закрыт), [nginx_sse_dev.md](nginx/nginx_sse_dev.md) (**после** этого плана — SSE location станет `/api/v1/notifications/stream`), [auth_dev.md](auth_dev.md), [tasks/](tasks/index.md), [notifications/](notifications/index.md).

Внешних клиентов нет → breaking cut без 301.

---

## Статус реализации (код)

Обновлено: 2026-10-29.

| Область | Статус | Что есть |
|---------|--------|----------|
| Решения / контракт | ✅ | этот документ |
| Prefix `/api` + auth в `v1_router` | ✅ | `src/api/v1/auth.py`, include в `v1/router.py`; `main.py` `prefix="/api"` |
| OpenAPI/docs под `/api` | ✅ | `/api/docs`, `/api/redoc`, `/api/openapi.json` |
| nginx `location /api/` | ✅ | `location /api/`, `proxy_pass http://api;` без URI; `/` и `/internal-s3/` живы |
| Тесты HTTP-пути | ✅ | `API_PREFIX="/api"`; 404 на `/auth`, `/api/auth`, `/v1`; smoke probe `/health` |
| Документация (структура, README, планы-факты) | ✅ | `project_structure.py`, README, auth/tasks/notifications, nginx_sse path |

**Этап:** шаги 1–4 ✅. План закрыт; дальше — [nginx_sse_dev.md](nginx/nginx_sse_dev.md).

**Порядок:** этот план → потом [nginx_sse_dev.md](nginx/nginx_sse_dev.md). Иначе SSE-location сядет на старый path.

---

## Решения (зафиксировано)

| Вопрос | Решение | Обоснование |
|--------|---------|-------------|
| Где префикс `/api` | `include_router(v1_router, prefix="/api")` в `main.py` | nginx не стрипает; отдельный parent-router не нужен — под `/api` только v1 |
| `root_path="/api"` | **Не ставить** | `root_path` — для proxy, который **съедает** prefix. Мы не съедаем |
| nginx `proxy_pass` | `http://api;` **без** URI (`http://api/` со слэшем стрипает `/api` → uvicorn увидит `/v1/...` → 404) | полный путь доходит до FastAPI |
| Auth URL | `/api/v1/auth/sign-up\|sign-in\|refresh\|logout` | тот же versioned API, что lists/tasks; не `/api/auth` и не корень |
| Auth файл | `src/api/auth.py` → `src/api/v1/auth.py`; include в `v1/router.py` | слой = URL; из `main.py` auth пропадает |
| `auth_router` prefix | оставить `prefix="/auth"` | итог `/api` + `/v1` + `/auth` |
| `GET /health` | **корень**, не под `/api` | liveness для compose/k8s; не часть публичного API |
| `GET /metrics` | **корень** | scrape Prometheus; уже `mount("/metrics")` |
| OpenAPI | `/api/docs`, `/api/redoc`, `/api/openapi.json` | будущий `location /` = SPA; один nginx `location /api/` закрывает docs+API |
| Старые URL | **404**, без редиректа | нет внешних клиентов; редирект копить нечего |
| `deep_link` | не трогать (`/tasks/{id}`) | это путь **фронта**, не API. [deadline_reminders.py](../../src/services/deadline_reminders.py) |
| X-Accel `/internal-s3/` | не трогать | nginx-only, не FastAPI |
| Upload presigned PUT | не трогать | клиент → MinIO напрямую |
| SSE buffering / timeout 1h | **не этот план** | [nginx_sse_dev.md](nginx/nginx_sse_dev.md), path после этого плана: `/api/v1/notifications/stream` |
| Дубль `include_router(auth_router)` в `main.py` | оба include уходят | auth только через `v1_router` |

### Карта URL после

```text
/health                         liveness
/metrics                        prometheus (если enable_metrics)
/api/docs  /api/redoc  /api/openapi.json
/api/v1/auth/sign-up|sign-in|refresh|logout
/api/v1/lists/...
/api/v1/tasks/...
/api/v1/tasks/{id}/attachments/...
/api/v1/notifications/...
/api/v1/notifications/sse-ticket
/api/v1/notifications/stream    SSE (настройки nginx — следующий план)

/internal-s3/...                nginx internal, как сейчас
```

### Как вешаем в FastAPI

Не размазывать `prefix="/api"` по файлам. `v1_router` остаётся `prefix="/v1"`, `auth_router` — `prefix="/auth"`.

```python
# src/api/v1/auth.py  (переезд из src/api/auth.py)
auth_router = APIRouter(prefix="/auth")

# src/api/v1/router.py
v1_router.include_router(auth_router)  # вместе с lists/tasks/...

# src/main.py — без import auth_router
self.app = FastAPI(
    ...,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
self.app.include_router(router=v1_router, prefix="/api")
```

Итог: `/api` + `/v1` + `/auth/sign-up` → `/api/v1/auth/sign-up`.

`@app.get("/health")` и `mount("/metrics")` без изменений. `src/api/auth.py` удалить после переезда (единственный импорт сейчас — `main.py`).

---

## Nginx (этот план — только группировка)

`location /` сейчас проксирует всё. Добавляем более специфичный `/api/`, настройки JSON **как у текущего `/`** (не buffering off, не timeout 1h).

```nginx
location /api/ {
    client_max_body_size 16k;
    proxy_http_version 1.1;
    proxy_set_header Host              $http_host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection        "";
    proxy_pass http://api;    # БЕЗ URI — не резать /api
}

location / {
    # /health, /metrics; пока нет SPA — можно оставить тем же proxy
    ...
}

location /internal-s3/ { ... }  # без изменений
```

`location /api/` (со слэшем) не матчит `/apiary`. `/api` без хвоста нам не нужен.

Пока SPA нет, `location /` остаётся catch-all на uvicorn — `/health` и мусорный `/v1/...` (старый URL) тоже уйдут в приложение → 404 от FastAPI. Это ок.

Не делать в этом плане: SSE-директивы, `limit_req`, закрытие `/` под static.

---

## Тесты

Слои не смешиваем: default pytest = `TestClient`, nginx не нужен. Меняются **строки путей**, не фикстуры и не маркеры.

### Что трогать

| Файл | Сейчас | Станет |
|------|--------|--------|
| `tests/conftest.py` | нет константы | `API_PREFIX = "/api"` |
| `tests/api/test_attachments.py` | хелперы `/v1/tasks/...` | `f"{API_PREFIX}/v1/tasks/..."` |
| `tests/api/test_notifications.py` | `/v1/notifications/...` | через `API_PREFIX` |
| `tests/api/test_notification_stream.py` | `/v1/notifications/stream\|sse-ticket` | через `API_PREFIX` |
| `tests/api/test_health_check.py` | `/health` | **без изменений** |
| `tests/smoke/nginx_download_flow.py` | `/auth/...`, `/v1/tasks/...`; probe `/docs` | `/api/v1/auth/...`, `/api/v1/tasks/...`; probe **`/health`** |
| `tests/middleware/test_metrics.py` | свой мини-app `/lists/{id}` | не трогать |

Repo/service/core — HTTP-путей нет, кроме `deep_link="/tasks/1"`. Не менять.

### Контракт cut

API-тесты на **404** (не 401) — старые префиксы мертвы:

- `POST /auth/sign-in`
- `POST /api/auth/sign-in` (промежуточный вариант, который не берём)
- `GET /v1/lists/`

Имена: `test__old_auth_path__not_found`, `test__unversioned_api_auth_path__not_found`, `test__old_v1_path__not_found`.

### Что не делать

- Не переводить `client` на `:8080`.
- Не оставлять алиасы старых путей «на переходный период».
- Не мокать роутер.
- Smoke по-прежнему `@pytest.mark.smoke`; `addopts = -m 'not smoke'` не трогать.

После шага 1 default `pytest` обязан быть зелёным: все HTTP-тесты либо обновлены, либо 404-контракт.

---

## Шаги реализации

### Шаг 1 — FastAPI

- [x] Переезд `src/api/auth.py` → `src/api/v1/auth.py`; `v1_router.include_router(auth_router)`
- [x] `main.py`: `include_router(v1_router, prefix="/api")`; оба include `auth_router` убрать
- [x] `docs_url` / `redoc_url` / `openapi_url` под `/api/...`
- [x] `/health`, `/metrics` на месте

### Шаг 2 — тесты

- [x] `API_PREFIX` в `tests/conftest.py`
- [x] Все api/smoke пути
- [x] 404 на старые `/auth`, `/api/auth`, `/v1`
- [x] smoke probe → `/health`
- [x] `pytest` зелёный

### Шаг 3 — nginx

- [x] `location /api/` = копия текущего JSON-proxy, `proxy_pass http://api;`
- [x] `/` и `/internal-s3/` живы
- [x] `nginx -t` + reload
- [x] Ручной: `curl :8080/api/v1/auth/sign-in`; `curl :8080/api/v1/lists/` с Bearer; `curl :8080/health`; `curl :8080/auth/sign-in` и `/v1/lists/` → 404; `curl :8080/internal-s3/x` → 404
- [x] `pytest -m smoke` (download) — если стек поднят

### Шаг 4 — документация

- [x] Статус-таблица этого файла → ✅
- [x] [project_structure.py](../basics/project_structure.py) — эндпоинты `/api/v1/auth`, дерево `api/v1/auth.py`
- [x] README curl / upload path
- [x] [auth_dev.md](auth_dev.md), [tasks_tech.md](tasks/tasks_tech.md), [notifications_mvp.md](notifications/notifications_mvp.md) — факт-пути
- [x] [nginx_sse_dev.md](nginx/nginx_sse_dev.md) — path `/api/v1/notifications/stream` (черновик уже правим вместе с этим планом)
- [x] [index.md](index.md)

---

## Область плана

| Входит | Не входит |
|--------|-----------|
| Prefix `/api` + auth в v1 (URL и файл) | Алиасы/301 со старых URL |
| Docs под `/api` | SSE `proxy_buffering off` / timeout 1h |
| nginx `location /api/` без strip | SPA на `location /` |
| Тесты путей + 404 old | Смена `deep_link` |
| | `root_path`, закрытие MinIO :9000 |
| | WebSocket, limit_req |

---

## Риски и грабли

| Риск | Как не словить |
|------|----------------|
| `proxy_pass http://api/;` (со слэшем) | uvicorn получит `/v1/...` без `/api` → 404 на «правильном» клиентском URL |
| `root_path="/api"` + реальный prefix | OpenAPI нарисует `/api/api/v1` |
| Забыть smoke `/api/v1/auth/sign-up` (останется `/auth` или `/api/auth`) | download smoke красный |
| Probe остался `/docs` | после переноса docs — ложный 404 «стек мёртв» |
| Поменять `deep_link` на `/api/v1/tasks` | сломает фронтовый контракт, который ещё не написан, но тесты сервиса зелёные зря |
| Сделать SSE-location в этом же PR | смешает два плана; buffering/timeout легко забыть отдельно |
| Оставить дубль auth include | два одинаковых роута, путаница в OpenAPI |

---

## Критерии готовности

- [x] `GET /api/docs` открывается, в схеме `/api/v1/auth` и `/api/v1/lists`
- [x] `GET /health` как было
- [x] `POST /auth/...`, `POST /api/auth/...`, `GET /v1/...` → 404
- [x] `pytest` зелёный; smoke download через `:8080/api/v1/...`
- [x] nginx `location /api/` есть, `/internal-s3/` не сломан
- [x] [nginx_sse_dev.md](nginx/nginx_sse_dev.md) ссылается на `/api/v1/notifications/stream`

---

## Вне скоупа → следующие планы

1. **[nginx_sse_dev.md](nginx/nginx_sse_dev.md)** — buffering off + 1h на `/api/v1/notifications/stream`.
2. **SPA** — `location /` → static; `/health` и `/metrics` отдельными location.
3. **`nginx_limits_dev.md`** — `limit_req` на `/api/v1/` vs `/api/v1/auth/` vs SSE.

---

## Итог выбора

| Тема | Выбор |
|------|--------|
| Prefix | `/api` на `v1_router`; auth → `/api/v1/auth`, файл в `src/api/v1/` |
| nginx | `location /api/`, без strip |
| health/metrics | корень |
| docs | под `/api` |
| old URLs | 404 |
| SSE tuning | следующий план |
