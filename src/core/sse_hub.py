import asyncio

from src.core.notification_metrics import SSE_ACTIVE_STREAMS


class SSEHub:
    """
    Локальный хаб SSE-подписчиков одного процесса.

    ``user_id → set[Queue]``; очередь maxsize=1 сливает повторные
    ``notification.invalidate`` без роста памяти.
    """

    def __init__(self) -> None:
        """Инициализирует пустой реестр подписчиков."""
        self._subscribers: dict[int, set[asyncio.Queue[dict]]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, user_id: int) -> asyncio.Queue[dict]:
        """
        Регистрирует новую очередь для SSE-потока пользователя.

        :param user_id: идентификатор получателя.
        :returns: очередь сигналов (maxsize=1).
        """
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1)

        async with self._lock:
            self._subscribers.setdefault(user_id, set()).add(queue)

        SSE_ACTIVE_STREAMS.inc()
        return queue

    async def unsubscribe(
            self,
            user_id: int,
            queue: asyncio.Queue[dict],
    ) -> None:
        """
        Снимает очередь с подписки; чистит пустой набор user_id.

        :param user_id: идентификатор получателя.
        :param queue: очередь, созданная ``subscribe``.
        """
        removed = False
        async with self._lock:
            user_subscribers = self._subscribers.get(user_id)
            if user_subscribers is None:
                return

            if queue in user_subscribers:
                user_subscribers.discard(queue)
                removed = True
            if not user_subscribers:
                self._subscribers.pop(user_id, None)

        if removed:
            SSE_ACTIVE_STREAMS.dec()

    async def publish_to_user(self, user_id: int, message: dict) -> None:
        """
        Кладёт сигнал во все локальные очереди пользователя.

        Полные очереди пропускаются (уже есть ожидающая invalidate).

        :param user_id: идентификатор получателя.
        :param message: полезный payload (обычно invalidate).
        """
        async with self._lock:
            queues = list(self._subscribers.get(user_id, set()))

        for queue in queues:
            if queue.full():
                continue
            queue.put_nowait(message)

    async def connection_count(self) -> int:
        """
        Суммарное число активных SSE-очередей в процессе.

        :returns: количество подписчиков.
        """
        async with self._lock:
            return sum(len(items) for items in self._subscribers.values())
