#!/usr/bin/env bash
# Runs as root every time the VM boots (it is the instance's startup-script). It is idempotent.
#   * installs Docker (official repository) the first time
#   * mounts the persistent data disk. It formats the disk ONLY when the disk is completely blank AND the one-time
#     "ojaloom-allow-format" metadata flag is set. A disk with anything on it is never touched.
#   * writes /etc/ojaloom/env (root-only) from instance metadata + Secret Manager, so no secret lives in git or in metadata
set -euo pipefail
MD="http://metadata.google.internal/computeMetadata/v1/instance/attributes"
md() { curl -fsS -H "Metadata-Flavor: Google" "$MD/$1" 2>/dev/null || true; }
MNT=/mnt/disks/ojaloom-data
DEV=/dev/disk/by-id/google-ojaloom-data

# ---- 1. Docker --------------------------------------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y && apt-get install -y ca-certificates curl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
fi

# ---- 2. the data disk -----------------------------------------------------------------------------------------
[ -b "$DEV" ] || { echo "data disk $DEV is not attached: refusing to continue" >&2; exit 1; }
mkdir -p "$MNT"
if ! mountpoint -q "$MNT"; then
  fstype="$(blkid -p -s TYPE -o value "$DEV" 2>/dev/null || true)"
  signatures="$(wipefs -n "$DEV" 2>/dev/null | tail -n +2 || true)"
  if [ -z "$fstype" ] && [ -z "$signatures" ]; then
    if [ "$(md ojaloom-allow-format)" = "true" ]; then
      echo "blank data disk and formatting is allowed: creating the filesystem"
      mkfs.ext4 -m 0 -F -E lazy_itable_init=0,lazy_journal_init=0,discard "$DEV"
    else
      echo "the data disk is blank but formatting is NOT allowed (ojaloom-allow-format is not set): refusing, so a failed mount can never wipe data" >&2
      exit 1
    fi
  fi
  mount -o discard,defaults "$DEV" "$MNT"
  uuid="$(blkid -s UUID -o value "$DEV")"
  grep -q "$MNT" /etc/fstab || echo "UUID=$uuid $MNT ext4 discard,defaults,nofail 0 2" >> /etc/fstab
fi
chown 10001:10001 "$MNT"   # the container's unprivileged user
chmod 0700 "$MNT"

# ---- 3. settings and secrets ----------------------------------------------------------------------------
install -d -m 0750 /etc/ojaloom
umask 077
envtmp="$(mktemp /etc/ojaloom/env.XXXXXX)"
md ojaloom-env > "$envtmp"; printf '\n' >> "$envtmp"
secret() { gcloud secrets versions access latest --secret="$1" 2>/dev/null || true; }
v="$(secret ojaloom-paystack-secret)"; [ -z "$v" ] || printf 'OJALOOM_PAYSTACK_SECRET=%s\n' "$v" >> "$envtmp"
v="$(secret ojaloom-wa-token)";        [ -z "$v" ] || printf 'OJALOOM_WA_TOKEN=%s\n' "$v" >> "$envtmp"
chmod 0600 "$envtmp"; mv "$envtmp" /etc/ojaloom/env
printf 'API_DOMAIN=%s\n' "$(md ojaloom-api-domain)" > /etc/ojaloom/caddy.env; chmod 0600 /etc/ojaloom/caddy.env

# ---- 4. start the app if it has been deployed ---------------------------------------------------------------------
if [ -f /opt/ojaloom/docker-compose.yml ]; then
  cd /opt/ojaloom && docker compose up -d
fi
