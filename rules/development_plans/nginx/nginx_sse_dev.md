# План: Nginx SSE-safe proxy

Расширение [nginx_dev.md](nginx_dev.md) + [api_prefix_dev.md](../api_prefix_dev.md) ✅: nginx `:8080` уже проксирует `/api/` (без strip) и `/` (health/metrics). Этот план добавляет **SSE-location**, не трогая Python, TestClient и X-Accel.

Путь стрима (факт): **`/api/v1/notifications/stream`**. Auth: `/api/v1/auth/...`. Ticket: `/api/v1/notifications/sse-ticket`.

Спека-сниппет / [FastAPIRealtimeNotifications.md](../notifications/FastAPIRealtimeNotifications.md) §12 / [notifications_mvp.md](../notifications/notifications_mvp.md) «Proxy notes». FastAPI `EventSourceResponse` уже шлёт нужные заголовки.

Связанные: [api_prefix_dev.md](../api_prefix_dev.md) (закрыт), [nginx_dev.md](nginx_dev.md) (закрыт), [notifications_mvp.md](../notifications/notifications_mvp.md) (SSE ✅), будущий `nginx_limits_dev.md`.

---

## Статус реализации (код)

Обновлено: 2026-10-29.

| Область | Статус | Что есть |
|---------|--------|----------|
| Решения / контракт | ✅ | этот документ; prefix `/api` ✅ |
| `location` SSE в `docker/nginx/nginx.conf` | ❌ | факт: `/api/` + `/` + `/internal-s3/`; SSE-location нет |
| Явные `proxy_buffering off` / `gzip off` / timeout 1h | ❌ | FastAPI шлёт `X-Accel-Buffering: no`; явных директив нет |
| Контракт-тест `nginx.conf` (без docker) | ❌ | — |
| Smoke SSE через `:8080` | ❌ | есть smoke download (`/health` probe, `/api/v1/auth`, `/api/v1/tasks/...`) |
| Документация | ❌ | proxy notes → этот план; README ещё без `curl -N` |

**Этап:** решения ✅, шаги 1–4 не начаты. Prefix не блокер.

---

## Контекст: что уже работает

Факт `docker/nginx/nginx.conf` после api_prefix:

```text
Client → nginx :8080
          location /api/         → proxy_pass http://api;   # БЕЗ URI, не стрипать /api
          location /             → тот же proxy             # /health, /metrics
          location /internal-s3/ (internal) → minio:9000
```

Публичные пути приложения: `/api/v1/auth/*`, `/api/v1/lists|tasks|notifications/*`, `/api/docs`. Старые `/auth`, `/api/auth`, `/v1` — 404.

SSE-ticket и stream **уже** проксируются через `location /api/` (как любой JSON). Не хватает настроек долгого `text/event-stream` на stream. Дефолт nginx:

| Директива | Default | Эффект на SSE |
|-----------|---------|----------------|
| `proxy_buffering` | `on` | ответ копится в буфере; клиент увидит `ready` только когда буфер заполнится **или** стрим закроется (~15 мин) |
| `proxy_read_timeout` | `60s` | режется, если upstream молчит дольше 60s |
| `gzip` | `off` | сейчас ок; глобальный `gzip on` позже сломает SSE (сжимает = буферизует) |
| `proxy_cache` | выкл | сейчас ок; включение без исключения SSE — катастрофа |

FastAPI `EventSourceResponse` (`/api/v1/notifications/stream`) уже ставит:

```text
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
```

`X-Accel-Buffering: no` nginx **обрабатывает сам** и клиенту обычно **не отдаёт**. Это per-response выключение буфера. Явные директивы в conf всё равно нужны: не зависеть от заголовка (его могут спрятать/`proxy_ignore_headers`), зафиксировать timeout 1h, защититься от будущего `gzip on`.

Keepalive ping `EventSourceResponse` — каждые **15s**. `SSE_CONNECTION_MAX_SEC` = **15 мин**. Timeout nginx должен быть **строго больше** обоих.

---

## Решения (зафиксировано)

