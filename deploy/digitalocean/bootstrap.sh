#!/usr/bin/env bash
# Oja Loom: set up a fresh Debian droplet (DigitalOcean, works on the $4 / 512 MB size). Safe to re-run: each step checks first.
#
#   sudo bash deploy/digitalocean/bootstrap.sh            install or repair everything
#   sudo bash deploy/digitalocean/bootstrap.sh --check    only check the settings file; changes nothing
#
# No Docker on purpose: on 512 MB the Docker daemon and image builds would eat the memory the app needs.
# What it sets up: 1 GB swap, firewall (ssh/80/443 only), automatic security updates, an unprivileged service user,
# Litestream (version + SHA-256 pinned), Caddy (automatic HTTPS), and the API as a sandboxed systemd service.
# Full guide: docs/DIGITALOCEAN.md
set -euo pipefail

# Same pins as backend/Dockerfile. If you update one, update the other.
LS_VERSION="0.5.17"
LS_SHA256_AMD64="cfb371176d164437ae869f8351cfde49bd1804ae71c61923f75c9cba9c9c006d"
LS_SHA256_ARM64="f8ca4a050095c1efbda2c4365172e61bf9d955ea0d9ac42f448b52e51819baa5"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
ENVF=/etc/ojaloom/ojaloom.env
CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

say()  { printf '\n== %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root:  sudo bash $0"
[ -f "$ROOT/backend/ojaloom_server.py" ] || die "run this from inside the cloned repository (cannot find backend/ojaloom_server.py)"
# shellcheck source=/dev/null
. /etc/os-release
case "${ID:-}" in
  debian) ;;
  ubuntu) warn "written for Debian 12/13; Ubuntu usually works too, but you are on your own if it does not" ;;
  *) die "this script is for Debian (found: ${PRETTY_NAME:-unknown})" ;;
esac

# ---------------------------------------------------------------------------------------------------------------
say "1/9 settings file ($ENVF)"
install -d -m 0750 /etc/ojaloom
if [ ! -f "$ENVF" ]; then
  [ "$CHECK_ONLY" -eq 0 ] || die "$ENVF does not exist yet"
  install -m 0600 "$HERE/ojaloom.env.example" "$ENVF"
  echo "Created $ENVF from the example."
  echo "Edit it now:   nano $ENVF"
  echo "Then run this script again."
  exit 0
fi
chmod 0600 "$ENVF"
sed -i 's/\r$//' "$ENVF"   # a file edited on Windows has CR characters that would end up inside the values

getenv() { grep -E "^$1=" "$ENVF" | tail -n 1 | cut -d= -f2- || true; }

problems=()
for k in OJALOOM_FRONTEND_URL OJALOOM_PUBLIC_API_URL OJALOOM_ALLOWED_ORIGINS LITESTREAM_REPLICA_URL \
         LITESTREAM_ENDPOINT LITESTREAM_REGION LITESTREAM_ACCESS_KEY_ID LITESTREAM_SECRET_ACCESS_KEY; do
  v="$(getenv "$k")"
  [ -n "$v" ] || problems+=("$k is missing or empty")
done
for k in OJALOOM_FRONTEND_URL OJALOOM_PUBLIC_API_URL OJALOOM_ALLOWED_ORIGINS OJALOOM_OPERATOR_NAME OJALOOM_SUPPORT_EMAIL \
         LITESTREAM_REPLICA_URL LITESTREAM_ENDPOINT LITESTREAM_REGION LITESTREAM_ACCESS_KEY_ID LITESTREAM_SECRET_ACCESS_KEY; do
  case "$(getenv "$k")" in
    *REPLACE_ME*|*BUCKET_NAME*|*example.com*|"Your Company Ltd") problems+=("$k still has the example value") ;;
  esac
done
[ "$(getenv OJALOOM_ENV)" = "production" ] || problems+=("OJALOOM_ENV must be production")
if grep -nE "^[A-Za-z_][A-Za-z0-9_]*=[\"']" "$ENVF" >/dev/null; then
  problems+=("a value starts with a quote character: remove the quotes (this file takes plain KEY=value)")
