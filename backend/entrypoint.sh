#!/bin/sh
# Container entrypoint.
#   1. If this machine has no database (new server, lost disk), bring it back from the backup in Cloud Storage.
#   2. Run the server under Litestream, which streams every change to that backup within about a second.
# It fails CLOSED: if the backup cannot be read, the container stops. It never starts an empty database
# on top of a backup it could not look at.
set -eu
umask 077

DATA_DIR="${OJALOOM_DATA_DIR:-/data}"
export OJALOOM_DATA_DIR="$DATA_DIR"
CONFIG="${LITESTREAM_CONFIG:-/etc/litestream.yml}"
APP="${OJALOOM_APP:-/app/ojaloom_server.py}"
DB="$DATA_DIR/ojaloom.db"

set -- python3 "$APP" --host 0.0.0.0 --port "${PORT:-8000}" --no-browser --trust-proxy --secure-cookies --data-dir "$DATA_DIR"

if [ -z "${LITESTREAM_REPLICA_URL:-}" ]; then
  if [ "${OJALOOM_ENV:-}" = "production" ] && [ "${OJALOOM_ALLOW_NO_BACKUP:-}" != "1" ]; then
    echo "refusing to start: production needs LITESTREAM_REPLICA_URL (continuous database backup)." >&2
    echo "(set OJALOOM_ALLOW_NO_BACKUP=1 only if you really want to run without one)" >&2
    exit 2
  fi
  echo "WARNING: running WITHOUT continuous database backup." >&2
  exec "$@"
fi

# Restores only when there is no database here AND a backup exists. Otherwise it does nothing.
litestream restore -config "$CONFIG" -if-db-not-exists -if-replica-exists "$DB"

exec litestream replicate -config "$CONFIG" -exec "$*"
