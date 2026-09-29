# MVP: Realtime-уведомления (deadline reminder)

План внедрения уведомлений в Task Manager. Архитектура — из [FastAPIRealtimeNotifications.md](FastAPIRealtimeNotifications.md). Скоуп урезан под текущий продукт.

Стек проекта: FastAPI + asyncpg + Redis. **Без** SQLAlchemy и Alembic. DDL — `db/scripts/init.sql`.

---

## Решения (зафиксировано)

| Вопрос | Решение |
|--------|---------|
| Источник событий в MVP | Только `task.deadline_reminder` |
| Окно напоминания | 24 часа |
| Получатель | `tasks.user_id` (assignees нет) |
| Auth для SSE | SSE ticket (Bearer → ticket → stream) |
| Схема БД | Таблица `notification` как в базовом доке |
| Миграции | `init.sql` (+ ручной SQL на уже существующий volume) |
| Фронт | Вне скоупа; контракт API + backend-тесты |
| `task.deadline_changed` / assigned / comment / status | Не в MVP |
| Grouping / outbox / email / push | Не в MVP |
| Хук в `TaskService` при смене `due_date` | Не в MVP (как в доке для reminder: новый `event_id` на следующем тике worker) |

Базовый док остаётся справочником по SSE hub, Redis bus, инвариантам commit→publish и антипаттернам (§11–§14, §19).

---

## Что должно работать

Пользователь получает напоминание, когда до `due_date` его задачи остаётся ≤ 24h.

- уведомление персистентно в PostgreSQL (не только Redis);
- список, счётчик непрочитанных, read / read-all / unread;
- SSE `notification.invalidate` → клиент (позже) перечитывает HTTP;
- несколько вкладок / несколько процессов FastAPI;
- повторный запуск worker не создаёт дубль;
- смена `due_date` → новое напоминание с другим `event_id`, когда новый due снова попадёт в окно 24h;
- падение Redis не ломает запись уведомления и HTTP API.

---

## Архитектура (кратко)

```text
deadline worker
  -> SELECT кандидатов (due_date в окне 24h)
  -> INSERT notification (ON CONFLICT DO NOTHING)
  -> commit
  -> Redis PUBLISH notifications:user:{user_id}
  -> FastAPI listener -> SSEHub
  -> SSE: notification.invalidate
  -> клиент GET /notifications (+ unread-count)
```

PostgreSQL — источник правды. Redis Pub/Sub — только сигнал. SSE — только инвалидация, не payload уведомления.

Порядок: **commit PostgreSQL → потом Redis**. Ошибка Redis после commit → лог, не 500.

---

## Область MVP

| Входит | Не входит |
|--------|-----------|
| Таблица `notification` | События assigned / unassigned / deadline_changed / commented / status |
| `NotificationEvent` + `NotificationService.emit` | Grouping |
| HTTP list / unread-count / read / read-all / unread | Outbox, email, push |
| SSE + Redis bus + SSEHub | Фронтенд |
| SSE ticket auth | Cookie с access token для EventSource |
| Deadline worker (отдельный процесс) | Worker внутри каждого uvicorn worker |
| FastAPI ≥ 0.135 (нативный SSE) | `sse-starlette` |
| Тесты repo / service / API / hub / worker идемпотентность | E2E браузер |

---

## DDL

Добавить в `db/scripts/init.sql` (для уже поднятого volume — выполнить тот же SQL вручную).

Типы `actor_id` / `recipient_id` — `INT`, FK на `users(id)`, как в остальной схеме.

