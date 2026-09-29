from datetime import timedelta
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Configs(BaseSettings):
    """Настройки приложения из окружения и .env."""

    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env")

    app_name: str = "Task Manager"
    database_url: str
    secret_key: str
    debug: bool = False
    session_key: str
    private_key_password: str
    private_key_path: str
    public_key_path: str

    enable_tracing: bool = False
    backend_service_name: str = "my-backend"

    enable_metrics: bool = False

    redis_url: str = "redis://localhost:6379/0"

    # DEADLINE_REMINDER_WINDOW — timedelta (напр. 24:00:00); default 24h
    deadline_reminder_window: timedelta = timedelta(hours=24)
    # DEADLINE_WORKER_INTERVAL_SEC — пауза между тиками (60–300)
    deadline_worker_interval_sec: int = 120


configs = Configs()
