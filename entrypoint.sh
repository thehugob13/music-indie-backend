#!/bin/sh
set -eu
umask 077
install -d -m 700 -o app -g app "${MEDIA_DATA_DIR:-/data/media}"
exec gosu app uvicorn app:create_app --factory --host 0.0.0.0 --port "${PORT:-8080}" --workers 1
