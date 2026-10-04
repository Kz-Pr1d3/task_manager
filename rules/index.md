## Индекс правил проекта Task Manager

Документация по правилам разработки и стандартам проекта.

### Навигация по правилам

- [basics.md](basics.md) — структура проекта, архитектура, стек технологий
- [code/python.md](code/python.md) — стандарты Python: стиль, типизация, импорты, ошибки, SQL (минимум round-trip / CTE), докстринги (reST)
- [code/tests.md](code/tests.md) — стиль тестов: фикстуры, нейминг, без бездумных моков
- [db/db.mdc](db/db.mdc) — база данных: подключение, таблицы, драйвер

### Планы разработки

В каждом плане есть секция **«Статус реализации»** — сверяй с кодом перед работой.

- [development_plans/auth_dev.md](development_plans/auth_dev.md) — авторизация (sign-up/in/refresh/logout ✅)
- [development_plans/tasks/tasks_dev.md](development_plans/tasks/tasks_dev.md) — задачи/списки (CRUD+lifecycle+delete list ✅, views ❌)
- [development_plans/tasks/tasks_tech.md](development_plans/tasks/tasks_tech.md) — задачи: API, БД, технические заметки
- [development_plans/notifications/notifications_mvp.md](development_plans/notifications/notifications_mvp.md) — realtime-уведомления (шаги 1–5 ✅)
- [development_plans/s3/s3_dev.md](development_plans/s3/s3_dev.md) — S3 / MinIO, вложения к задачам (presigned) ✅ код (шаг 8 ⏭ нет прода)
- [development_plans/s3/s3_multipart_dev.md](development_plans/s3/s3_multipart_dev.md) — multipart upload > 100 MiB (max 300 MiB) ❌ план
- [development_plans/nginx/nginx_dev.md](development_plans/nginx/nginx_dev.md) — Nginx reverse proxy + X-Accel-Redirect → S3 ❌ план

### Обновление правил

Регулярно обновляй правила в этом разделе в соответствии с развитием проекта и изменением требований.
После значимых фич — обновляй статусы в development_plans.

