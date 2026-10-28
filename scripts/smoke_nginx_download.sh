#!/usr/bin/env bash
# Smoke: download вложения через nginx (:8080) + X-Accel → MinIO.
#
# Prefers:
#   docker compose up -d
#   ATTACHMENT_DOWNLOAD_MODE=x_accel в .env
#   uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
#
# Запуск:
#   ./scripts/smoke_nginx_download.sh
#   ./scripts/smoke_nginx_download.sh --keep   # оставить файл + напечатать curl
#   SMOKE_BASE=http://127.0.0.1:8080 ./scripts/smoke_nginx_download.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BASE_ARGS=()
if [[ -n "${SMOKE_BASE:-}" ]]; then
  BASE_ARGS=(--base "$SMOKE_BASE")
fi

exec python scripts/smoke_nginx_download.py "${BASE_ARGS[@]}" "$@"
