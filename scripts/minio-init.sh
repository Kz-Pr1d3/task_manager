#!/usr/bin/env bash
# Инициализация бакета MinIO: private + lifecycle (tmp/pending).
# Idempotent. Аналог db/scripts/init.sql для объектного хранилища.
#
# CORS на этом стеке задаётся на сервере MinIO (не PutBucketCors):
#   MINIO_API_CORS_ALLOW_ORIGIN (см. docker-compose / README).
# Abort incomplete multipart — через MINIO_API_STALE_UPLOADS_EXPIRY
# (S3 AbortIncompleteMultipartUpload в lifecycle XML MinIO отклоняет).
#
# Env:
#   MINIO_ENDPOINT      default http://localhost:9000
#   MINIO_ROOT_USER     default minioadmin
#   MINIO_ROOT_PASSWORD default minioadmin
#   MINIO_BUCKET        default task-manager-media
#   MINIO_ALIAS         default local
#   MC_BIN              default mc
#
# Запуск:
#   ./scripts/minio-init.sh
#   docker compose up -d   # поднимает minio-init автоматически

set -euo pipefail

MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://localhost:9000}"
MINIO_ROOT_USER="${MINIO_ROOT_USER:-minioadmin}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-minioadmin}"
MINIO_BUCKET="${MINIO_BUCKET:-task-manager-media}"
MINIO_ALIAS="${MINIO_ALIAS:-local}"
MC_BIN="${MC_BIN:-mc}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIFECYCLE_JSON="${SCRIPT_DIR}/minio/lifecycle.json"

if ! command -v "${MC_BIN}" >/dev/null 2>&1; then
  echo "mc not found (MC_BIN=${MC_BIN}). Install MinIO Client or use docker compose minio-init." >&2
  exit 1
fi

if [[ ! -f "${LIFECYCLE_JSON}" ]]; then
  echo "lifecycle json missing: ${LIFECYCLE_JSON}" >&2
  exit 1
fi

echo "Waiting for MinIO at ${MINIO_ENDPOINT} ..."
for _ in $(seq 1 60); do
  if curl -sf "${MINIO_ENDPOINT}/minio/health/live" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if ! curl -sf "${MINIO_ENDPOINT}/minio/health/live" >/dev/null 2>&1; then
  echo "MinIO not ready: ${MINIO_ENDPOINT}" >&2
  exit 1
fi

"${MC_BIN}" alias set "${MINIO_ALIAS}" "${MINIO_ENDPOINT}" \
  "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}" >/dev/null

TARGET="${MINIO_ALIAS}/${MINIO_BUCKET}"

# Бакет (идемпотентно)
"${MC_BIN}" mb --ignore-existing "${TARGET}"

# Приватный доступ: без anonymous download/upload
"${MC_BIN}" anonymous set none "${TARGET}"

# Lifecycle: expire tmp/pending/ через 1 день (идемпотентный import с фиксированным ID)
"${MC_BIN}" ilm import "${TARGET}" < "${LIFECYCLE_JSON}"

echo "MinIO bucket ready: ${TARGET}"
echo "  private: anonymous=none"
echo "  lifecycle: drop-abandoned-tmp (tmp/pending/ → 1d)"
echo "  CORS / stale uploads: server env on minio service (see docker-compose)"
