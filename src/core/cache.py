import redis.asyncio as redis

redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    return redis_client
