import redis.asyncio as redis

redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """
    Возвращает глобальный Redis-клиент приложения.

    :returns: экземпляр ``redis.Redis`` (инициализируется в lifespan).
    """
    return redis_client
