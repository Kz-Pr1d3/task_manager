# nginx/

Reverse proxy + X-Accel download + SSE-safe proxy. Спека: `../S3_Redis_Nginx.docx` (Часть III).

## Содержимое

| Файл | Что | Когда |
|------|-----|-------|
| [nginx_dev.md](nginx_dev.md) | `:8080` → uvicorn `:8000`, `location /internal-s3/` + `internal`, `ATTACHMENT_DOWNLOAD_MODE` | proxy, download, smoke download |
| [nginx_sse_dev.md](nginx_sse_dev.md) | `location /api/v1/notifications/stream`: buffering off, timeout 1h, smoke SSE | SSE через nginx; [api_prefix_dev.md](../api_prefix_dev.md) ✅ |

Upload не через nginx (presigned PUT). `limit_req` / `limit_conn` / `real_ip` — отдельный план (`nginx_limits_dev.md`, ⏭). Конфиг: `docker/nginx/nginx.conf`.
