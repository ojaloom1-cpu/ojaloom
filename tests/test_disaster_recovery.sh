#!/usr/bin/env bash
# Disaster-recovery drill with the REAL Litestream and the REAL entrypoint, using a local folder as the "bucket".
#   start -> write data -> wait for replication -> DESTROY the data directory -> restart -> data must be back.
# Usage: tests/test_disaster_recovery.sh            (needs `litestream` on PATH, or LITESTREAM_BIN=/path/to/litestream)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LS="${LITESTREAM_BIN:-$(command -v litestream || true)}"
[ -x "$LS" ] || { echo "litestream not found (set LITESTREAM_BIN)"; exit 2; }
W="$(mktemp -d)"; PORT=$((20000 + RANDOM % 20000)); PID=""
cleanup() { [ -n "$PID" ] && kill "$PID" 2>/dev/null || true; sleep 0.5; rm -rf "$W"; }
trap cleanup EXIT
mkdir -p "$W/bin" "$W/replica"; ln -s "$LS" "$W/bin/litestream"

run_server() {
  PATH="$W/bin:$PATH" OJALOOM_ENV=development OJALOOM_DATA_DIR="$W/data" LITESTREAM_CONFIG="$ROOT/backend/litestream.yml" \
  LITESTREAM_REPLICA_URL="file://$W/replica" OJALOOM_APP="$ROOT/backend/ojaloom_server.py" PORT=$PORT \
  setsid sh "$ROOT/backend/entrypoint.sh" >"$W/server.log" 2>&1 &
  PID=$!
  for _ in $(seq 1 100); do curl -fs "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && return 0; sleep 0.2; done
  echo "server did not come up"; cat "$W/server.log"; exit 1
}
stop_server() { kill -TERM -- "-$PID" 2>/dev/null || kill -TERM "$PID" 2>/dev/null || true; wait "$PID" 2>/dev/null || true; PID=""; }
api() { python3 - "$@" <<'PY'
import sys, json, http.client
port, step = int(sys.argv[1]), sys.argv[2]
def call(method, path, body=None, cookie="", csrf=""):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    h = {"Origin": "http://127.0.0.1:5173", "Content-Type": "application/json"}
    if cookie: h["Cookie"] = cookie
    if csrf: h["X-CSRF-Token"] = csrf
    c.request(method, path, json.dumps(body) if body is not None else None, h)
    r = c.getresponse(); data = r.read()
    ck = (r.getheader("Set-Cookie") or "").split(";")[0]
    return r.status, (json.loads(data) if data[:1] == b"{" else {}), ck
cred = {"email": "drill@example.test", "password": "correct horse battery 42"}
if step == "write":
    s, d, ck = call("POST", "/api/signup", {**cred, "owner_name": "Drill", "business_name": "Drill Shop", "category": "Fashion & Clothing", "phone": "08030000000", "accept_terms": "1"})
    assert s in (200, 201), (s, d)
    s, me, _ = call("GET", "/api/me", cookie=ck); csrf = me["csrf"]
    s, d, _ = call("POST", "/api/customers", {"full_name": "Survives The Crash", "phone": "08031112222"}, ck, csrf)
    assert s == 201, (s, d); print("wrote customer", d["id"])
else:
    s, d, ck = call("POST", "/api/login", cred); assert s == 200, ("login failed after restore", s, d)
    s, me, _ = call("GET", "/api/me", cookie=ck)
    s, lst, _ = call("GET", "/api/customers", cookie=ck)
    names = [c["full_name"] for c in lst["items"]]
    assert "Survives The Crash" in names, names; print("customer is back:", names)
PY
}

echo "1) first start: no database, no backup yet"
run_server; grep -q "WITHOUT" "$W/server.log" && { echo "unexpected: no-backup mode"; exit 1; } || true
api "$PORT" write
echo "2) wait for Litestream to ship the changes"; sleep 4
[ -n "$(find "$W/replica" -name '*.ltx' | head -1)" ] || { echo "nothing replicated"; cat "$W/server.log"; exit 1; }
stop_server
echo "3) DISASTER: the data directory is destroyed"; rm -rf "$W/data"; [ ! -e "$W/data/ojaloom.db" ]
echo "4) new machine boots: entrypoint restores from the backup"
run_server
api "$PORT" read          # the real test: the data written before the disaster is back
stop_server
echo "5) fail-closed: an unreadable backup must STOP the container, not create an empty database"
rm -rf "$W/data"; mv "$W/replica" "$W/replica.moved"; printf 'garbage' > "$W/replica"   # a file where the backup folder should be
if PATH="$W/bin:$PATH" OJALOOM_ENV=development OJALOOM_DATA_DIR="$W/data" LITESTREAM_CONFIG="$ROOT/backend/litestream.yml" LITESTREAM_REPLICA_URL="file://$W/replica" \
   OJALOOM_APP="$ROOT/backend/ojaloom_server.py" PORT=$PORT timeout 8 sh "$ROOT/backend/entrypoint.sh" >"$W/fail.log" 2>&1; then
  echo "FAIL: started although the backup was unreadable"; cat "$W/fail.log"; exit 1
fi
[ ! -e "$W/data/ojaloom.db" ] || { echo "FAIL: an empty database was created"; exit 1; }
echo "6) production without a backup configured refuses to start"
if OJALOOM_ENV=production sh "$ROOT/backend/entrypoint.sh" >"$W/prod.log" 2>&1; then echo "FAIL"; exit 1; fi
grep -q "needs LITESTREAM_REPLICA_URL" "$W/prod.log"
echo "DISASTER RECOVERY DRILL PASSED"