```sql
CREATE TABLE IF NOT EXISTS notification (
    id            BIGSERIAL PRIMARY KEY,
    event_id      VARCHAR(160) NOT NULL,
    type          VARCHAR(64)  NOT NULL,
    category      VARCHAR(32)  NOT NULL DEFAULT 'tasks',
    severity      VARCHAR(16)  NOT NULL DEFAULT 'normal',

    actor_id      INT REFERENCES users (id) ON DELETE SET NULL,
    recipient_id  INT NOT NULL REFERENCES users (id) ON DELETE CASCADE,

    entity_type   VARCHAR(32),
    entity_id     VARCHAR(64),

    title         TEXT NOT NULL,
    body          TEXT,
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
    deep_link     TEXT,

    grouping_key  VARCHAR(256),
    group_count   INTEGER NOT NULL DEFAULT 1,

    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at       TIMESTAMPTZ,
    expires_at    TIMESTAMPTZ,

    CONSTRAINT uq_notification_event_recipient
        UNIQUE (event_id, recipient_id),
    CONSTRAINT ck_notification_severity
        CHECK (severity IN ('normal', 'important')),
    CONSTRAINT ck_notification_group_count
        CHECK (group_count > 0)
);

CREATE INDEX IF NOT EXISTS ix_notification_recipient_created
    ON notification (recipient_id, id DESC);

CREATE INDEX IF NOT EXISTS ix_notification_recipient_unread
    ON notification (recipient_id, id DESC)
    WHERE read_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_notification_recipient_category
    ON notification (recipient_id, category, id DESC);

CREATE INDEX IF NOT EXISTS ix_notification_grouping
    ON notification (recipient_id, grouping_key, id DESC)
    WHERE grouping_key IS NOT NULL;
```

Имя таблицы: `notification` (как в базовом доке). Колонка JSON — `metadata` в DDL; в SQL через asyncpg экранировать/алиасить при необходимости (`metadata` не reserved в PG, но в Python лучше маппить явно).

Для существующих volume после изменения `init.sql` скрипт сам не применится — нужен ручной `psql` с тем же DDL.

---

## Структура файлов

Под существующие слои `src/` (не монопапка `app/notifications/`):

```text
src/
  models/notification.py
  repository/notification.py
  services/notification.py
  services/deadline_reminders.py      # логика тика (можно вызывать из worker entry)
  workers/deadline_reminders.py       # entrypoint процесса
  api/v1/notifications.py             # REST
  api/v1/notification_stream.py       # SSE + ticket (отдельный router)
  core/sse_hub.py
  core/redis_notification_bus.py

db/scripts/init.sql                   # + DDL notification

tests/
  repository/test_notification_repo.py
  services/test_notification_service.py
  services/test_deadline_reminders.py
  api/test_notifications.py
  core/test_sse_hub.py
```

Зависимости DI — по аналогии с `src/repository/dependencies.py` и `src/services/dependencies.py`.

Обновить: `src/main.py` (lifespan: SSEHub + Redis bus listener), `src/api/v1/router.py`, `requirements.txt` (`fastapi>=0.135.0`).

---

## Контракт события

Единая точка создания — `NotificationService.emit`. Сервис **не** делает `commit`; транзакцией владеет вызывающий код (в MVP — worker).

```python
class NotificationEvent(BaseModel):
    event_id: str
    type: str
    category: str = "tasks"
    severity: Literal["normal", "important"] = "normal"
    actor_id: int | None = None
    recipient_ids: set[int]
    entity_type: str | None = None
    entity_id: str | None = None
    title: str
    body: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    deep_link: str | None = None
    grouping_key: str | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

Правила:
- `actor_id` вычитается из `recipient_ids` (для reminder `actor_id=None`);
- пустой набор получателей — не ошибка;
- `deep_link` только внутренний путь (`/v1/tasks/{id}` или `/tasks/{id}` — зафиксировать один стиль);
- `emit` возвращает `set[int]` получателей, для которых реально вставилась строка → им publish.

Репозиторий: `INSERT ... ON CONFLICT (event_id, recipient_id) DO NOTHING RETURNING recipient_id`.

---

## Единственное событие MVP: `task.deadline_reminder`

```text
event_id = task.deadline_reminder:{task_id}:{recipient_id}:{due_date_iso}:24h
```

- `type`: `task.deadline_reminder`
- `severity`: `important`
- `recipient_ids`: `{task.user_id}`
- `entity_type`: `task`, `entity_id`: `str(task.id)`
- `title`: например `Скоро дедлайн: {task.title}`
- `metadata`: `{"task_id": ..., "due_date": ...}`
- `deep_link`: `/tasks/{id}`

После смены `due_date` строка со старым `event_id` остаётся; новое напоминание появится с новым `event_id`, когда новый due войдёт в окно — как в §17 базового дока. Отзыв stale в MVP не делаем.

---

## Deadline worker

Отдельный процесс (не в lifespan uvicorn):

```bash
python -m src.workers.deadline_reminders
```

Алгоритм тика:

1. Advisory lock или Redis lock (чтобы несколько реплик worker не дублировали работу; уникальный `event_id` всё равно защищает от дублей строк).
2. Кандидаты:

```sql
SELECT id, title, due_date, user_id
FROM tasks
WHERE due_date > now()
  AND due_date <= now() + interval '24 hours'
  AND status = 'active'
  AND deleted_at IS NULL;