fi
if grep -nE "^[A-Za-z_][A-Za-z0-9_]*=.*[[:space:]]#" "$ENVF" >/dev/null; then
  problems+=("a line has a comment after its value: move the comment to its own line")
fi
API_URL="$(getenv OJALOOM_PUBLIC_API_URL)"
API_DOMAIN="${API_URL#https://}"; API_DOMAIN="${API_DOMAIN%%/*}"
[[ "$API_URL" == https://* ]] || problems+=("OJALOOM_PUBLIC_API_URL must start with https://")
[[ "$API_DOMAIN" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]] || problems+=("OJALOOM_PUBLIC_API_URL must be a plain lower-case address like https://api.yourshop.com")
if [ "${#problems[@]}" -gt 0 ]; then
  printf 'Fix these in %s, then run this script again:\n' "$ENVF" >&2
  printf '  - %s\n' "${problems[@]}" >&2
  exit 1
fi
echo "Settings look complete. API address: https://$API_DOMAIN"

# Warn (do not stop) when DNS does not point here yet: Caddy cannot get a certificate until it does.
MY_IP="$(curl -fsS -m 3 http://169.254.169.254/metadata/v1/interfaces/public/0/ipv4/address 2>/dev/null || true)"
DNS_IP="$(getent ahostsv4 "$API_DOMAIN" 2>/dev/null | awk 'NR==1{print $1}' || true)"
if [ -z "$DNS_IP" ]; then
  warn "$API_DOMAIN does not resolve yet. Add the DNS A record (api -> ${MY_IP:-the IP of this droplet}); HTTPS will not work until it does."
elif [ -n "$MY_IP" ] && [ "$DNS_IP" != "$MY_IP" ]; then
  warn "$API_DOMAIN points to $DNS_IP but this droplet is $MY_IP. HTTPS will not work until the A record matches."
else
  echo "DNS: $API_DOMAIN -> ${DNS_IP}  (good)"
fi
[ "$CHECK_ONLY" -eq 0 ] || { echo "Check only: nothing was changed."; exit 0; }

# ---------------------------------------------------------------------------------------------------------------
say "2/9 operating-system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends ca-certificates curl gnupg debian-keyring debian-archive-keyring \
  apt-transport-https python3 sqlite3 ufw unattended-upgrades util-linux

# ---------------------------------------------------------------------------------------------------------------
say "3/9 swap (a 512 MB machine needs a safety net)"
if [ -z "$(swapon --show --noheadings)" ]; then
  if [ ! -f /swapfile ]; then
    fallocate -l 1G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=1024 status=none
    chmod 0600 /swapfile
    mkswap /swapfile >/dev/null
  fi
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "1 GB swap enabled"
else
  echo "swap already present"
fi
echo 'vm.swappiness=10' > /etc/sysctl.d/99-ojaloom.conf
sysctl -q -p /etc/sysctl.d/99-ojaloom.conf || true

# ---------------------------------------------------------------------------------------------------------------
say "4/9 service user and folders"
id ojaloom >/dev/null 2>&1 || useradd --system --user-group --home-dir /nonexistent --shell /usr/sbin/nologin ojaloom
install -d -m 0700 -o ojaloom -g ojaloom /var/lib/ojaloom   # the database lives here
install -d -m 0755 /opt/ojaloom                              # the code lives here (owned by root: the service cannot change it)

# ---------------------------------------------------------------------------------------------------------------
say "5/9 Litestream $LS_VERSION (checked against a pinned SHA-256)"
if [ "$(litestream version 2>/dev/null || true)" != "$LS_VERSION" ]; then
  case "$(dpkg --print-architecture)" in
    amd64) arch=x86_64; sha="$LS_SHA256_AMD64" ;;
    arm64) arch=arm64;  sha="$LS_SHA256_ARM64" ;;
    *) die "unsupported CPU architecture: $(dpkg --print-architecture)" ;;
  esac
  tmp="$(mktemp -d)"
  curl -fsSL -o "$tmp/litestream.tgz" "https://github.com/benbjohnson/litestream/releases/download/v${LS_VERSION}/litestream-${LS_VERSION}-linux-${arch}.tar.gz"
  echo "${sha}  $tmp/litestream.tgz" | sha256sum -c - || die "Litestream download does not match its pinned SHA-256: refusing to install it"
  tar -xzf "$tmp/litestream.tgz" -C "$tmp" litestream
  install -m 0755 "$tmp/litestream" /usr/local/bin/litestream
  rm -rf "$tmp"
