# notifications/

Realtime-уведомления.

## Содержимое

| Файл | Что | Когда |
|------|-----|-------|
| [notifications_mvp.md](notifications_mvp.md) | скоуп MVP, статус, API, worker, инварианты commit→publish | любая работа по уведомлениям |
| [FastAPIRealtimeNotifications.md](FastAPIRealtimeNotifications.md) | длинный справочник: SSE hub, Redis bus, антипаттерны | архитектура/инварианты; не читать целиком ради CRUD |

Источник правды — Postgres. Redis — сигнал. SSE — `notification.invalidate`, не payload.
