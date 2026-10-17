#!/usr/bin/env bash
# Restore drill: prove the backup works. Restores a backup into a scratch folder, checks its integrity and counts rows.
# It does NOT touch the live database. Run it once after setup, then monthly.
#   sudo /opt/ojaloom/restore-drill.sh                                  newest backup
#   sudo /opt/ojaloom/restore-drill.sh -timestamp 2026-10-15T09:00:00Z  the database as it was at that moment (UTC)
#   sudo RESTORE_TO=/root/old /opt/ojaloom/restore-drill.sh ...         also KEEP the restored file as /root/old/restored.db
set -euo pipefail
[ "$(id -u)" -eq 0 ] || exec sudo bash "$0" "$@"
ENVF="${OJALOOM_ENV_FILE:-/etc/ojaloom/ojaloom.env}"
DATA="${OJALOOM_DATA_DIR:-/var/lib/ojaloom}"
CONF="${LITESTREAM_CONFIG:-/opt/ojaloom/litestream.yml}"

envargs=()
while IFS= read -r line || [ -n "$line" ]; do
  [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] && envargs+=("$line")
done < <(tr -d '\r' < "$ENVF")

SCRATCH="$(mktemp -d /tmp/restore-drill.XXXXXX)"
trap 'rm -rf "$SCRATCH"' EXIT
# Anything you pass (for example -timestamp ...) goes straight to "litestream restore".
env "${envargs[@]}" OJALOOM_DATA_DIR="$DATA" litestream restore -config "$CONF" "$@" -o "$SCRATCH/restored.db" "$DATA/ojaloom.db"
python3 - "$SCRATCH/restored.db" <<'PY'
import sqlite3, sys
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
print("integrity_check :", c.execute("PRAGMA integrity_check").fetchone()[0])
for t in ("users", "businesses", "customers", "orders", "billing_payments"):
    print(f"{t:17}:", c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
print("latest order    :", c.execute("SELECT MAX(created_at) FROM orders").fetchone()[0])
PY
if [ -n "${RESTORE_TO:-}" ]; then
  install -d -m 0700 "$RESTORE_TO"
  install -m 0600 "$SCRATCH/restored.db" "$RESTORE_TO/restored.db"
  echo "Kept a copy at $RESTORE_TO/restored.db (it holds customer data: delete it when you are done)."
fi
echo "Restore drill finished. If integrity_check says ok and the counts look right, your backup works."
