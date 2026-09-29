# Realtime-уведомления для FastAPI таск-трекера

## 1. Что должно работать

После внедрения пользователь должен получать уведомления без перезагрузки страницы.

Минимальный набор событий:

- на пользователя назначили задачу;
- пользователя сняли с задачи;
- в его задаче изменили дедлайн;
- до дедлайна осталось заданное время;
- в его задаче оставили комментарий;
- статус задачи изменился.

У уведомлений должны быть список, счетчик непрочитанных, отметка о прочтении и ссылка на нужную задачу. Если пользователь был не в сети, уведомление не должно пропасть. Если открыто несколько вкладок, уведомление должно прийти в каждую.

## 2. Как это устроено

В этой схеме у каждого инструмента одна понятная задача:

- PostgreSQL хранит уведомления и является источником правды;
- Redis Pub/Sub передает короткий сигнал нужным экземплярам FastAPI;
- SSE доставляет этот сигнал в открытый браузер по обычному HTTP-соединению;
- обычный HTTP API возвращает список уведомлений и счетчики.

Полный путь события выглядит так:

```text
Изменение задачи
    -> запись уведомления в PostgreSQL
    -> успешный commit
    -> PUBLISH в Redis для нужного user_id
    -> FastAPI отправляет notification.invalidate в SSE-поток
    -> клиент заново запрашивает список и счетчик по HTTP
```

Через Redis и SSE не надо отправлять полную запись уведомления. Достаточно такого сообщения:

```json
{
  "type": "notification.invalidate"
}
```

Клиент получает сигнал и забирает актуальное состояние из PostgreSQL через HTTP. Поэтому повторный сигнал не создает дубль, нарушение порядка сигналов ничего не ломает, а пропущенный сигнал восстанавливается обычным запросом списка.

Redis Pub/Sub похож на радио. Пока подписчик подключен, он слышит сообщения. Если он отключился, старые сообщения после подключения не вернутся. У Redis Pub/Sub гарантия at-most-once, поэтому хранить сами уведомления только в Redis нельзя.

SSE, или Server-Sent Events, это обычный долгий HTTP-запрос, по которому сервер может отправлять браузеру события по мере их появления. Канал односторонний: сервер отправляет данные, браузер принимает. Для уведомлений этого достаточно, потому что все команды клиента продолжают идти через обычный HTTP API.