| Вопрос | Решение | Обоснование |
|--------|---------|-------------|
| «Проксировать все запросы» | Уже: `location /api/` + `/`. Этот план — только SSE-директивы | [api_prefix_dev.md](../api_prefix_dev.md) ✅ |
| Сниппет `location /api/` | Prefix уже есть; buffering/timeout — **не** на весь `/api/` | 1h на JSON прячет hung-upstream |
| Где buffering off + 1h | **Отдельный** `location ^~ /api/v1/notifications/stream` | приоритет `^~` над `/api/`; JSON fail-fast 60s |
| Альтернатива «намазать на весь `/api/`» | **Не берём** | Безвредно для маленького JSON, но прячет hung-upstream на час |
| `Host` | `$http_host`, **не** `$host` из сниппета | [nginx_dev.md](nginx_dev.md): `$host` теряет `:8080` в `Location` |
| `Connection` | `""` (как на `/api/` и `/`) | keepalive upstream; **не** `Upgrade` |
| Заголовки FastAPI | Не дублировать в приложении | `EventSourceResponse` уже корректный контракт |
| Код Python | **Не менять** | Только nginx.conf + тесты + доки |
| Upload | Без изменений, presigned PUT мимо nginx | [s3_dev.md](../s3/s3_dev.md) |
| Download / `/internal-s3/` | Без изменений | buffering off там уже есть; smoke download не должен покраснеть |
| WebSocket | Не в этом плане | Когда появится chat — отдельный `location` с `Upgrade` |
| TLS / HTTP/2 | Не в этом плане | prod; HTTP/2 полезен против лимита 6 conn HTTP/1.1, не блокер SSE |
| `limit_req` / `limit_conn` | Не в этом плане | `limit_conn` на SSE **убивает** длинные коннекты; оставить пометку для `nginx_limits_dev.md` |
| Тесты API на `:8080` | **Нет.** `TestClient` остаётся in-process | nginx — инфра; бизнес-логика SSE уже покрыта `tests/api/test_notification_stream.py` |

### Почему не весь `location /api/`

Сниппет из сообщения — один блок на «весь API». У нас API, health и файловый internal-redirect уже разделены. SSE — отдельный контракт:

| Location | Тело | Буфер | Timeout |
|----------|------|-------|---------|
| `/api/` | маленький JSON | default on — ок | default 60s — ок |
| `/` | health / metrics | default | default |
| `/internal-s3/` | байты файла | off | 300s |
| `/api/v1/notifications/stream` | вечный stream | **off** | **1h** |

---

## Что должно работать

- Клиент (браузер `EventSource` / curl) бьёт в `http://localhost:8080/api/v1/notifications/stream?ticket=...` → сразу видит `event: ready`, не через 15 минут.
- Keepalive-комментарии доходят; соединение живёт до лимита приложения (~15 мин), nginx **не** режет на 60s.
- JSON через `:8080` (`/api/v1/lists/`, `/api/v1/auth/sign-in`, ticket POST) — как сейчас.
- Download X-Accel через `:8080` — как сейчас.
- Прямой GET `/internal-s3/...` снаружи → 404.
- `pytest` без маркера smoke — зелёный без docker/nginx.

---

## Архитектура

```text
JSON (уже так):
  Client → nginx :8080  location /api/
         → uvicorn :8000  → 200 JSON

SSE (этот план):
  Client
    → POST :8080/api/v1/notifications/sse-ticket   (location /api/, JSON, Bearer)
    → GET  :8080/api/v1/notifications/stream?ticket=...
         location ^~ /api/v1/notifications/stream
           proxy_buffering off
           proxy_cache off
           gzip off
           proxy_read_timeout 1h
           proxy_send_timeout 1h
         → uvicorn EventSourceResponse
              Content-Type: text/event-stream
              Cache-Control: no-cache
              X-Accel-Buffering: no    # nginx съедает, клиенту не отдаёт
              body: event: ready \n ... (сразу, чанками)
```

```text
Тесты (слои не смешивать):

  pytest                  TestClient → ASGI in-process     nginx.conf НЕ участвует
  pytest -m smoke         httpx → :8080 → nginx → uvicorn  реальный proxy
  контракт nginx.conf     читает файл с диска              docker НЕ нужен
```

---

## Nginx (dev)

Файл: `docker/nginx/nginx.conf`. Существующие `location /api/`, `/`, `/internal-s3/` **не выкидывать и не менять `proxy_pass`**. Добавить SSE location — у `^~` приоритет над `/api/`.

