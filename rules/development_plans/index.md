# development_plans/

Планы фич. **Читай только папку своей задачи.** Сначала `index.md` фичи, потом секцию «Статус реализации».

## Содержимое

| Путь | Статус | Когда |
|------|--------|-------|
| [auth_dev.md](auth_dev.md) | sign-up/in/refresh/logout ✅; password policy / rate limit / email ❌ | auth, JWT, Redis refresh, session cookie |
| [api_prefix_dev.md](api_prefix_dev.md) | `/api/v1` + auth в v1 ✅ | публичный URL, `src/api/v1/auth.py`, nginx `location /api/`; дальше SSE-proxy |
| [tasks/](tasks/index.md) | CRUD+lifecycle+delete list ✅; virtual views ❌ | задачи, списки, пагинация |
| [notifications/](notifications/index.md) | шаги 1–5 ✅ | SSE, Redis bus, deadline worker |
| [s3/](s3/index.md) | presigned ✅; multipart ❌; prod ⏭ | вложения, MinIO, cleanup |
| [nginx/](nginx/index.md) | proxy + X-Accel ✅; SSE-safe proxy ❌; limits ⏭ | download / SSE через nginx, `:8080` |
| `S3_Redis_Nginx.docx` | исходная спека (Части I–III) | только если спор с md-планом; бинарник, не парсить без нужды |
