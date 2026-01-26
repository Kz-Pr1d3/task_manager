from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Configs(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env")

    app_name: str = "Task Manager"
    database_url: str
    secret_key: str
    debug: bool = False


configs = Configs()
