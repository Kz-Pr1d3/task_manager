from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app
from starlette.middleware.sessions import SessionMiddleware

from src.api.auth import auth_router
from src.core.config import configs
from src.core.database import db
from src.middleware.logging import LoggingMiddleware
from src.middleware.metrics import MetricsMiddleware
from src.middleware.tracing import TracingMiddleware, setup_tracing


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    if configs.enable_tracing:
        setup_tracing(configs.backend_service_name)

    await db.connect()
    yield
    await db.disconnect()


class AppCreator:
    """Класс для создания FastAPI приложения."""

    def __init__(self, lifespan=None):
        """Создание экземпляра FastAPI приложения."""

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


app_creator = AppCreator(lifespan=app_lifespan)
app = app_creator.app


@app.get("/health")
async def health():
    return {"status": "ok"}