### Целевой фрагмент

```nginx
# SSE: долгий ответ. Не буферизовать, не gzip, не резать на 60s.
location ^~ /api/v1/notifications/stream {
    proxy_http_version 1.1;
    proxy_set_header Host              $http_host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection        "";

    proxy_buffering off;
    proxy_cache off;
    gzip off;

    proxy_read_timeout 1h;
    proxy_send_timeout 1h;

    proxy_pass http://api;
}
```

`^~` — prefix, regex location'ов нет и не будет; query `?ticket=` в match не входит.

Не делать:

- `proxy_ignore_headers X-Accel-Buffering;` — выключит per-response обход буфера.
- `proxy_set_header Host $host;` — сломает порт в Location, если скопировать на `/api/` или `/`.
- `gzip on` на `http {}` без исключения SSE.
- `limit_conn` на этот location (когда дойдут лимиты).

После правки: `docker compose exec nginx nginx -t && docker compose exec nginx nginx -s reload` (conf смонтирован `:ro`).

---

## Изменения в приложении

| Слой | Файл | Что сделать |
|------|------|-------------|
| App | — | ничего. Заголовки SSE уже есть |
| Nginx | `docker/nginx/nginx.conf` | новый `location` |
| Тесты | `tests/infra/test_nginx_conf.py` (новый) | контракт директив, default pytest |
| Тесты | `tests/smoke/test_nginx_sse.py` + flow | smoke `:8080`, маркер `smoke` |
| Доки | README, index'ы, notifications proxy notes | ссылка на этот план |

---

## Тесты: как живут текущие и что добавляем

Это главная развилка. Nginx.conf **не виден** in-process клиенту. Ломать default suite этим планом почти нечем — если не перевести API-тесты на `:8080` (не переводим).

### Матрица

| Сюит | Команда | nginx | Что будет после плана |
|------|---------|-------|------------------------|
| repo / core / services | `pytest` | нет | без изменений |
| API JSON | `pytest tests/api/` `TestClient` | нет | без изменений; пути уже `{API_PREFIX}/v1/...` |
| API SSE | `tests/api/test_notification_stream.py` | нет | без изменений (`_STREAM` / `_TICKET` через `API_PREFIX`). `finite_sse_stream` — ASGITransport ждёт конец стрима, не nginx |
| контракт conf | `pytest tests/infra/` (без маркера) | файл на диске | **новый**, быстрый, без docker |
| smoke download | `pytest -m smoke` | `:8080` | **регрессия**: `location /api/` (без strip), `/`, `/internal-s3/` не режем |
| smoke SSE | `pytest -m smoke` | `:8080` | **новый**. Skip если стек не поднят (`SmokeUnavailable`) |

`addopts = -m 'not smoke'` не трогаем. Новые smoke-тесты **обязаны** нести `@pytest.mark.smoke`, иначе они неожиданно попадут в default прогон и будут skip/fail без docker.

### Почему API SSE-тесты не доказывают nginx

`TestClient` ходит в ASGI напрямую. Буфер nginx, `proxy_read_timeout`, gzip — мёртвый код для этого пути. `ready` в `response.text` там есть даже при полностью сломанном `nginx.conf`.

Отсюда: **не** «покрыть SSE через TestClient ещё раз». Нужен реальный прокси.

### Почему `ready` через nginx — не полный proof buffering

Если nginx чтит `X-Accel-Buffering: no`, buffering уже off **сегодня**, до правки conf. Smoke «`ready` за 5s» может быть зелёным и до, и после.

Поэтому два уровня:

1. **Контракт файла** — лочит директивы (`proxy_buffering off`, `gzip off`, `proxy_cache off`, `proxy_read_timeout 1h`, `proxy_send_timeout 1h`, `location` именно `/api/v1/notifications/stream`). Единственный дешёвый способ зафиксировать 1h timeout (час в CI не ждём).
2. **Smoke runtime** — ticket → stream через `:8080`, чанки приходят, `Server: nginx`, `Content-Type: text/event-stream`. Ловит 502, кривой `proxy_pass`, сломанный Host, регресс download не этот тест.

`proxy_read_timeout 1h` runtime-ом не доказать без часа ожидания. Не пытаться.

### Контракт `tests/infra/test_nginx_conf.py`

