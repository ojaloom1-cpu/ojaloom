#!/usr/bin/env bash
# Copy the API code to the VM and (re)start it. Run it again for every update. Uses Google's IAP tunnel: the VM has no public SSH.
# Your Google account needs roles/compute.osAdminLogin on the project and roles/iap.tunnelResourceAccessor.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
# shellcheck source=/dev/null
source "$HERE/config.sh"
gcloud config set project "$PROJECT_ID" >/dev/null

STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/backend"
cp "$ROOT"/backend/{Dockerfile,ojaloom_server.py,entrypoint.sh,litestream.yml} "$STAGE/backend/"
cp "$ROOT"/deploy/vm/{docker-compose.yml,Caddyfile,restore-drill.sh} "$STAGE/"
tar -czf "$STAGE/ojaloom.tgz" -C "$STAGE" backend docker-compose.yml Caddyfile restore-drill.sh

# make sure the VM has the latest startup script and settings before it (re)starts the app
gcloud compute instances add-metadata "$VM_NAME" --zone="$ZONE" --metadata-from-file=startup-script="$HERE/startup.sh" >/dev/null

gcloud compute scp --zone="$ZONE" --tunnel-through-iap "$STAGE/ojaloom.tgz" "$VM_NAME:/tmp/ojaloom.tgz"
gcloud compute ssh "$VM_NAME" --zone="$ZONE" --tunnel-through-iap --command='
  set -euo pipefail
  sudo install -d -m 0755 /opt/ojaloom
  sudo tar -xzf /tmp/ojaloom.tgz -C /opt/ojaloom && rm -f /tmp/ojaloom.tgz
  sudo google_metadata_script_runner startup      # re-read settings and secrets, make sure the data disk is mounted
  cd /opt/ojaloom && sudo docker compose up -d --build --remove-orphans
  sudo docker image prune -f >/dev/null
'

echo "Waiting for https://${API_DOMAIN}/health (needs the DNS record; the certificate can take a minute the first time)..."
for _ in $(seq 1 40); do
  if curl -fsS --max-time 5 "https://${API_DOMAIN}/health" >/dev/null 2>&1; then
    echo "API is up: https://${API_DOMAIN}/health"
    # the data disk has been formatted/mounted once: close the 'allowed to format' door for good
    gcloud compute instances remove-metadata "$VM_NAME" --zone="$ZONE" --keys=ojaloom-allow-format >/dev/null 2>&1 || true
    exit 0
  fi
  sleep 5
done
echo "Not answering yet. Check DNS for ${API_DOMAIN}, then:  gcloud compute ssh ${VM_NAME} --zone=${ZONE} --tunnel-through-iap --command='sudo docker compose -f /opt/ojaloom/docker-compose.yml logs --tail=80'"
exit 1
