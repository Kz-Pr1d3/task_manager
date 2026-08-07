# Задачи: технические заметки

Дополнение к [tasks_dev.md](tasks_dev.md). Варианты API, схемы таблиц, инварианты и выводы из проектирования. Не финальная спецификация — основа для технических требований.

---

## Статус реализации

Обновлено: 2026-08-07.

| Компонент | Статус | Путь / заметки |
|-----------|--------|----------------|
| DDL lists/tasks + индексы + seed | ✅ | `init.sql`: seed только Inbox; status `active`/`completed` |
| Models: `Task`, `UpdateTaskRequest`, enums | ✅ | `src/models/tasks.py`, `enums.py` |
| Models: lists CRUD schemas | ✅ | `src/models/lists.py` |
| `ListRepository` get/create/rename/reorder | ✅ | reorder с каскадом позиций; delete — stub |
| `TaskRepository` | ✅ | get/list/create/update/move/lifecycle/subtasks/count |
| `ListService` CRUD (без delete) | ✅ | лимит 5 → `409` (`ConflictException`) |
| `TaskService` | ✅ | get/list/create/update/move/lifecycle/subtasks |
| API lists | ✅ частично | GET/POST `/v1/lists/`, PATCH rename/reorder; DELETE stub |
| API tasks | ✅ | GET/POST `/v1/tasks/`; GET/PATCH/DELETE `/{id}`; move/complete/trash/restore/subtasks |
| API views | ❌ | нет |
| API create-via-view | ❌ | `/views/today|next7/tasks` |
| DI wiring | ✅ | `repository/dependencies.py`, `services/dependencies.py`, `v1/router.py` |

**Этап:** tasks_router done. Next: delete list → views.

**Расхождения API с ранним черновиком (как в коде сейчас):**

| Черновик | Факт |
|----------|------|
| `PATCH /lists/{id}` rename | `PATCH /lists/{id}/rename` |
| `PUT /lists/reorder` + `ordered_ids` | `PATCH /lists/{id}/reorder` + `{position: 1..5}` + каскад |
| prefix `/api/v1` | prefix `/v1` (без `/api`) |
| лимит списков → 409 | ✅ create → `409` |
| `GET/POST /lists/{id}/tasks` | `GET/POST /tasks/` (`list_id` query/body); код в `tasks.py` + `TaskService` |

---

## Архитектурные инварианты

```
┌─────────────────────────────────────────────────────────────┐
│  Физический list_id  — ровно один на задачу (корень/лист)   │
│  Виртуальные views   — query по due_date, status, deleted_at│
│  previous_list_id    — только для restore из trash          │
│  deleted_at          — ортогонален status (completed+trash) │
│  completed           — статус, list_id НЕ меняется          │
│  «не буду делать»    — soft delete в корзину                │
└─────────────────────────────────────────────────────────────┘
```

1. Задача без `deleted_at` может одновременно быть в физическом списке и в N virtual views.
2. Задача с `deleted_at` видна **только** в `/views/trash`.
3. `due_date` / `status` не влияют на `list_id`.
4. Подзадача всегда имеет тот же `list_id`, что родитель (синхронизация при move).
5. Лимит 100 считается по `(user_id, list_id)` включая подзадачи.
6. Физических системных списков — только Inbox.

---

## Хранение списков (вариант B — принято)

Единая таблица `lists` для системных и пользовательских списков.

| type | user_id | Строк в БД | Назначение |
|------|---------|------------|------------|
| `inbox` | NULL | 1 (seed) | «Входящие» — общий системный список |
| `user` | NOT NULL | до 5 на пользователя | Пользовательские списки |

Изоляция задач пользователя — через `tasks.user_id`, не через отдельные строки Inbox на каждого user.

**Правила:**

- Системный Inbox создаётся **seed-ом при инициализации БД**, не при регистрации.
- `tasks.list_id` — FK на `lists.id`.
- Запрос задач во «Входящих»: `tasks.user_id = :uid AND lists.type = 'inbox'`.
- Пользовательские списки: `lists.type = 'user' AND lists.user_id = :uid`.
- Константа `INBOX_LIST_ID` — в коде (или lookup по `type` один раз при старте).