fi
litestream version

# ---------------------------------------------------------------------------------------------------------------
say "6/9 Caddy (automatic HTTPS), from the official Caddy package repository"
if ! command -v caddy >/dev/null 2>&1; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' -o /etc/apt/sources.list.d/caddy-stable.list
  chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y
  apt-get install -y caddy
fi

# ---------------------------------------------------------------------------------------------------------------
say "7/9 install the application"
install -m 0444 -o root -g root "$ROOT/backend/ojaloom_server.py" /opt/ojaloom/ojaloom_server.py
install -m 0555 -o root -g root "$ROOT/backend/entrypoint.sh"     /opt/ojaloom/entrypoint.sh
install -m 0444 -o root -g root "$HERE/litestream.yml"            /opt/ojaloom/litestream.yml
install -m 0555 -o root -g root "$HERE/restore-drill.sh"          /opt/ojaloom/restore-drill.sh
install -m 0755 -o root -g root "$HERE/ojaloom-admin.sh"          /usr/local/bin/ojaloom-admin
install -m 0644 -o root -g root "$HERE/ojaloom.service"           /etc/systemd/system/ojaloom.service
sed "s/__API_DOMAIN__/${API_DOMAIN}/g" "$HERE/Caddyfile" > /etc/caddy/Caddyfile
chmod 0644 /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1 || die "the generated Caddyfile is not valid:  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile"

# ---------------------------------------------------------------------------------------------------------------
say "8/9 firewall and automatic security updates"
SSH_PORT="$(sshd -T 2>/dev/null | awk '/^port /{print $2; exit}' || true)"; SSH_PORT="${SSH_PORT:-22}"
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw limit "${SSH_PORT}/tcp" >/dev/null   # ssh, with rate limiting against password guessing
ufw allow 80/tcp  >/dev/null             # Let's Encrypt + redirect to https
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' > /etc/apt/apt.conf.d/20auto-upgrades
echo "firewall: only ssh (port $SSH_PORT), 80 and 443 are open"
if sshd -T 2>/dev/null | grep -qi '^passwordauthentication yes'; then
  warn "ssh still accepts PASSWORD logins, so anyone on the internet can keep guessing your root password. Add an SSH key, then run: bash deploy/digitalocean/ssh-keys-only.sh   (steps: docs/DIGITALOCEAN.md, section 1b)"
fi

# ---------------------------------------------------------------------------------------------------------------
say "9/9 start"
systemctl daemon-reload
systemctl enable ojaloom caddy >/dev/null 2>&1
systemctl restart ojaloom
systemctl restart caddy

wait_for() { local i; for ((i = 0; i < $2; i++)); do curl -fsS -m 4 "$1" >/dev/null 2>&1 && return 0; sleep 2; done; return 1; }
if wait_for "http://127.0.0.1:8000/health" 45; then
  echo "API is running locally."
else
  echo "The API did not start within 90 seconds. Last log lines:" >&2
  journalctl -u ojaloom -n 40 --no-pager >&2 || true
  die "fix the problem above (usually a wrong value in $ENVF or a wrong backup bucket key), then run this script again"
fi
if wait_for "https://${API_DOMAIN}/health" 45; then
  echo "SUCCESS: https://${API_DOMAIN}/health answers."
else
  warn "https://${API_DOMAIN}/health does not answer yet. Usually the DNS A record has not spread, or ports 80/443 are blocked by a DigitalOcean Cloud Firewall. Look at:  journalctl -u caddy -n 40"
fi
echo
echo "Next: run the restore drill once (proves the backup works):   sudo /opt/ojaloom/restore-drill.sh"