Default pytest, без маркера, без сети.

Идея: прочитать `docker/nginx/nginx.conf`, вырезать блок `location ^~ /api/v1/notifications/stream { ... }`, assert подстроки. Не парсить nginx grammar.

Минимум:

- блок существует;
- `proxy_pass http://api;`
- `proxy_http_version 1.1;`
- `proxy_set_header Connection "";`
- `proxy_set_header Host $http_host;` (не `$host`)
- `proxy_buffering off;`
- `proxy_cache off;`
- `gzip off;`
- `proxy_read_timeout 1h;`
- `proxy_send_timeout 1h;`
- `location /api/` жив, `proxy_pass http://api;` **без** URI (не откатить strip);
- `location /internal-s3/` + `internal;` на месте.

Имена: `test__nginx_sse_location__has_streaming_directives`, `test__nginx_api_location__no_uri_strip`, `test__nginx_internal_s3__still_internal`.

Папка `tests/infra/` — не зеркало `src/`, это тест артефакта `docker/`. При реализации дописать строку в [tests.md](../../code/tests.md) и [project_structure.py](../../basics/project_structure.py).

### Smoke SSE `tests/smoke/test_nginx_sse.py`

Паттерн как `nginx_download_flow.py` / `test_nginx_download.py`: sync `httpx`, `SMOKE_BASE` default `http://127.0.0.1:8080`, `SmokeUnavailable` → `pytest.skip`. Пути через `API_PREFIX` из `tests/conftest.py` (`/api/v1/auth/sign-up`, `/api/v1/notifications/...`). Probe download уже бьёт в `/health` — переиспользовать.

Предусловия те же: compose + uvicorn `0.0.0.0:8000` + postgres/redis. `ATTACHMENT_DOWNLOAD_MODE` для SSE **не важен**.

Поток:

1. `probe(base)` из download flow (502 / connection refused → skip).
2. `POST {API_PREFIX}/v1/auth/sign-up` (уникальный email) → token.
3. `POST {API_PREFIX}/v1/notifications/sse-ticket` Bearer → `ticket`.
4. `httpx.stream("GET", .../stream?ticket=...)` с `timeout=10`.
5. Читать чанки, пока не будет `event: ready` **или** 5s deadline.
6. Assert: status 200, `content-type` начинается с `text/event-stream`, в буфере `retry: 3000`, `Server` начинается с `nginx`.
7. Закрыть клиент (не ждать 15 мин). Ticket одноразовый — не ретраить GET.

Если buffering on **и** заголовок `X-Accel-Buffering` проигнорирован — шаг 5 упрётся в deadline → fail. Это как раз сценарий «забыли директивы + сбросили заголовок».

Не входит в smoke SSE:

- ждать keepalive 15s (можно optional вторым тестом; default 5s-ready достаточно);
- прогон invalidate через Redis (уже есть API/core тесты; nginx байты не интерпретирует);
- `X-Accel-Buffering` в ответе клиенту (nginx его съест — assert на отсутствие ок, на наличие — хрупко).

CLI-обёртка (`scripts/smoke_nginx_sse.sh`) — по желанию, по образцу download. Не блокер, если есть pytest -m smoke.

### Регрессия download

После правки conf прогнать `pytest -m smoke` целиком (download + SSE). Не сужать marker. Не менять `run_smoke` download, пока сам не покраснеет.

### Чего не делать с тестами

- Не ставить `base_url=http://127.0.0.1:8080` в фикстуру `client` — сломает CI/локальный прогон без compose, смешает слои.
- Не вешать `@pytest.mark.smoke` на API SSE-тесты.
- Не мокать nginx.
- Не держать stream открытым `SSE_CONNECTION_MAX_SEC` в smoke.
- Не добавлять `@pytest.mark.asyncio` на sync httpx smoke.

---

## Шаги реализации

### Шаг 1 — nginx.conf

- [ ] `location ^~ /api/v1/notifications/stream` с директивами из раздела «Nginx»
- [ ] `location /api/` (без URI-strip), `/`, `/internal-s3/` без регрессии
- [ ] `nginx -t` + reload

### Шаг 2 — ручная проверка