**Ограничения на `lists`:**

```sql
-- ровно одна строка inbox
CREATE UNIQUE INDEX lists_system_type_unique
  ON lists (type) WHERE user_id IS NULL;

ALTER TABLE lists ADD CONSTRAINT lists_user_type_check CHECK (
  (type = 'inbox' AND user_id IS NULL)
  OR (type = 'user' AND user_id IS NOT NULL)
);
```

Отклонённые альтернативы: enum без FK (вариант A); отдельные таблицы `inbox_tasks` / `abandoned_tasks` (вариант C); статус/список/view Abandoned (**снято** — «не буду делать» = trash).

---

## Схема БД

> Реализовано в `db/scripts/init.sql` (вариант B). Системная строка — seed Inbox; пользовательские — CRUD.

### `lists`

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | SERIAL PK | |
| user_id | INT NULL FK users | NULL для системного Inbox |
| type | VARCHAR | `inbox`, `user` |
| name | VARCHAR(255) | Для user-списков; для системных — константа |
| position | INT NULL | Порядок user-списков в UI; NULL для системных |
| created_at | TIMESTAMPTZ | |

**Seed:**

```sql
INSERT INTO lists (id, user_id, type, name) VALUES
  (1, NULL, 'inbox', 'Входящие');
```

Задача во Входящих: `list_id=1` + фильтр `tasks.user_id`.

### `tasks`

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | SERIAL PK | |
| user_id | INT NOT NULL FK users | |
| list_id | INT NOT NULL FK lists | |
| parent_id | INT NULL FK tasks | |
| previous_list_id | INT NULL | **без FK** (user list мог быть hard-deleted); только trash |
| title | VARCHAR(50) NOT NULL | |
| description | TEXT | |
| priority | VARCHAR NULL | `low`, `medium`, `high`; NULL = без приоритета |
| due_date | TIMESTAMPTZ NULL | |
| status | VARCHAR NOT NULL | `active`, `completed` |
| deleted_at | TIMESTAMPTZ NULL | |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |
| completed_at | TIMESTAMPTZ NULL | |

**Индексы (минимум):**

- `(user_id, list_id)` WHERE deleted_at IS NULL — лимит 100
- `(user_id, list_id, created_at, id)` WHERE parent_id IS NULL AND deleted_at IS NULL — пагинация списков
- `(user_id, due_date, id)` WHERE deleted_at IS NULL AND status = 'active' AND parent_id IS NULL — views today/next7
- `(user_id, completed_at DESC, id DESC)` WHERE deleted_at IS NULL AND parent_id IS NULL AND status = 'completed' — completed
- `(user_id, deleted_at DESC, id DESC)` WHERE deleted_at IS NOT NULL AND parent_id IS NULL — trash
- `(parent_id)` — каскады

### Ограничение 5 user-списков

```sql
-- CHECK или trigger: COUNT(*) WHERE user_id=X AND type='user' <= 5
-- сейчас: service + advisory lock в ListRepository.create_custom_list
```

---

## Virtual views: SQL-скелеты

Timezone `tz` приходит от клиента на каждый запрос.

```sql
-- «Сегодня»
-- :today = calendar date in tz
WHERE user_id = :uid
  AND deleted_at IS NULL
  AND due_date IS NOT NULL
  AND (due_date AT TIME ZONE :tz)::date = :today

-- «Следующие 7 дней» (включая сегодня)
WHERE user_id = :uid
  AND deleted_at IS NULL
  AND due_date IS NOT NULL
  AND (due_date AT TIME ZONE :tz)::date BETWEEN :today AND :today + 7

-- «Выполненные»
WHERE user_id = :uid
  AND deleted_at IS NULL
  AND status = 'completed'

-- «Корзина»
WHERE user_id = :uid
  AND deleted_at IS NOT NULL
```

**Inbox (физический):**

```sql
WHERE user_id = :uid
  AND list_id = (SELECT id FROM lists WHERE type = 'inbox')
  AND deleted_at IS NULL
```

---

## API

Префикс: `/v1` (роутер `v1_router`). Все endpoints требуют auth (`Bearer`).

Легенда: ✅ сделано · 🟡 stub/частично · ❌ не начато

### Lists (пользовательские)

