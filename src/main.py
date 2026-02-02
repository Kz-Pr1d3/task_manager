from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from src.api.auth import auth_router
from src.core.config import configs


class AppCreator:
    """Класс для создания FastAPI приложения."""

    def __init__(self):
        """Создание экземпляра FastAPI приложения."""

        self.app = FastAPI(
            title=configs.app_name,
            version="1.0.0",
        )

        self.app.include_router(router=auth_router)
        self.app.add_middleware(
            middleware_class=CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"]
        )
        self.app.add_middleware(
            middleware_class=SessionMiddleware,
            secret_key=configs.session_key,
            session_cookie="SESSION_ID",
            same_site="strict",
            https_only=True,
        )
        # self.app.add_exception_handler()


app_creator = AppCreator()
app = app_creator.app


@app.get("/health")
async def health():
    return {"status": "ok"}