- [ ] JSON: `curl localhost:8080/api/v1/lists/` с Bearer → как `:8000`
- [ ] SSE: ticket + `curl -N localhost:8080/api/v1/notifications/stream?ticket=...` → `event: ready` сразу (`-N` = без буфера curl)
- [ ] Держать ~70s: соединение живо (проверка, что не 60s default). Не обязательно час
- [ ] `curl localhost:8080/internal-s3/x` → 404

### Шаг 3 — тесты

- [ ] `tests/infra/test_nginx_conf.py` — контракт директив, default pytest
- [ ] `tests/smoke/` — SSE flow + `test__stream__via_nginx_ready_immediately`
- [ ] `pytest` (без smoke) зелёный
- [ ] `pytest -m smoke` — download + SSE (стек поднят)

### Шаг 4 — документация / правила

- [ ] Статус-таблица этого файла → ✅
- [ ] [nginx/index.md](index.md), [development_plans/index.md](../index.md)
- [ ] [nginx_dev.md](nginx_dev.md) «вне скоупа» → ссылка сюда
- [ ] [notifications_mvp.md](../notifications/notifications_mvp.md) Proxy notes → этот план
- [ ] README: SSE через `:8080`, `curl -N`
- [ ] [project_structure.py](../../basics/project_structure.py) — `tests/infra/`, smoke SSE
- [ ] [tests.md](../../code/tests.md) — строка про контракт nginx.conf

---

## Область плана

| Входит | Не входит |
|--------|-----------|
| SSE location в nginx.conf | Префикс `/api/` — уже ✅ [api_prefix_dev.md](../api_prefix_dev.md) |
| Явный buffering/gzip/cache/timeout | Правки FastAPI/SSEHub |
| Контракт-тест conf + smoke SSE | Перевод `TestClient` на `:8080` |
| Регрессия smoke download | `limit_req` / `limit_conn` / `real_ip` |
| | WebSocket `Upgrade` |
| | TLS, HTTP/2, закрытие MinIO :9000 |
| | Менять `SSE_CONNECTION_MAX_SEC` / keepalive 15s |

---

## Риски и грабли

| Риск | Как не словить |
|------|----------------|
| Скопировать сниппет с `$host` / намазать buffering на весь `/api/` | Stream-location `/api/v1/notifications/stream`, Host `$http_host` |
| Default pytest ходит в мёртвый `:8080` | Новые runtime-тесты только `@pytest.mark.smoke` |
| Smoke SSE без маркера | Попадёт в `pytest` → skip/fail у всех |
| `httpx.get` вместо `stream` | Ждёт конец стрима 15 мин / timeout |
| Assert `X-Accel-Buffering` у клиента | nginx прячет; смотреть `Content-Type` + чанки |
| `proxy_ignore_headers X-Accel-Buffering` | Запретить в плане; контракт-тест может ловить подстроку |
| `limit_conn` позже на `/api/` | Пометить в `nginx_limits_dev.md`: SSE вынести из conn-зоны |
| Smoke `ready` зелёный «и так» из-за заголовка FastAPI | Контракт conf фиксирует директивы; smoke фиксирует путь |
| Reload без `-t` | Синтаксис → nginx не поднимается, download smoke 502 |

---

## Критерии готовности

- [ ] `curl -N` через `:8080` печатает `event: ready` сразу
- [ ] JSON и X-Accel download через `:8080` живы
- [ ] `pytest` без smoke зелёный (включая новый infra-контракт)
- [ ] `pytest -m smoke` покрывает download **и** SSE
- [ ] План и index обновлены

---

## Вне скоупа → следующие планы

1. **`nginx_limits_dev.md`** — `limit_req` / zones / dry_run / `real_ip`. SSE location не класть в `limit_conn`.
2. **WebSocket proxy** — когда появится chat: `Upgrade` / `Connection "upgrade"`, отдельный location.
3. **Закрыть MinIO с хоста** — как в [nginx_dev.md](nginx_dev.md).

---

## Итог выбора

| Тема | Выбор |
|------|--------|
| Все HTTP через nginx | уже `location /api/` + `/`; клиент бьёт в `:8080` |
| SSE-настройки | отдельный location, не весь `/api/` |
| Path | `/api/v1/notifications/stream` (факт) |
| Host | `$http_host` |
| Python | не трогать |
| Тесты | TestClient как было; контракт conf в default pytest; runtime только smoke |
