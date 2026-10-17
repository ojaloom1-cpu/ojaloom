#!/usr/bin/env bash
# Update the API after you pulled new code:   cd <repo> && git pull && sudo bash deploy/digitalocean/update.sh
# Copies the application files into place and restarts the service. It does not touch settings, the database, or Caddy.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || exec sudo bash "$0" "$@"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$ROOT/backend/ojaloom_server.py" || { echo "ojaloom_server.py does not parse: not installing it" >&2; exit 1; }
install -m 0444 -o root -g root "$ROOT/backend/ojaloom_server.py" /opt/ojaloom/ojaloom_server.py
install -m 0555 -o root -g root "$ROOT/backend/entrypoint.sh"     /opt/ojaloom/entrypoint.sh
install -m 0444 -o root -g root "$HERE/litestream.yml"            /opt/ojaloom/litestream.yml
install -m 0555 -o root -g root "$HERE/restore-drill.sh"          /opt/ojaloom/restore-drill.sh
install -m 0755 -o root -g root "$HERE/ojaloom-admin.sh"          /usr/local/bin/ojaloom-admin
install -m 0644 -o root -g root "$HERE/ojaloom.service"           /etc/systemd/system/ojaloom.service
systemctl daemon-reload
systemctl restart ojaloom
for _ in $(seq 1 30); do
  curl -fsS -m 4 http://127.0.0.1:8000/health >/dev/null 2>&1 && { echo "Updated. The API is running."; exit 0; }
  sleep 2
done
echo "The API did not come back. See:  journalctl -u ojaloom -n 50 --no-pager" >&2
exit 1
