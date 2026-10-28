# db/

Схема БД.

## Содержимое

| Файл | Что | Когда |
|------|-----|-------|
| [db.mdc](db.mdc) | Postgres 17, `asyncpg`, таблицы `users` / `lists` / `tasks` / `notification` / `task_attachment` | любой SQL, репозиторий, новая колонка |

DDL-истина: `db/scripts/init.sql`. Стиль запросов (CTE, timestamps из Python) — [../code/python.md](../code/python.md) §3.