- [Как работает Redis Pub/Sub](https://redis.io/docs/latest/develop/pubsub/)
- [Async Redis и Pub/Sub на Python](https://redis.io/docs/latest/develop/clients/redis-py/async/)
- [SSE в документации FastAPI](https://fastapi.tiangolo.com/tutorial/server-sent-events/)
- [Видео на русском: разбираем Server-Sent Events](https://www.youtube.com/watch?v=m9TDaOXTRKQ)

## 3. Что добавить в проект

Названия папок можно подстроить под существующую структуру, но ответственность файлов лучше не смешивать.

```text
app/
  notifications/
    models.py
    schemas.py
    repository.py
    service.py
    sse_hub.py
    redis_bus.py
    router.py
    stream_router.py
  tasks/
    service.py
  core/
    config.py
    database.py
  main.py
```

Зависимости:

```text
fastapi>=0.135.0
uvicorn[standard]
sqlalchemy[asyncio]>=2.0
asyncpg
alembic
redis>=5.0
```

Если SQLAlchemy, Alembic и PostgreSQL уже подключены, добавлять их второй раз не надо.

Встроенные `EventSourceResponse` и `ServerSentEvent` появились в FastAPI `0.135.0`. Если в проекте стоит более старая версия, сначала обнови FastAPI и проверь тесты существующего API. Отдельная библиотека `sse-starlette` для этой реализации не нужна.

Для локальной разработки Redis можно поднять так:

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10
```

В настройках приложения нужен адрес:

```env
REDIS_URL=redis://localhost:6379/0
```

В production порт Redis не надо открывать в интернет. К Redis должны иметь доступ только сервисы внутри закрытой сети.

## 4. Таблица уведомлений

Создай миграцию Alembic со следующей таблицей. Типы `actor_id` и `recipient_id` должны совпадать с типом идентификатора пользователя в проекте. Если в проекте UUID, замени `bigint` на `uuid`. При наличии таблицы пользователей добавь внешние ключи на нее.

```sql
CREATE TABLE notification (
    id bigserial PRIMARY KEY,
    event_id varchar(160) NOT NULL,
    type varchar(64) NOT NULL,
    category varchar(32) NOT NULL DEFAULT 'tasks',
    severity varchar(16) NOT NULL DEFAULT 'normal',

    actor_id bigint NULL,
    recipient_id bigint NOT NULL,

    entity_type varchar(32) NULL,
    entity_id varchar(64) NULL,

    title text NOT NULL,
    body text NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    deep_link text NULL,

    grouping_key varchar(256) NULL,
    group_count integer NOT NULL DEFAULT 1,

    occurred_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    read_at timestamptz NULL,
    expires_at timestamptz NULL,

    CONSTRAINT uq_notification_event_recipient
        UNIQUE (event_id, recipient_id),
    CONSTRAINT ck_notification_severity
        CHECK (severity IN ('normal', 'important')),
    CONSTRAINT ck_notification_group_count
        CHECK (group_count > 0)
);

CREATE INDEX ix_notification_recipient_created
    ON notification (recipient_id, id DESC);

CREATE INDEX ix_notification_recipient_unread
    ON notification (recipient_id, id DESC)
    WHERE read_at IS NULL;

CREATE INDEX ix_notification_recipient_category
    ON notification (recipient_id, category, id DESC);

CREATE INDEX ix_notification_grouping
    ON notification (recipient_id, grouping_key, id DESC)
    WHERE grouping_key IS NOT NULL;
```

Для отката миграции:

```sql
DROP TABLE notification;
```

Зачем нужны основные поля:

- `event_id` защищает от дублей при повторном выполнении одной операции;
- `type` определяет событие, например `task.assigned`;
- `category` позволяет позже отделить задачи от системных уведомлений;
- `severity` отделяет обычные уведомления от важных;
- `actor_id` хранит пользователя, который вызвал событие;
- `recipient_id` хранит получателя;
- `entity_type` и `entity_id` связывают уведомление с задачей или другой сущностью;
- `metadata` хранит дополнительные данные, которые не стоит раскладывать по отдельным колонкам;
- `deep_link` хранит внутренний путь, например `/tasks/42`;
- `read_at` одновременно отвечает на вопрос о прочтении и хранит его время;
- `grouping_key` и `group_count` понадобятся для объединения похожих уведомлений.

Индекс с условием `WHERE read_at IS NULL` нужен для частого запроса счетчика непрочитанных. Он не содержит уже прочитанные строки и поэтому остается небольшим.

- [Миграции Alembic](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
- [Async SQLAlchemy](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Частичные индексы PostgreSQL](https://www.postgresql.org/docs/current/indexes-partial.html)

## 5. Модель SQLAlchemy

В SQLAlchemy имя `metadata` уже занято. Поэтому атрибут Python можно назвать `payload`, а колонку в базе оставить `metadata`.

```python
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Notification(Base):
    __tablename__ = "notification"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "recipient_id",
            name="uq_notification_event_recipient",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column("type", String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="tasks", nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="normal", nullable=False)

    actor_id: Mapped[int | None] = mapped_column(BigInteger)
    recipient_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64))

    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        nullable=False,
    )
    deep_link: Mapped[str | None] = mapped_column(Text)

    grouping_key: Mapped[str | None] = mapped_column(String(256))
    group_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

Миграция является окончательным описанием индексов. Если часть индексов создается через сырой SQL Alembic, не надо еще раз создавать их через `Base.metadata.create_all()`.

## 6. Единый контракт события

Не создавай уведомления вручную в каждом роуте. Все части приложения должны передавать события в один `NotificationService`.

```python
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class NotificationEvent(BaseModel):
    event_id: str = Field(max_length=160)
    type: str = Field(max_length=64)
    category: str = Field(default="tasks", max_length=32)
    severity: Literal["normal", "important"] = "normal"

    actor_id: int | None = None
    recipient_ids: set[int]

    entity_type: str | None = None
    entity_id: str | None = None

    title: str = Field(min_length=1)
    body: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    deep_link: str | None = None

    grouping_key: str | None = None
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
```

Правила для любого события:

- автор действия не получает уведомление о собственном действии;
- один `event_id` нельзя генерировать заново при каждом повторе одной операции;
- пустой список получателей не является ошибкой;
- `deep_link` содержит только внутренний путь приложения;
- пользовательские строки нельзя использовать как готовый HTML;
- `NotificationService` не делает `commit`, транзакцией управляет сервис задачи.

Для `event_id` лучше использовать идентификатор доменного события или созданной записи. Например, `task.assigned:{assignment_id}`. Если запрос может повторяться после таймаута, один и тот же запрос должен использовать тот же идентификатор. Случайный UUID, созданный заново внутри каждой попытки, от дублей не защитит.

## 7. Какие события создавать в таск-трекере

### `task.assigned`

Получатели: новые исполнители, кроме пользователя, который назначил задачу.

```python
NotificationEvent(
    event_id=f"task.assigned:{assignment.id}",
    type="task.assigned",
    severity="important",
    actor_id=current_user.id,
    recipient_ids={assignee.id},
    entity_type="task",
    entity_id=str(task.id),
    title=f"Вам назначили задачу: {task.title}",
    body=None,
    metadata={"task_id": str(task.id)},
    deep_link=f"/tasks/{task.id}",
)
```

### `task.unassigned`

Получатели: снятые исполнители, кроме автора действия.

Заголовок: `Вас сняли с задачи: <название>`.

### `task.deadline_changed`

Получатели: текущие исполнители, кроме автора изменения.

В `metadata` положи старый и новый дедлайн:

```json
{
  "old_deadline": "2026-08-10T12:00:00Z",
  "new_deadline": "2026-08-11T12:00:00Z"
}
```

### `task.deadline_reminder`

Получатели: текущие исполнители. Это важное уведомление.

Для напоминания нужен детерминированный `event_id`, например:

```text
task.deadline_reminder:<task_id>:<recipient_id>:<deadline>:24h
```

Так повторный запуск фоновой задачи не создаст второй экземпляр того же напоминания.

### `task.commented`

Получатели: исполнители, автор задачи и подписчики, кроме автора комментария. Множество получателей обязательно очищается от дублей.

Для серии комментариев можно использовать:

```text
grouping_key = task.comments:<task_id>
```

### `task.status_changed`

Получатели: исполнители и автор задачи, кроме пользователя, который изменил статус.

Старый и новый статус положи в `metadata`.

## 8. Запись в базу без дублей

Для PostgreSQL удобно использовать `INSERT ... ON CONFLICT DO NOTHING`. Повторная обработка события тогда не создаст новую строку.

```python
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import Notification
from app.notifications.schemas import NotificationEvent


class NotificationRepository:
    async def create_for_recipients(
        self,
        session: AsyncSession,
        event: NotificationEvent,
    ) -> set[int]:
        recipients = set(event.recipient_ids)
        if event.actor_id is not None:
            recipients.discard(event.actor_id)

        if not recipients:
            return set()

        rows = [
            {
                "event_id": event.event_id,
                "event_type": event.type,
                "category": event.category,
                "severity": event.severity,
                "actor_id": event.actor_id,
                "recipient_id": recipient_id,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "title": event.title,
                "body": event.body,
                "payload": event.metadata,
                "deep_link": event.deep_link,
                "grouping_key": event.grouping_key,
                "occurred_at": event.occurred_at,
            }
            for recipient_id in recipients
        ]

        statement = (
            insert(Notification)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=["event_id", "recipient_id"]
            )
            .returning(Notification.recipient_id)
        )

        result = await session.execute(statement)
        return set(result.scalars().all())
```

Репозиторий возвращает только тех получателей, для которых действительно появилась новая строка. Именно им потом отправляется сигнал через Redis.

Сервис пока остается небольшим:

```python
class NotificationService:
    def __init__(self, repository: NotificationRepository) -> None:
        self.repository = repository

    async def emit(
        self,
        session: AsyncSession,
        event: NotificationEvent,
    ) -> set[int]:
        return await self.repository.create_for_recipients(session, event)
```

## 9. Встраивание в существующий сервис задач

Запись задачи и запись уведомления должны проходить в одной транзакции PostgreSQL. Сигнал в Redis отправляется только после успешного commit.

```python
async def assign_user_to_task(
    session: AsyncSession,
    task_id: int,
    assignee_id: int,
    current_user: User,
    notification_service: NotificationService,
    notification_bus: RedisNotificationBus,
) -> Task:
    async with session.begin():
        task = await task_repository.get_for_update(session, task_id)
        assignment = await task_repository.assign(
            session=session,
            task=task,
            user_id=assignee_id,
        )

        changed_recipients = await notification_service.emit(
            session,
            NotificationEvent(
                event_id=f"task.assigned:{assignment.id}",
                type="task.assigned",
                severity="important",
                actor_id=current_user.id,
                recipient_ids={assignee_id},
                entity_type="task",
                entity_id=str(task.id),
                title=f"Вам назначили задачу: {task.title}",
                metadata={"task_id": str(task.id)},
                deep_link=f"/tasks/{task.id}",
            ),
        )

    await notification_bus.publish_many(changed_recipients)
    return task
```

Важен именно такой порядок:

1. Изменить задачу.
2. Добавить уведомление той же сессией.
3. Закоммитить PostgreSQL.
4. После commit вызвать Redis.

Если транзакция PostgreSQL откатилась, уведомления тоже не будет. Если Redis временно упал после commit, сама задача и уведомление уже сохранены. HTTP-запрос или резервный опрос клиента все равно покажет уведомление.

Ошибка Redis после commit не должна превращать успешное изменение задачи в ответ `500`. Ее надо записать в лог, а пользователю вернуть успешный результат операции с задачей.

Если одна операция создала несколько событий, собери измененных получателей в один `set` и вызови `publish_many` один раз после commit.

## 10. HTTP API

Во всех запросах `recipient_id` берется из текущего авторизованного пользователя. Клиент не передает чужой идентификатор.

### Получить список

```http
GET /api/notifications?limit=20&before_id=350&unread=true&category=tasks
```

Параметры:

- `limit`: по умолчанию 20, максимум 100;
- `before_id`: курсор для следующей страницы;
- `unread`: необязательный фильтр;
- `category`: необязательный фильтр;
- `important`: необязательный фильтр по `severity`.

Ответ:

```json
{
  "items": [
    {
      "id": 349,
      "type": "task.assigned",
      "category": "tasks",
      "severity": "important",
      "actor_id": 10,
      "entity_type": "task",
      "entity_id": "42",
      "title": "Вам назначили задачу: Подготовить отчет",
      "body": null,
      "metadata": {
        "task_id": "42"
      },
      "deep_link": "/tasks/42",
      "group_count": 1,
      "created_at": "2026-08-08T10:15:00Z",
      "read_at": null
    }
  ],
  "has_more": true,
  "next_before_id": 349
}
```

Запрос сортируется по `id DESC`. Для страницы нужно взять `limit + 1` строку. Если лишняя строка есть, `has_more` равен `true`, а клиенту возвращаются только первые `limit` строк.

Не используй `offset` для бесконечной ленты. При появлении новых уведомлений страницы с `offset` начинают пересекаться или пропускать записи. Курсор по `id` от этого не страдает.

### Получить счетчики

```http
GET /api/notifications/unread-count
```

```json
{
  "total": 7,
  "important": 2,
  "by_category": {
    "tasks": 7
  }
}
```

### Отметить выбранные уведомления прочитанными

```http
POST /api/notifications/read
Content-Type: application/json

{
  "ids": [349, 348]
}
```

SQL-условие обновления обязательно включает текущего пользователя:

```sql
UPDATE notification
SET read_at = now()
WHERE recipient_id = :current_user_id
  AND id = ANY(:ids)
  AND read_at IS NULL;
```

### Отметить все прочитанными

```http
POST /api/notifications/read
Content-Type: application/json

{
  "all": true,
  "category": "tasks"
}
```

Если `category` не передана, отмечаются все уведомления текущего пользователя.

### Вернуть уведомление в непрочитанные

```http
POST /api/notifications/349/unread
```

Здесь тоже должно быть условие `recipient_id = current_user.id`.

После успешного commit операций `read`, `read all` и `unread` отправь этому же пользователю `notification.invalidate`. Тогда счетчик обновится сразу во всех его вкладках и устройствах.

### Pydantic-схемы для команд

```python
from pydantic import BaseModel, Field, model_validator


class MarkNotificationsRead(BaseModel):
    ids: list[int] = Field(default_factory=list, max_length=100)
    all: bool = False
    category: str | None = None

    @model_validator(mode="after")
    def validate_mode(self):
        if self.all == bool(self.ids):
            raise ValueError("Передайте ids или all=true")
        return self
```

Проверки прав доступа должны быть в запросах репозитория, а не только в роуте. Так случайный вызов репозитория из другого места не позволит изменить чужое уведомление.

## 11. Локальные SSE-подписчики

Один пользователь может открыть несколько вкладок и несколько устройств. Каждому открытому SSE-потоку нужна отдельная очередь.

В памяти конкретного процесса FastAPI структура выглядит так:

```text
user_id -> set очередей открытых SSE-потоков
```

Очередь можно ограничить одним элементом. В нее кладется не само уведомление, а сигнал о том, что данные изменились. Если один такой сигнал уже ожидает отправки, второй ничего не добавит.

```python
import asyncio


class SSEHub:
    def __init__(self) -> None:
        self._subscribers: dict[int, set[asyncio.Queue[dict]]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, user_id: int) -> asyncio.Queue[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1)

        async with self._lock:
            self._subscribers.setdefault(user_id, set()).add(queue)

        return queue

    async def unsubscribe(
        self,
        user_id: int,
        queue: asyncio.Queue[dict],
    ) -> None:
        async with self._lock:
            user_subscribers = self._subscribers.get(user_id)
            if user_subscribers is None:
                return

            user_subscribers.discard(queue)
            if not user_subscribers:
                self._subscribers.pop(user_id, None)

    async def publish_to_user(self, user_id: int, message: dict) -> None:
        async with self._lock:
            queues = list(self._subscribers.get(user_id, set()))

        for queue in queues:
            if queue.full():
                continue
            queue.put_nowait(message)

    async def connection_count(self) -> int:
        async with self._lock:
            return sum(len(items) for items in self._subscribers.values())
```

У каждой вкладки своя очередь, поэтому все вкладки пользователя получат сигнал. Медленный клиент не расходует память бесконечно: в его очереди может лежать максимум одна инвалидация.

## 12. SSE endpoint и авторизация

Адрес потока:

```text
GET /api/notifications/stream
```

В FastAPI `0.135.0` появились встроенные `EventSourceResponse` и `ServerSentEvent`. `EventSourceResponse` сам выставляет `Content-Type: text/event-stream`, запрещает кеширование, отключает буферизацию Nginx через заголовок и отправляет keepalive-комментарий каждые 15 секунд простоя.

```python
from collections.abc import AsyncIterable

from fastapi import APIRouter, Depends, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent


router = APIRouter(prefix="/api/notifications")


def get_sse_hub(request: Request) -> SSEHub:
    return request.app.state.sse_hub


@router.get("/stream", response_class=EventSourceResponse)
async def stream_notifications(
    current_user: User = Depends(get_current_user),
    hub: SSEHub = Depends(get_sse_hub),
) -> AsyncIterable[ServerSentEvent]:
    queue = await hub.subscribe(current_user.id)

    try:
        yield ServerSentEvent(
            event="ready",
            data={"type": "ready"},
            retry=3000,
        )

        while True:
            message = await queue.get()
            yield ServerSentEvent(
                event="notification.invalidate",
                data=message,
            )
    finally:
        await hub.unsubscribe(current_user.id, queue)
```

Объяви `/stream` раньше динамического роута вроде `/{notification_id}` или вынеси поток в отдельный router. Иначе строка `stream` может попасть в параметр `notification_id` и дать `422`.

Обычная dependency `get_current_user` должна проверять пользователя так же, как в остальных HTTP endpoint. `user_id` нельзя принимать из query string.

Для браузера удобнее всего существующая HttpOnly cookie. При подключении к тому же origin браузер передаст ее автоматически. Если frontend находится на другом origin, создавай `EventSource` с `withCredentials: true`, а в CORS указывай точный frontend origin и `allow_credentials=True`. Wildcard `*` с credential cookie использовать нельзя.

Нативный `EventSource` не позволяет установить произвольный заголовок `Authorization`. Не передавай основной access token в URL: query string часто попадает в access-логи. Если сервис использует только Bearer token и cookie добавить нельзя, сделай короткоживущий SSE ticket. Это отдельный одноразовый токен, который живет около 30 секунд и нужен только для открытия потока.

Схема с ticket:

1. Клиент вызывает `POST /api/notifications/stream-ticket` с обычным `Authorization`.
2. Backend создает случайный токен и кладет в Redis `sse-ticket:<hash>` со значением `user_id` и TTL 30 секунд.
3. Клиент открывает `/api/notifications/stream?ticket=<token>`.
4. SSE endpoint атомарно забирает ticket через `GETDEL` и больше его не принимает.
5. В логах query string для этого endpoint отключается или маскируется.

Основной вариант документа все равно использует HttpOnly cookie, потому что он проще и не добавляет отдельный протокол авторизации.

`Last-Event-ID` здесь не нужен. SSE передает только инвалидацию, а не журнал событий. После любого подключения клиент заново читает состояние из PostgreSQL. Это надежнее попытки восстановить пропущенные Redis Pub/Sub-сигналы.

Авторизация проверяется в момент открытия потока. Если сервис должен быстро замечать отзыв сессии или истечение JWT, ограничь срок одного SSE-соединения, например 15 минутами. После закрытия `EventSource` автоматически подключится заново, а dependency еще раз проверит пользователя.

### Настройка reverse proxy

SSE является долгим HTTP-ответом. Прокси не должен буферизовать его или закрывать раньше keepalive.

Пример для Nginx:

```nginx
location /api/notifications/stream {
    proxy_pass http://fastapi;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 1h;
}
```

FastAPI уже отправляет `X-Accel-Buffering: no`, но явная настройка Nginx делает поведение понятным. Для другого ingress или load balancer выставь idle timeout больше 15 секунд. В production желательно включить HTTP/2 со стороны браузера, чтобы несколько вкладок не конкурировали за небольшой лимит HTTP/1.1-соединений.

- [SSE в FastAPI](https://fastapi.tiangolo.com/tutorial/server-sent-events/)
- [EventSource в браузере](https://developer.mozilla.org/en-US/docs/Web/API/EventSource)
- [Видео на русском: Server-Sent Events на практике](https://www.youtube.com/watch?v=m9TDaOXTRKQ)

## 13. Redis bus

Каждый процесс FastAPI хранит только свои локальные SSE-потоки. Если запущено несколько процессов или контейнеров, процесс, который изменил задачу, не знает, в каком процессе открыт браузер получателя. Redis рассылает сигнал всем процессам, а каждый процесс кладет его только в локальные очереди нужного пользователя.

Канал для пользователя:

```text
notifications:user:<user_id>
```

Один фоновый listener в каждом процессе подписывается по шаблону:

```text
notifications:user:*
```

Реализация:

```python
import asyncio
import json
import logging

import redis.asyncio as redis
from redis.exceptions import RedisError


logger = logging.getLogger(__name__)


class RedisNotificationBus:
    CHANNEL_PREFIX = "notifications:user:"

    def __init__(
        self,
        client: redis.Redis,
        hub: SSEHub,
    ) -> None:
        self.client = client
        self.hub = hub

    async def publish_many(self, user_ids: set[int]) -> None:
        if not user_ids:
            return

        message = json.dumps({"type": "notification.invalidate"})

        for user_id in user_ids:
            try:
                await self.client.publish(
                    f"{self.CHANNEL_PREFIX}{user_id}",
                    message,
                )
            except RedisError:
                logger.exception(
                    "Failed to publish notification invalidation",
                    extra={"user_id": user_id},
                )

    async def listen_forever(self) -> None:
        delay = 1

        while True:
            try:
                async with self.client.pubsub() as pubsub:
                    await pubsub.psubscribe(f"{self.CHANNEL_PREFIX}*")
                    delay = 1

                    async for message in pubsub.listen():
                        if message["type"] != "pmessage":
                            continue

                        channel = message["channel"]
                        user_id = int(channel.removeprefix(self.CHANNEL_PREFIX))
                        payload = json.loads(message["data"])
                        await self.hub.publish_to_user(user_id, payload)

            except asyncio.CancelledError:
                raise
            except (RedisError, ValueError, json.JSONDecodeError):
                logger.exception("Redis notification listener failed")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
```

Клиент `redis.Redis` можно разделять между запросами и задачами. Объект `PubSub` нельзя одновременно использовать из нескольких независимых задач. В коде выше `PubSub` принадлежит только одному listener.

Не ставь короткий `socket_timeout` на client, который обслуживает Pub/Sub. Отсутствие уведомлений в течение нескольких минут является нормальным, а короткий timeout будет рвать здоровое соединение. `socket_connect_timeout` оставить можно: он ограничивает только установку нового соединения.

На небольшом и среднем таск-трекере подписка по шаблону достаточно проста. Если поток уведомлений станет очень большим, можно перейти на динамические подписки только для пользователей, у которых есть локальные SSE-потоки. До появления реальной нагрузки это усложнение не нужно.

## 14. Запуск Redis listener вместе с FastAPI

Lifespan в FastAPI запускает ресурсы при старте процесса и закрывает их при остановке. Здесь он нужен, чтобы создать один Redis client, один SSE hub и один Redis listener на весь срок жизни процесса.

```python
import asyncio
from contextlib import asynccontextmanager, suppress

import redis.asyncio as redis
from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_client = redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=2,
        health_check_interval=30,
    )

    sse_hub = SSEHub()
    notification_bus = RedisNotificationBus(redis_client, sse_hub)
    listener_task = asyncio.create_task(
        notification_bus.listen_forever()
    )

    app.state.redis = redis_client
    app.state.sse_hub = sse_hub
    app.state.notification_bus = notification_bus

    try:
        yield
    finally:
        listener_task.cancel()
        with suppress(asyncio.CancelledError):
            await listener_task
        await redis_client.aclose()


app = FastAPI(lifespan=lifespan)
```

Не создавай новый Redis client в каждом HTTP-запросе. Один client уже управляет пулом соединений и должен жить вместе с процессом FastAPI.

Bus для операций создания и прочтения уведомлений можно получать из `app.state`:

```python
from fastapi import Request


def get_notification_bus(request: Request) -> RedisNotificationBus:
    return request.app.state.notification_bus
```

- [Lifespan в FastAPI](https://fastapi.tiangolo.com/advanced/events/)
- [Жизненный цикл async redis-py](https://redis.io/docs/latest/develop/clients/redis-py/async/#cleanup-and-lifecycle)

## 15. Что должен делать клиент

Backend и frontend должны заранее договориться об этом поведении:

1. После входа клиент запрашивает список и счетчик через HTTP.
2. Клиент открывает `/api/notifications/stream` через `EventSource`.
3. После открытия SSE клиент еще раз обновляет список и счетчик. Это закрывает промежуток между первым HTTP-запросом и подключением потока.
4. На `notification.invalidate` клиент повторяет HTTP-запросы списка и счетчика.
5. При разрыве соединения `EventSource` переподключается сам. Сервер передает рекомендуемую задержку 3 секунды через поле `retry`.
6. При событии браузера `online` клиент сразу обновляет данные.
7. Пока вкладка видима и есть интернет, клиент раз в 60 секунд обновляет счетчик. Это страховка на случай пропущенного Redis Pub/Sub-сигнала.
8. Получение уведомления не означает его прочтение. `read_at` меняется только после действия пользователя.
9. При выходе пользователя из аккаунта клиент вызывает `source.close()`.

Пример обработчика:

```javascript
let refreshTimer = null;

function scheduleNotificationRefresh() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(refreshNotifications, 100);
}

function connectNotifications() {
  const source = new EventSource("/api/notifications/stream");

  source.onopen = () => {
    scheduleNotificationRefresh();
  };

  source.addEventListener("notification.invalidate", () => {
    scheduleNotificationRefresh();
  });

  source.onerror = () => {
    // EventSource переподключится автоматически.
  };

  return source;
}

const notificationSource = connectNotifications();

window.addEventListener("online", scheduleNotificationRefresh);
```

Задержка 100 миллисекунд объединяет серию сигналов в одно обновление списка. Она не влияет на хранение уведомлений.

Для frontend на другом origin:

```javascript
const source = new EventSource(
  "https://api.example.com/api/notifications/stream",
  { withCredentials: true }
);
```

`deep_link` надо проверять перед переходом. Разрешены только внутренние пути, которые начинаются с одного `/`. Значения с `http://`, `https://`, `//`, обратным слешем и управляющими символами надо отклонять.

Каждая вкладка открывает свой SSE-поток. При большом количестве вкладок можно оставить поток только в одной вкладке, а остальные уведомлять через `BroadcastChannel`. Это оптимизация, а не обязательная часть первого релиза.

## 16. Группировка похожих уведомлений

Без группировки десять комментариев подряд создадут десять строк. После основной версии можно объединять похожие непрочитанные уведомления в течение десяти минут.

Пример:

```text
grouping_key = task.comments:42
```

Алгоритм внутри транзакции:

1. Найти последнее непрочитанное уведомление текущего получателя с тем же `grouping_key`, созданное не более десяти минут назад.
2. Заблокировать строку через `SELECT ... FOR UPDATE`.
3. Если строка найдена, увеличить `group_count`, заменить заголовок, автора, текст и `created_at`.
4. Если строки нет, создать новую.
5. После commit отправить обычный `notification.invalidate`.

Пример результата:

```text
Иван и еще 4 человека оставили комментарии в задаче "Подготовить отчет"
```

Группировку надо добавлять после обычного создания уведомлений и тестов на идемпотентность. Она не должна быть условием запуска первой рабочей версии.

## 17. Напоминания о дедлайне

Для `task.deadline_reminder` нужен отдельный периодический worker. Он раз в несколько минут ищет задачи, дедлайн которых скоро наступит.

Пример запроса для напоминания за 24 часа:

```sql
SELECT t.id, t.title, t.deadline, a.user_id
FROM task t
JOIN task_assignee a ON a.task_id = t.id
WHERE t.deadline > now()
  AND t.deadline <= now() + interval '24 hours'
  AND t.status NOT IN ('done', 'cancelled');
```

Для каждой пары задача-получатель создается событие с детерминированным `event_id`. Уникальный индекс в `notification` не даст worker создать дубль при следующем запуске.

Не полагайся только на поле вроде `reminder_sent = true` в задаче, если напоминаний несколько. Идентификатор должен учитывать задачу, пользователя, точное значение дедлайна и окно напоминания. После изменения дедлайна новое напоминание получит другой `event_id`.

Периодический worker можно запускать через уже используемый в проекте механизм. Если фоновых задач пока нет, для разработки подойдет отдельный процесс с бесконечным циклом и паузой. Не запускай такой цикл внутри каждого HTTP worker без блокировки, иначе каждый процесс будет выполнять одинаковую работу. Уникальный `event_id` защитит от дублей, но лишняя работа останется.

## 18. Email и push как следующий этап

Outbox здесь означает обычную таблицу PostgreSQL с заданиями на отправку. Она нужна, чтобы email или push не исчез после падения worker.

Realtime в браузере уже надежно восстанавливается из таблицы `notification`, поэтому для первой версии outbox не обязателен. Для email и push он обязателен.

Минимальная таблица:

```sql
CREATE TABLE notification_outbox (
    id bigserial PRIMARY KEY,
    notification_id bigint NOT NULL REFERENCES notification(id) ON DELETE CASCADE,
    channel varchar(16) NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'pending',
    attempts integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    last_error text NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    sent_at timestamptz NULL,
    UNIQUE (notification_id, channel)
);
```

Строка уведомления и строки outbox создаются в одной транзакции. Worker забирает задания со статусом `pending`, отправляет их, а затем ставит `sent`. При ошибке увеличивает `attempts` и назначает следующую попытку. Для параллельных worker используется `FOR UPDATE SKIP LOCKED`.

Настройки email, push, тихих часов и часового пояса стоит добавлять вместе с outbox, а не смешивать с первой реализацией браузерных уведомлений.

## 19. Ошибки, которые нельзя допустить

- Хранить уведомления только в Redis Pub/Sub. Отключившийся пользователь их потеряет.
- Отправлять Redis-сигнал до commit PostgreSQL. Клиент может запросить список раньше, чем строка станет видна.
- Делать `commit` внутри `NotificationRepository`. Изменение задачи и уведомление перестанут быть одной транзакцией.
- Передавать `recipient_id` от клиента в API списка или прочтения.
- Хранить только одну SSE-очередь на пользователя. Вторая вкладка тогда вытеснит первую.
- Держать соединения только в памяти и не использовать Redis при нескольких процессах FastAPI.
- Делать очередь инвалидаций неограниченной. Для одного потока достаточно одного ожидающего сигнала.
- Генерировать новый `event_id` при каждом retry одной операции.
- Считать уведомление прочитанным сразу после доставки по SSE.
- Полагаться только на SSE без обновления при подключении и резервного опроса.
- Передавать основной access token в URL SSE-потока.
- Оставлять буферизацию или короткий idle timeout на reverse proxy.
- Разрешать внешние URL в `deep_link`.
- Возвращать `500` на успешное изменение задачи только потому, что Redis временно недоступен.

## 20. Порядок реализации

### Шаг 1. Хранение

Создать миграцию, SQLAlchemy-модель и репозиторий. Реализовать список, счетчик, `read` и `unread`. На этом этапе SSE и Redis не нужны.

### Шаг 2. Первое событие

Добавить `NotificationEvent`, `NotificationService` и событие `task.assigned`. Проверить, что уведомление создается в одной транзакции с назначением исполнителя и не создается для автора действия.

### Шаг 3. SSE в одном процессе

Добавить `SSEHub`, авторизованный SSE endpoint и отправить тестовый `notification.invalidate` в две локальные очереди одного пользователя.

### Шаг 4. Redis

Поднять Redis, добавить `RedisNotificationBus`, process-level listener и lifespan. Запустить два процесса FastAPI и проверить, что изменение в одном процессе доходит до SSE-потока во втором.

### Шаг 5. Клиентское восстановление

Добавить обновление по HTTP после открытия потока, автоматическое переподключение `EventSource` и резервный опрос раз в 60 секунд.

### Шаг 6. Остальные события

Добавить снятие с задачи, изменение дедлайна, комментарии и статус. После этого сделать worker для напоминаний.

### Шаг 7. Доводка

Добавить группировку комментариев, метрики, ограничения очередей и при необходимости outbox для email или push.

## 21. Что проверить тестами

### Репозиторий и HTTP API

- один `event_id` для одного получателя не создает две строки;
- одно событие может создать строки для нескольких получателей;
- автор действия удаляется из списка получателей;
- пользователь видит только свои уведомления;
- пользователь не может прочитать или вернуть в непрочитанные чужое уведомление;
- список идет по `id DESC`;
- `before_id` возвращает следующую страницу без дублей;
- `limit` больше 100 отклоняется или ограничивается;
- счетчик меняется после `read` и `unread`;
- `read all` затрагивает только текущего пользователя;
- откат транзакции задачи откатывает и уведомление.

### SSE

- endpoint без авторизации отвечает `401`;
- ответ имеет `Content-Type: text/event-stream`;
- первым приходит событие `ready` с `retry: 3000`;
- две очереди одного пользователя получают сигнал;
- другой пользователь сигнал не получает;
- после закрытия потока очередь удаляется из `SSEHub`;
- несколько сигналов объединяются в одну ожидающую инвалидацию;
- сигнал, опубликованный одним процессом, приходит в SSE-поток другого процесса;
- reverse proxy не буферизует поток и не закрывает его между keepalive.

### Отказы

- при выключенном Redis изменение задачи и запись уведомления работают;
- после восстановления Redis listener переподключается;
- пользователь, который был offline, видит уведомление через HTTP;
- повторный запуск deadline worker не создает дубль;
- после изменения дедлайна создается новое напоминание, а не старое.

Логику локальной доставки сначала проверь отдельно от HTTP:

```python
import pytest


@pytest.mark.anyio
async def test_sse_hub_delivers_to_all_tabs():
    hub = SSEHub()
    first_tab = await hub.subscribe(user_id=7)
    second_tab = await hub.subscribe(user_id=7)

    await hub.publish_to_user(
        7,
        {"type": "notification.invalidate"},
    )

    assert (await first_tab.get())["type"] == "notification.invalidate"
    assert (await second_tab.get())["type"] == "notification.invalidate"


def test_sse_requires_auth(client):
    response = client.get("/api/notifications/stream")
    assert response.status_code == 401
```

Для интеграционного теста добавь авторизационную cookie, открой streaming response и опубликуй сигнал через тестовый Redis или замену `RedisNotificationBus`. Тест должен дождаться строк `event: notification.invalidate` и `data: ...`, а затем закрыть поток.

- [Тестирование FastAPI](https://fastapi.tiangolo.com/tutorial/testing/)
- [Формат событий SSE в FastAPI](https://fastapi.tiangolo.com/tutorial/server-sent-events/)

## 22. Логи и метрики

В логах нужны:

- `event_id`, `type` и количество получателей при создании;
- ошибка Redis publish с `user_id`;
- переподключение Redis listener;
- подключение и отключение SSE без записи токена;
- количество объединенных инвалидаций при заполненной очереди;
- ошибки deadline worker.

Полезные метрики:

- число активных SSE-потоков;
- число пользователей с активными соединениями;
- количество созданных уведомлений по `type`;
- количество Redis publish ошибок;
- количество переподключений listener;
- количество переподключений SSE, если frontend отправляет такую метрику;
- длительность запросов списка и счетчика;
- количество pending и failed заданий outbox, если он появился.

В логах и метриках нельзя хранить access token, полный текст приватных комментариев и другие чувствительные данные из `metadata`.

## 23. Когда задача готова

- [ ] Есть миграция `notification` и все индексы.
- [ ] FastAPI обновлен минимум до `0.135.0`.
- [ ] Уведомление хранится в PostgreSQL, а не только в Redis.
- [ ] Работают список, счетчик, `read`, `read all` и `unread`.
- [ ] Все запросы ограничены текущим пользователем.
- [ ] Есть единый `NotificationService`.
- [ ] `task.assigned` создается в одной транзакции с назначением.
- [ ] Автор действия не получает собственное уведомление.
- [ ] Повтор одного `event_id` не создает дубль.
- [ ] SSE endpoint авторизован через ту же dependency, что и обычный HTTP API.
- [ ] Основной access token не передается в URL потока.
- [ ] Несколько вкладок одного пользователя получают сигнал.
- [ ] Reverse proxy не буферизует SSE и держит соединение между keepalive.
- [ ] Redis listener запускается через lifespan и восстанавливается после ошибки.
- [ ] Два процесса FastAPI доставляют сигнал через Redis.
- [ ] Redis publish выполняется только после commit PostgreSQL.
- [ ] Падение Redis не ломает изменение задачи и HTTP-чтение уведомлений.
- [ ] Клиент обновляет данные после подключения и на `notification.invalidate`.
- [ ] `EventSource` автоматически переподключается, а клиент делает резервный опрос.
- [ ] Реализованы события назначения, снятия, дедлайна, комментария и статуса.
- [ ] Deadline worker не создает дубли.
- [ ] Есть тест с offline-пользователем.
- [ ] Есть тест доставки между двумя процессами.

После выполнения этого списка уведомления переживают перезапуск браузера, временное падение Redis и запуск FastAPI в нескольких процессах. Realtime остается быстрым, а сами данные не зависят от надежности SSE или Pub/Sub.
