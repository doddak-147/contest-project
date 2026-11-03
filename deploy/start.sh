#!/bin/sh
set -eu
python -m backend.manage init-db
mkdir -p "${CONTEST_DATA_DIR:-/app/runtime/catalogue}"
if [ ! -f "${CONTEST_DATA_DIR:-/app/runtime/catalogue}/contests.json" ]; then
  cp -R /app/data/. "${CONTEST_DATA_DIR:-/app/runtime/catalogue}/"
fi
python -m backend.manage import-data
exec python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
