import asyncio
from contextlib import asynccontextmanager, suppress

import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app
from starlette.middleware.sessions import SessionMiddleware

from src.api.auth import auth_router
from src.api.v1.router import v1_router
from src.core import cache
from src.core.config import configs
from src.core.database import db
from src.core.keys import Keys
from src.core.redis_notification_bus import RedisNotificationBus
from src.core.sse_hub import SSEHub
from src.middleware.logging import LoggingMiddleware
from src.middleware.metrics import MetricsMiddleware
from src.middleware.tracing import TracingMiddleware, setup_tracing


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """
    Startup/shutdown: keys, DB pool, Redis, SSEHub, Redis bus listener.

    Redis client без ``decode_responses`` (как ticket GETDEL / auth).
    Bus сам нормализует bytes/str в pubsub.

    :param app: экземпляр FastAPI.
    """
    if configs.enable_tracing:
        setup_tracing(configs.backend_service_name)

    Keys.load_keys()
    await db.connect()

    pool = redis.ConnectionPool.from_url(configs.redis_url)
    cache.redis_client = redis.Redis.from_pool(pool)
    await cache.redis_client.ping()

    sse_hub = SSEHub()
    notification_bus = RedisNotificationBus(
        client=cache.redis_client,
        hub=sse_hub,
    )
    listener_task = asyncio.create_task(notification_bus.listen_forever())

    app.state.sse_hub = sse_hub
    app.state.notification_bus = notification_bus

    try:
        yield
    finally:
        listener_task.cancel()
        with suppress(asyncio.CancelledError):
            await listener_task

        await db.disconnect()

        if cache.redis_client:
            await cache.redis_client.aclose()
            cache.redis_client = None


class AppCreator:
    """Класс для создания FastAPI приложения."""

    def __init__(self, lifespan=None):
        """
        Создание экземпляра FastAPI приложения.

        :param lifespan: async context manager startup/shutdown.
        """

        self.app = FastAPI(
            title=configs.app_name,
            version="1.0.0",
            lifespan=lifespan,
        )

        self.app.include_router(router=auth_router)
        self.app.add_middleware(
            middleware_class=CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self.app.add_middleware(
            middleware_class=SessionMiddleware,
            secret_key=configs.session_key,
            session_cookie="SESSION_ID",
            same_site="strict",
            https_only=True,
        )

        if configs.enable_tracing:
            self.app.add_middleware(TracingMiddleware)

        if configs.enable_metrics:
            self.app.add_middleware(MetricsMiddleware)

        self.app.add_middleware(LoggingMiddleware)

        if configs.enable_metrics:
            metrics_app = make_asgi_app()
            self.app.mount("/metrics", metrics_app)

        self.app.include_router(router=auth_router)
        self.app.include_router(router=v1_router)


app_creator = AppCreator(lifespan=app_lifespan)
app = app_creator.app


@app.get("/health")
async def health():
    """
    Liveness-проверка сервиса.

    :returns: ``{"status": "ok"}``.
    """
    return {"status": "ok"}