| Endpoint | Метод | Статус | Описание |
|----------|-------|--------|----------|
| `/lists/` | GET | ✅ | User-списки (type=user), ORDER BY position |
| `/lists/` | POST | ✅ | Создать (лимит 5 → 409); body `{name}` |
| `/lists/{id}/rename` | PATCH | ✅ | `{name}` |
| `/lists/{id}/reorder` | PATCH | ✅ | `{position}` (1..N); каскад соседних позиций |
| `/lists/{id}` | DELETE | 🟡 | Hard delete → задачи в корзину (stub) |

### Tasks

Владение: `api/v1/tasks.py` (`tasks_router`) + `TaskService` + `TaskRepository`.
Lists router — только CRUD списков, без nested `/lists/{id}/tasks`.

| Endpoint | Метод | Статус | Описание |
|----------|-------|--------|----------|
| `/tasks/` | GET | ✅ | Задачи физического списка; query `list_id` + cursor pagination |
| `/tasks/` | POST | ✅ | Создать; body `{list_id, title, due_date?}` |
| `/tasks/{id}` | GET | ✅ | Одна задача |
| `/tasks/{id}` | PATCH | ✅ | title/description/priority/due_date (`exclude_unset`) |
| `/tasks/{id}/move` | POST | ✅ | `{list_id}` — явный move + каскад подзадач; subtask → 422 |
| `/tasks/{id}/complete` | POST | ✅ | Complete + каскад (`list_id` без изменений) |
| `/tasks/{id}/trash` | POST | ✅ | Soft delete + previous_list_id + каскад |
| `/tasks/{id}/restore` | POST | ✅ | Restore из корзины |
| `/tasks/{id}` | DELETE | ✅ | Hard delete (только если в корзине) → иначе 422 |

**Решение:** редактирование полей — PATCH (не PUT). Move/complete/trash — отдельные POST.
Список/создание — на `tasks_router`, не nested под lists.

### Views

| Endpoint | Метод | Статус | Query params |
|----------|-------|--------|--------------|
| `/views/inbox` | GET | ❌ | `tz`, `limit`, `cursor`, `cursor_created_at`* |
| `/views/today` | GET | ❌ | `tz`, `limit`, `cursor`, `cursor_due_date`* |
| `/views/next7` | GET | ❌ | `tz`, `limit`, `cursor`, `cursor_due_date`* |
| `/views/completed` | GET | ❌ | `limit`, `cursor`, `cursor_completed_at`* |
| `/views/trash` | GET | ❌ | `limit`, `cursor`, `cursor_deleted_at`* |
| `/views/trash` | DELETE | ❌ | Очистить корзину (hard delete all) |

