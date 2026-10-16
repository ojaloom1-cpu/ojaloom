#!/usr/bin/env bash
# One-time infrastructure for the API on Google Cloud. Safe to re-run: every step checks before it creates.
# Needs the gcloud CLI, logged in as someone who can administer the project (Owner is simplest for the first run).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
[ -f "$HERE/config.sh" ] || { echo "Copy config.example.sh to config.sh and edit it first."; exit 1; }
# shellcheck source=/dev/null
source "$HERE/config.sh"
SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
exists() { "$@" >/dev/null 2>&1; }

gcloud config set project "$PROJECT_ID" >/dev/null
echo "== 1/8 enabling the Google Cloud services we use"
gcloud services enable compute.googleapis.com secretmanager.googleapis.com storage.googleapis.com \
  logging.googleapis.com monitoring.googleapis.com iap.googleapis.com

echo "== 2/8 service account for the VM (no keys are ever created for it)"
exists gcloud iam service-accounts describe "$SA" || gcloud iam service-accounts create "$SA_NAME" --display-name="Oja Loom API VM"
# Only what the VM needs: write logs and metrics. Storage and secrets are granted on the single bucket / secrets below.
for role in roles/logging.logWriter roles/monitoring.metricWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA" --role="$role" --condition=None >/dev/null
done

echo "== 3/8 private bucket for continuous database backups"
exists gcloud storage buckets describe "gs://$BUCKET" || \
  gcloud storage buckets create "gs://$BUCKET" --location="$REGION" --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update "gs://$BUCKET" --soft-delete-duration=14d   # an accidental delete can be undone for 14 days
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$SA" --role=roles/storage.objectUser >/dev/null

echo "== 4/8 fixed public IP address"
exists gcloud compute addresses describe ojaloom-api-ip --region="$REGION" || gcloud compute addresses create ojaloom-api-ip --region="$REGION"
IP="$(gcloud compute addresses describe ojaloom-api-ip --region="$REGION" --format='value(address)')"

echo "== 5/8 firewall: web traffic from anywhere, SSH only through Google's IAP tunnel (no public SSH)"
exists gcloud compute firewall-rules describe ojaloom-allow-web || \
  gcloud compute firewall-rules create ojaloom-allow-web --allow=tcp:80,tcp:443 --target-tags=ojaloom --direction=INGRESS
exists gcloud compute firewall-rules describe ojaloom-allow-iap-ssh || \
  gcloud compute firewall-rules create ojaloom-allow-iap-ssh --allow=tcp:22 --source-ranges=35.235.240.0/20 --target-tags=ojaloom --direction=INGRESS

echo "== 6/8 data disk (holds the database) + daily snapshots kept for 14 days"
exists gcloud compute disks describe ojaloom-data --zone="$ZONE" || \
  gcloud compute disks create ojaloom-data --zone="$ZONE" --size=20GB --type=pd-balanced
exists gcloud compute resource-policies describe ojaloom-daily --region="$REGION" || \
  gcloud compute resource-policies create snapshot-schedule ojaloom-daily --region="$REGION" \
    --max-retention-days=14 --on-source-disk-delete=keep-auto-snapshots --daily-schedule --start-time=01:00
gcloud compute disks add-resource-policies ojaloom-data --zone="$ZONE" --resource-policies=ojaloom-daily 2>/dev/null || true

echo "== 7/8 non-secret settings for the VM"
ENVFILE="$(mktemp)"; trap 'rm -f "$ENVFILE"' EXIT
cat > "$ENVFILE" <<ENV
OJALOOM_ENV=production
OJALOOM_FRONTEND_URL=https://${FRONTEND_DOMAIN}
OJALOOM_PUBLIC_API_URL=https://${API_DOMAIN}
OJALOOM_ALLOWED_ORIGINS=https://${FRONTEND_DOMAIN}
OJALOOM_ENFORCE_PAYWALL=1
OJALOOM_OPERATOR_NAME=${OPERATOR_NAME}
OJALOOM_SUPPORT_EMAIL=${SUPPORT_EMAIL}
OJALOOM_SUPPORT_WHATSAPP=${SUPPORT_WHATSAPP}
LITESTREAM_REPLICA_URL=gcs://${BUCKET}/ojaloom
ENV
[ -z "${WA_PHONE_ID:-}" ] || echo "OJALOOM_WA_PHONE_ID=${WA_PHONE_ID}" >> "$ENVFILE"

echo "== 8/8 the VM (Shielded VM, OS Login, deletion protection, no public SSH)"
if exists gcloud compute instances describe "$VM_NAME" --zone="$ZONE"; then
  echo "VM already exists: updating its settings only"
  gcloud compute instances add-metadata "$VM_NAME" --zone="$ZONE" \
    --metadata=ojaloom-api-domain="$API_DOMAIN" --metadata-from-file="ojaloom-env=${ENVFILE},startup-script=${HERE}/startup.sh"
else
  gcloud compute instances create "$VM_NAME" --zone="$ZONE" --machine-type="$MACHINE_TYPE" \
    --image-family=debian-12 --image-project=debian-cloud --boot-disk-size=20GB --boot-disk-type=pd-balanced \
    --disk="name=ojaloom-data,device-name=ojaloom-data,mode=rw,boot=no,auto-delete=no" \
    --address=ojaloom-api-ip --tags=ojaloom --service-account="$SA" --scopes=cloud-platform \
    --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring --deletion-protection \
    --metadata=enable-oslogin=TRUE,ojaloom-api-domain="$API_DOMAIN",ojaloom-allow-format=true \
    --metadata-from-file="ojaloom-env=${ENVFILE},startup-script=${HERE}/startup.sh"
fi

cat <<DONE

Done. Next:
  1. DNS:   A     ${API_DOMAIN}        ->  ${IP}
            CNAME ${FRONTEND_DOMAIN}   ->  <your-github-username>.github.io
  2. Secrets:  ./02-secrets.sh
  3. Code:     ./03-deploy.sh
DONE
