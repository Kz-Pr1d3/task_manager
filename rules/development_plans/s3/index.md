# s3/

Вложения к задачам (MinIO/S3). Спека: `../S3_Redis_Nginx.docx` (Часть I).

## Содержимое

| Файл | Что | Когда |
|------|-----|-------|
| [s3_dev.md](s3_dev.md) | presigned PUT + complete, ключи `tmp/`→`users/`, лимиты, cleanup, статус ✅ | upload/download/delete, бакет, lifecycle |
| [s3_multipart_dev.md](s3_multipart_dev.md) | файлы > 100 MiB (max 300 MiB) ❌ план | только если делаем multipart |
