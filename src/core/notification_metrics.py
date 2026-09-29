"""Prometheus-метрики realtime-уведомлений (не через BaseHTTPMiddleware)."""

from prometheus_client import Counter, Gauge

SSE_ACTIVE_STREAMS = Gauge(
    "notification_sse_active_streams",
    "Active SSE notification streams in this process",
)

NOTIFICATIONS_CREATED = Counter(
    "notifications_created_total",
    "Notifications inserted into PostgreSQL",
    ["type"],
)

REDIS_PUBLISH_ERRORS = Counter(
    "notification_redis_publish_errors_total",
    "Redis PUBLISH failures for notification invalidate",
)

DEADLINE_WORKER_RUNS = Counter(
    "deadline_reminder_worker_runs_total",
    "Deadline reminder worker tick executions",
)

DEADLINE_WORKER_CANDIDATES = Counter(
    "deadline_reminder_worker_candidates_total",
    "Tasks considered by deadline reminder worker ticks",
)