```

3. В транзакции: для каждой строки `emit(NotificationEvent(...))`.
4. Commit.
5. `publish_many(changed_recipients)` — ошибки Redis только в лог.
6. Sleep (например 60–300 сек) → повтор.

Интервал и окно `24h` — в `Configs` (`DEADLINE_REMINDER_WINDOW`, `DEADLINE_WORKER_INTERVAL_SEC`).

---

## HTTP API

Префикс: `/v1/notifications` (как остальной API).  
`recipient_id` всегда из `get_current_user_id`, никогда из body/query клиента.

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/v1/notifications` | Список, cursor `before_id`, `limit`≤100, фильтры `unread` / `category` / `important` |
| GET | `/v1/notifications/unread-count` | `total`, `important`, `by_category` |
| POST | `/v1/notifications/read` | `{ "ids": [...] }` или `{ "all": true, "category"? }` |
| POST | `/v1/notifications/unread` | `{ "ids": [...] }` |
| POST | `/v1/notifications/sse-ticket` | Создаёт одноразовый ticket в Redis TTL ~30s |
| GET | `/v1/notifications/stream` | SSE; auth через `ticket` query (`GETDEL`) |

После успешного commit `read` / `read-all` / `unread` — `publish` invalidate текущему пользователю (счётчик на других вкладках).

Пагинация: `id DESC`, брать `limit+1`, `has_more` / `next_before_id`. Без `offset`.

Объявить `/stream` и `/sse-ticket` **до** любых `/{id}` роутов (сейчас path-id для read не нужен — ids в body).

---

## SSE ticket

`EventSource` не шлёт `Authorization`. Схема:

1. Клиент: `POST /v1/notifications/sse-ticket` с Bearer → `{ "ticket": "..." }`.
2. Backend: Redis `sse-ticket:{sha256(ticket)}` = `user_id`, TTL 30s.
3. Клиент: `GET /v1/notifications/stream?ticket=...`.
4. Endpoint: атомарный `GETDEL`, при отсутствии/истечении → 401.
5. Подписка в `SSEHub`, событие `ready` с `retry: 3000`, далее `notification.invalidate` + keepalive.

Основной access token в URL не передавать.  
`Last-Event-ID` не использовать — после connect клиент сам делает HTTP refetch (контракт для будущего фронта).

Опционально: ограничить жизнь одного SSE-соединения (~15 мин), чтобы при reconnect снова проверить сессию.

---

## Redis + SSEHub + lifespan

Уже есть Redis в `app_lifespan`. Добавить:

- один `SSEHub` на процесс (`app.state`);
- один `RedisNotificationBus` + background listener (`psubscribe notifications:user:*`);
- при shutdown: отменить listener, закрыть pubsub.

Канал: `notifications:user:{user_id}`.  
Payload сигнала:

```json
{"type": "notification.invalidate"}
```

`SSEHub`: `user_id → set[Queue]`, maxsize очереди = 1 (слияние invalidate). Unsubscribe в `finally` стрима.

Два процесса uvicorn обязаны ходить через Redis, не через память одного процесса.

---

## Клиентский контракт (фронт вне скоупа)

Зафиксировать в этом плане / OpenAPI, не реализовывать UI:

1. После логина: HTTP list + unread-count.
2. `POST sse-ticket` → открыть `EventSource` на `/stream?ticket=...`.
3. На `ready` и на каждый `notification.invalidate` — снова list + count.
4. Авто-reconnect `EventSource`.
5. Poll unread-count раз в 60s как страховка.

---

## Порядок реализации

### Статус реализации