\* второй параметр cursor — только при составной сортировке, см. [Пагинация](#пагинация-cursor--lazy-load).

`GET /tasks/?list_id=` — те же `limit`, `cursor`, `cursor_created_at`.

### Subtasks

| Endpoint | Метод | Статус | Описание |
|----------|-------|--------|----------|
| `/tasks/{id}/subtasks` | GET | ✅ | Список подзадач |
| `/tasks/{id}/subtasks` | POST | ✅ | Создать подзадачу (title) |

Подзадача наследует `list_id`, `user_id`; `due_date` = NULL.

### Create через view (удобные alias)

| Endpoint | Метод | Статус | Эффект |
|----------|-------|--------|--------|
| `/views/today/tasks` | POST | ❌ | `{title}` → Inbox + due_date=today |
| `/views/next7/tasks` | POST | ❌ | `{title}` → Inbox + due_date=today (default) |

Опционально `{due_date}` в body для next7 — выбор дня из диапазона.

---

## Request/Response (черновик)

### TaskResponse

```json
{
  "id": 1,
  "title": "...",
  "description": null,
  "priority": null,
  "due_date": "2026-06-17T00:00:00+03:00",
  "status": "active",
  "list_id": 10,
  "parent_id": null,
  "previous_list_id": null,
  "deleted_at": null,
  "created_at": "...",
  "updated_at": "...",
  "completed_at": null,
  "subtasks_count": 2
}
```

### Pagination

Ответ списка задач (cursor / lazy load):

```json
{
  "items": [...],
  "next_cursor": 198,
  "has_more": true,
  "limit": 20
}
```

- `next_cursor` — **id последней задачи в `items`**, не арифметика `cursor + limit`.
- `has_more = (len(items) == limit)`.
- Если `has_more = false` → `next_cursor = null`.
- `total` не возвращаем (дорогой `COUNT(*)`; для lazy load не нужен).

Параметры запроса:

| Параметр | Default | Max | Описание |
|----------|---------|-----|----------|
| `limit` | 20 | 50 | Размер страницы |
| `cursor` | — | — | `id` последней задачи с предыдущей страницы |
| `cursor_created_at` | — | — | Для списков: пара к `cursor` при `ORDER BY created_at, id` |
| `cursor_due_date` | — | — | Для today/next7: пара к `cursor` при `ORDER BY due_date, id` |
| `cursor_completed_at` | — | — | Для completed |
| `cursor_deleted_at` | — | — | Для trash |

---

## Пагинация (cursor / lazy load)

Keyset pagination для infinite scroll. **Offset не используем.**

### Инварианты

1. В выборке только **корневые задачи**: `parent_id IS NULL`.
2. `tasks.id` — `SERIAL` (integer), монотонно растёт глобально, но в выборке пользователя id **не непрерывны**.
3. `next_cursor` всегда берётся из **фактического последнего элемента ответа**:

```python
has_more = len(items) == limit
next_cursor = items[-1].id if has_more else None
```

4. Следующий запрос: `cursor = next_cursor` (+ companion-поле при составной сортировке).

### Сортировка и cursor по контексту

#### Списки (inbox, user) — `created_at ASC, id ASC`

Первая страница:

```sql
WHERE user_id = :uid
  AND list_id = :list_id
  AND parent_id IS NULL
  AND deleted_at IS NULL
ORDER BY created_at ASC, id ASC
LIMIT :limit
```

Следующие страницы:

```sql
  AND (created_at, id) > (:cursor_created_at, :cursor)
ORDER BY created_at ASC, id ASC
LIMIT :limit
```

Первая страница — без `cursor` / `cursor_created_at`.

#### Today / Next7 — `due_date ASC, id ASC`

```sql
  AND (due_date, id) > (:cursor_due_date, :cursor)  -- со 2-й страницы
ORDER BY due_date ASC, id ASC
LIMIT :limit
```

#### Completed — `completed_at DESC NULLS LAST, id DESC`

```sql
  AND (completed_at, id) < (:cursor_completed_at, :cursor)  -- со 2-й страницы
ORDER BY completed_at DESC NULLS LAST, id DESC
LIMIT :limit
```

Для DESC «следующая страница» = элементы **меньше** курсора.

#### Trash — `deleted_at DESC, id DESC`

```sql
  AND (deleted_at, id) < (:cursor_deleted_at, :cursor)
ORDER BY deleted_at DESC, id DESC
LIMIT :limit
```

### Почему `next_cursor ≠ cursor + limit`

Пример: `cursor=145`, `limit=20`. В ответе могут быть id `150, 152, 158, … 198` — между ними дыры (задачи других users, других list_id, подзадачи, удалённые). `next_cursor = 198`, не `165`.

### Подзадачи в ответе

Вариант A (рекомендуется для MVP): `items` — только корни; подзадачи в `GET /tasks/{id}` или `GET /tasks/{id}/subtasks`.

Вариант B: вложить `subtasks[]` в каждый root (без пагинации подзадач; их обычно мало).

### Пример flow (физический список)

```
1. GET /tasks/?list_id=10&limit=20
   → items: [id=12, 15, 18, …, 141], next_cursor=141, has_more=true

2. GET /tasks/?list_id=10&limit=20&cursor=141&cursor_created_at=2026-06-10T10:00:00Z
   → items: [id=145, 150, …, 198], next_cursor=198, has_more=true

3. GET /tasks/?list_id=10&limit=20&cursor=198&cursor_created_at=2026-06-15T14:30:00Z
   → items: [3 шт], has_more=false, next_cursor=null
```

---

## Service-layer: ключевые транзакции

### Move task

1. Проверить лимит 100 в целевом списке (+ все подзадачи).
2. UPDATE `tasks SET list_id = :new WHERE id = :root OR parent_id = :root`.
3. Не трогать `previous_list_id` (только trash).

### Soft delete (trash)

1. `previous_list_id = current list_id` (перезаписывать).
2. `deleted_at = now()` для root + descendants.

### Restore from trash

1. Target list = `previous_list_id` if exists else `INBOX_LIST_ID`.
2. Проверить лимит 100.
3. `deleted_at = NULL`, restore descendants.

### Delete user list

1. Для каждой задачи: `previous_list_id = list_id`, `deleted_at = now()` (+ subtasks).
2. DELETE FROM lists WHERE id = :id AND type = 'user'.

### Complete parent

1. UPDATE all descendants SET status=completed, completed_at=now().
2. UPDATE root SET status=completed, completed_at=now().

### Auto-complete parent

Trigger после complete подзадачи: если all siblings completed → complete parent (рекурсивно вверх).

---

## Hard delete: стратегия (вариант C)

- **Источник:** только корзина.
- **Операции:** `DELETE /tasks/{id}` (404 если not trashed), `DELETE /views/trash` (bulk).
- **Каскад:** hard delete root → hard delete all `parent_id = root`.
- **Retention:** нет авто-очистки; completed вне корзины хранятся бессрочно.
- **Списки:** user list hard delete не оставляет tombstone; задачи только через soft delete.

---

## Структура файлов (факт)

```
src/
├── api/
│   ├── auth.py
│   ├── dependencies.py          # get_current_user_id
│   └── v1/
│       ├── router.py            # /v1
│       ├── lists.py             # ✅ CRUD списков (DELETE stub); без tasks
│       ├── tasks.py             # 🟡 GET/POST `/`; GET/PATCH `/{id}`; lifecycle/subtasks stubs
│       └── views.py             # ❌ ещё нет
├── services/
│   ├── auth.py
│   ├── list.py                  # ✅ без delete; create → 409
│   ├── task.py                  # 🟡 get/update done; list/create/lifecycle stubs
│   └── dependencies.py
├── repository/
│   ├── user.py
│   ├── list.py                  # ✅ get/create/rename/reorder(+cascade); delete stub
│   ├── task.py                  # 🟡 get/update; list/create/lifecycle stubs
│   ├── base.py
│   └── dependencies.py
├── models/
│   ├── auth.py
│   ├── user.py
│   ├── lists.py
│   ├── tasks.py
│   └── enums.py                 # TaskStatus (active/completed), TaskPriority
└── db/scripts/init.sql          # DDL + seed Inbox
```

---

## Ошибки (HTTP)

| Код | Ситуация |
|-----|----------|
| 400 | title > 50, невалидный priority/status |
| 403 | чужая задача / список |
| 404 | не найдено |
| 409 | лимит 5 списков / 100 задач |
| 422 | create в запрещённом view; hard delete не из корзины |

---

## Расхождения, зафиксированные в ходе обсуждения

| Было раньше | Стало |
|-------------|-------|
| Всегда create через Inbox | Create в любом user-списке или Inbox |
| Next7 без «Сегодня» | Next7 включает today … today+7 |
| due_date DATE, без времени | TIMESTAMPTZ, время опционально |
| 5 уровней приоритета | null + low/medium/high |
| GET /tasks глобально без фильтра | `GET /tasks/?list_id=` + views; без «всех задач юзера» |
| `GET/POST /lists/{id}/tasks` | `GET/POST /tasks/` в `tasks_router` + `TaskService` |
| Inbox per-user при регистрации | Единая таблица `lists`, вариант B: seed только inbox |
| Статус/список/view Abandoned | **Снято**; «не буду делать» = trash |
| Restore списка | Нет; только задачи поштучно |
| `previous_list_id` FK на lists | Без FK (hard delete списка) |
| prefix `/api/v1` | `/v1` |
| bulk reorder `ordered_ids` | per-list `PATCH .../reorder` + `position` (+ каскад) |
| лимит списков → 403 | → `409` |

---

## Post-MVP

- **Архивация списка** — отдельный контейнер, не корзина; restore списка целиком.
- **Timezone в профиле** — если фронт перестанет слать tz на каждый запрос.
