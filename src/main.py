from fastapi import FastAPI

from src.core.config import configs


class AppCreator:
    """Класс для создания FastAPI приложения."""

    def __init__(self):
        """Создание экземпляра FastAPI приложения."""

        self.app = FastAPI(
            title=configs.app_name,
            version="1.0.0",
        )

        # self.app.include_router()
        # self.app.add_middleware()
        # self.app.add_exception_handler()


app_creator = AppCreator()
app = app_creator.app


@app.get("/health")
async def health():
    return {"status": "ok"}
