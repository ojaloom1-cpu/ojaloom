#!/usr/bin/env bash
# Store secrets in Secret Manager (never in git, never in instance metadata). Values are typed, not echoed, and not saved in shell history.
# Re-run to rotate: it adds a new version. Then:  ./03-deploy.sh  (the VM re-reads secrets on restart).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/config.sh"
SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud config set project "$PROJECT_ID" >/dev/null

store() {  # name, prompt
  local name="$1" prompt="$2" value
  read -r -s -p "$prompt (blank to skip): " value; echo
  [ -n "$value" ] || { echo "  skipped $name"; return 0; }
  if gcloud secrets describe "$name" >/dev/null 2>&1; then
    printf %s "$value" | gcloud secrets versions add "$name" --data-file=- >/dev/null
  else
    printf %s "$value" | gcloud secrets create "$name" --data-file=- --replication-policy=automatic >/dev/null
  fi
  gcloud secrets add-iam-policy-binding "$name" --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor >/dev/null
  echo "  stored $name"
}
store ojaloom-paystack-secret "Paystack SECRET key (sk_test_... or sk_live_...)"
store ojaloom-wa-token        "WhatsApp Cloud API access token (only if you set up direct sending; see docs/WHATSAPP.md)"
echo "For direct WhatsApp sending also set WA_PHONE_ID in config.sh and re-run ./01-setup.sh (see docs/WHATSAPP.md)."