| Шаг | Статус |
|-----|--------|
| 1. Хранение + HTTP | ✅ |
| 2. Service + worker | ✅ |
| 3. SSE в одном процессе | ✅ |
| 4. Redis bus | ✅ |
| 5. Доводка | ✅ |

### Шаг 1. Хранение + HTTP

- [x] DDL в `init.sql`
- [x] Pydantic-модели
- [x] `NotificationRepository` (create_for_recipients, list, unread counts, mark read/unread)
- [x] REST без SSE
- [x] Тесты: изоляция по recipient, идемпотентность `event_id`, cursor, read/unread

### Шаг 2. Service + worker

- [x] `NotificationEvent`, `NotificationService.emit`
- [x] Worker entrypoint + тик 24h
- [x] После commit — publish (можно временно no-op bus / лог)
- [x] Тесты: повторный тик без дубля; смена `due_date` → новый `event_id`

### Шаг 3. SSE в одном процессе

- [x] FastAPI ≥ 0.135
- [x] `SSEHub`
- [x] `POST sse-ticket` + `GET stream`
- [x] Тест: две очереди одного user получают invalidate; чужой user — нет; без ticket → 401

### Шаг 4. Redis bus

- [x] `RedisNotificationBus` + listener в lifespan
- [x] Worker/read-пути публикуют через bus
- [x] Проверка: сигнал из процесса A доходит в SSE процесса B
- [x] Redis down: worker/HTTP всё равно пишут notification

### Шаг 5. Доводка

- [x] Логи: `event_id`, type, recipients; Redis errors; SSE connect/disconnect без токена; worker errors
- [x] Метрики: active SSE streams, notifications created by type, redis publish errors, worker runs
- [x] Proxy notes (если появится nginx): `proxy_buffering off`, достаточный `proxy_read_timeout`

#### Proxy notes (nginx)

SSE — долгий ответ. Для `/v1/notifications/stream` выставь `proxy_buffering off`, `proxy_cache off`, `proxy_http_version 1.1`, `proxy_set_header Connection ""` и `proxy_read_timeout` существенно больше keepalive (например `1h`). FastAPI уже шлёт `X-Accel-Buffering: no`, но явная настройка nginx делает поведение предсказуемым.

---

## Тесты (минимум)

**Repo / HTTP**
- один `(event_id, recipient_id)` → одна строка;
- пользователь видит только свои;
- нельзя read/unread чужое;
- list `id DESC`, `before_id` без дублей;
- `limit` > 100 режется или 422;
- unread-count после read / read-all;
- offline: строка есть без SSE.

**Worker**
- повторный тик не дублирует;
- после смены `due_date` создаётся новое напоминание (другой `event_id`);
- completed / deleted / вне окна 24h — не создаётся.

**SSE / Redis**
- stream без ticket → 401;
- `Content-Type: text/event-stream`, первое событие `ready`;
- две вкладки одного user;
- publish из bus → hub;
- Redis publish fail не валит успешный тик worker.

---

## Когда MVP готов

- [x] Таблица `notification` в `init.sql` и на стенде
- [x] FastAPI ≥ 0.135
- [x] List / unread-count / read / read-all / unread работают и ограничены текущим user
- [x] Единый `NotificationService`
- [x] Worker создаёт только `task.deadline_reminder` с детерминированным `event_id`
- [x] Повтор worker без дублей
- [x] SSE ticket + stream, access не в URL как основной токен
- [x] Redis listener в lifespan, доставка между процессами
- [x] Publish только после commit; Redis down ≠ потеря notification / ≠ 500 на HTTP read
- [x] Тесты из чеклиста выше зелёные
- [x] Контракт для будущего фронта описан (invalidate → refetch + poll)

---

## Связь с базовым доком

| Тема | Где в базовом доке |
|------|-------------------|
| Таблица, индексы, смысл полей | §4 |
| `NotificationEvent` / emit / ON CONFLICT | §6, §8 |
| Встраивание commit → Redis | §9 (паттерн; в MVP вызывающий — worker) |
| HTTP API | §10 |
| SSEHub | §11 |
| SSE auth / ticket | §12 |
| Redis bus | §13–§14 |
| Клиентское восстановление | §15 (контракт) |
| Deadline worker | §17 |
| Антипаттерны | §19 |
| Outbox / grouping / прочие события | вне MVP |
