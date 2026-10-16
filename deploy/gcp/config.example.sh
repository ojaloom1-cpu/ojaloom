# shellcheck shell=bash disable=SC2034
# Copy to config.sh and edit. config.sh is git-ignored. Nothing in this file is secret.
PROJECT_ID="my-ojaloom-project"          # a Google Cloud project with billing enabled
REGION="europe-west1"                    # pick near your customers; the bucket, IP and disk snapshots live here
ZONE="europe-west1-b"
MACHINE_TYPE="e2-small"                  # 2 shared vCPU / 2 GB. Plenty for a small business app. Resize later if needed.

# The web app and the API MUST share one registrable domain (login cookies are SameSite=Strict).
API_DOMAIN="api.example.com"             # DNS: A record -> the VM's address (01-setup.sh prints it)
FRONTEND_DOMAIN="app.example.com"        # DNS: CNAME -> <your-github-username>.github.io

SUPPORT_WHATSAPP="2347074235945"         # customer-support chat number, international format
OPERATOR_NAME="Your Company Ltd"         # shown on the Terms page
SUPPORT_EMAIL="support@example.com"
WA_PHONE_ID=""                           # OPTIONAL: WhatsApp Cloud API phone number ID for direct PDF sending (docs/WHATSAPP.md)

# Derived: change only if you must
VM_NAME="ojaloom-api"
BUCKET="${PROJECT_ID}-ojaloom-db"        # database backups; bucket names are global, so this includes the project id
SA_NAME="ojaloom-vm"
