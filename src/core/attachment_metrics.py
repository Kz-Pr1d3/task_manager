"""Prometheus-метрики вложений / cleanup worker."""

from prometheus_client import Counter, Gauge

ATTACHMENT_CLEANUP_RUNS = Counter(
    "attachment_cleanup_worker_runs_total",
    "Attachment cleanup worker tick executions",
)

ATTACHMENT_CLEANUP_DELETED = Counter(
    "attachment_cleanup_deleted_total",
    "Stale pending attachment rows deleted by cleanup worker",
)

ATTACHMENT_PENDING_GAUGE = Gauge(
    "attachment_pending_total",
    "Current pending attachment rows (hanging uploads)",
)
