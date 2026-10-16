#!/usr/bin/env bash
# Restore drill: prove the backup works. Restores the newest backup into a scratch folder, checks its integrity and
# counts rows. It does not touch the live database. Run it monthly, and after changing anything about backups.
#   on the VM:  sudo /opt/ojaloom/restore-drill.sh
set -euo pipefail
cd /opt/ojaloom
SCRATCH="$(mktemp -d /tmp/restore-drill.XXXXXX)"
chmod 0777 "$SCRATCH"   # the container user (uid 10001) must be able to write here; the folder is deleted at the end
trap 'rm -rf "$SCRATCH"' EXIT
docker compose run --rm --no-deps --entrypoint sh -v "$SCRATCH:/scratch" app -c '
  set -eu
  litestream restore -config /etc/litestream.yml -o /scratch/restored.db /data/ojaloom.db
  python3 - <<PY
import sqlite3
c = sqlite3.connect("file:/scratch/restored.db?mode=ro", uri=True)
print("integrity_check :", c.execute("PRAGMA integrity_check").fetchone()[0])
for t in ("users", "businesses", "customers", "orders", "billing_payments"):
    print(f"{t:17}:", c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
print("latest order    :", c.execute("SELECT MAX(created_at) FROM orders").fetchone()[0])
PY'
echo "Restore drill finished. If integrity_check says ok and the counts look right, your backup works."
