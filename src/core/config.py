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

    # S3 / MinIO (dev defaults = docker-compose minio)
    s3_endpoint_url: str = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin"
    s3_bucket: str = "task-manager-media"
    s3_presigned_put_ttl_sec: int = 600
    s3_presigned_get_ttl_sec: int = 120
    attachment_max_bytes: int = 10_485_760  # 10 MiB
    attachment_max_per_task: int = 5
    # ATTACHMENT_PENDING_TTL — возраст pending до чистки БД (default 24h)
    attachment_pending_ttl: timedelta = timedelta(hours=24)
    # ATTACHMENT_CLEANUP_INTERVAL_SEC — пауза между тиками cleanup worker
    attachment_cleanup_interval_sec: int = 3600

    # DEADLINE_REMINDER_WINDOW — timedelta (напр. 24:00:00); default 24h
    deadline_reminder_window: timedelta = timedelta(hours=24)
    # DEADLINE_WORKER_INTERVAL_SEC — пауза между тиками (60–300)
    deadline_worker_interval_sec: int = 120


configs = Configs()
