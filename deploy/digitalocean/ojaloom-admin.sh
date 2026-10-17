#!/usr/bin/env bash
# Run an Oja Loom maintenance command against the live database, as the service user. Installed as /usr/local/bin/ojaloom-admin.
#   sudo ojaloom-admin --grant-pro owner@shop.com --days 30
#   sudo ojaloom-admin --make-codes 5
#   sudo ojaloom-admin --reset-password owner@shop.com
set -euo pipefail
[ "$(id -u)" -eq 0 ] || exec sudo "$0" "$@"
ENVF="${OJALOOM_ENV_FILE:-/etc/ojaloom/ojaloom.env}"
DATA="${OJALOOM_DATA_DIR:-/var/lib/ojaloom}"
APP="${OJALOOM_APP:-/opt/ojaloom/ojaloom_server.py}"

# Read the settings the same way systemd does: plain KEY=value lines (an array keeps values that contain spaces intact).
envargs=()
while IFS= read -r line || [ -n "$line" ]; do
  [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] && envargs+=("$line")
done < <(tr -d '\r' < "$ENVF")

exec setpriv --reuid=ojaloom --regid=ojaloom --clear-groups \
  env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/nonexistent TERM="${TERM:-xterm}" "${envargs[@]}" \
  OJALOOM_DATA_DIR="$DATA" python3 "$APP" --no-browser "$@"
