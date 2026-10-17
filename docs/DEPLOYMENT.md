# Deploying Oja Loom: GitHub Pages (web app) + Google Cloud (API and database)

> **Do not want Google Cloud?** A $4/month DigitalOcean droplet runs the same API with no Google service involved: see [DIGITALOCEAN.md](DIGITALOCEAN.md). The web app side (GitHub Pages, sections 2, 5 and 6 below) is identical.

```
 customer / shop owner
        │ https
        ├───────────────► app.example.com ── GitHub Pages ── static files (nothing secret)
        │                       │ fetch(credentials: include)
        └───────────────► api.example.com ── Google Cloud VM
                                              ├─ Caddy         HTTPS certificate, reverse proxy
                                              ├─ API container  Python, non-root, read-only filesystem
                                              └─ /data          persistent disk (SQLite)
                                                    ├─ Litestream ─► private Cloud Storage bucket (continuous, ~1 s behind)
                                                    └─ daily disk snapshots (kept 14 days)
        Paystack ─► api.example.com/webhooks/paystack        Secrets: Secret Manager (never git, never metadata)
```

## Before you start

You need: a **domain you own** · a **Google Cloud project with billing** + the `gcloud` CLI · a **GitHub repository** for this folder.

**Why a domain is not optional.** The login cookie is `SameSite=Strict`, which browsers only send between pages on the *same site*.
`app.example.com` and `api.example.com` are the same site, so it works. `yourname.github.io` and `anything.run.app` are different sites
(and `github.io` is on the Public Suffix List), so login would silently fail. The server refuses to start in production in that situation.

Pick the two names now: `app.example.com` (web app) and `api.example.com` (API).

## 1. Google Cloud: infrastructure (once, ~10 minutes)

```bash
cd deploy/gcp
cp config.example.sh config.sh        # edit: PROJECT_ID, REGION/ZONE, API_DOMAIN, FRONTEND_DOMAIN, OPERATOR_NAME, SUPPORT_EMAIL
./01-setup.sh
```
It creates (and is safe to re-run): a service account with **no keys**; a **private bucket** (uniform access, public access blocked, 14-day
soft-delete); a fixed IP; a firewall that opens only 80/443 and allows SSH **only through Google's IAP tunnel**; a 20 GB data disk with
**daily snapshots kept 14 days**; and the VM (Shielded VM, OS Login, **deletion protection** on). The VM service account gets only: write logs,
write metrics, read/write **that one bucket**, and read **its own secrets**.

It prints the VM's IP at the end.

## 2. DNS

| Type | Name | Value |
|---|---|---|
| `A` | `api.example.com` | the IP printed by `01-setup.sh` |
| `CNAME` | `app.example.com` | `<your-github-username>.github.io` |

Also **verify the domain in GitHub** (your account → Settings → Pages → *Add a domain*, add the TXT record it shows). This stops anyone
else claiming `app.example.com` if you ever delete the CNAME (subdomain takeover). A hijacked sibling subdomain is same-site with your API.

## 3. Secrets

```bash
./02-secrets.sh        # asks for the Paystack SECRET key (input hidden). Stored in Secret Manager, readable only by the VM.
```
Use `sk_test_...` first. Switch to `sk_live_...` (run the script again) when you are ready for real money. The API prints **TEST** or **LIVE** at start-up.

## 4. Deploy the API

```bash
./03-deploy.sh
```
Copies the code over the IAP tunnel, builds the container on the VM, starts it, and waits for `https://api.example.com/health`.
The first run can take a few minutes while Caddy gets your certificate (it retries until DNS has propagated).
After the first success it removes the one-time "allowed to format the data disk" flag, so a later mistake can never wipe the disk.

Your Google account needs `roles/compute.osAdminLogin` and `roles/iap.tunnelResourceAccessor` on the project (Owner has both).

## 5. Deploy the web app (GitHub Pages)

1. Push this folder to GitHub (the `.gitignore` already blocks `.env`, databases and `config.sh`).
2. **Settings → Pages → Source: GitHub Actions.** Then set **Custom domain** = `app.example.com` and tick **Enforce HTTPS** once it is available.
3. **Settings → Secrets and variables → Actions → Variables** (these are public values, not secrets):

   | Variable | Value |
   |---|---|
   | `API_BASE` | `https://api.example.com` |
   | `FRONTEND_DOMAIN` | `app.example.com` |
   | `SUPPORT_WHATSAPP` | `2347074235945` (optional, this is the default) |
4. Push to `main` (or run the workflow by hand). `frontend/**` changes redeploy automatically.

## 6. Paystack dashboard

*Settings → API Keys & Webhooks → Webhook URL:* `https://api.example.com/webhooks/paystack`. Nothing else is needed: the server
sends its own callback address with every payment. Test with Paystack's test cards while on `sk_test_` keys. Going live needs Paystack's business verification.

## 7. Check it works (do this once)

- [ ] `https://api.example.com/health` answers, and `https://api.example.com/` redirects to the web app.
- [ ] `https://app.example.com` loads. Sign up, then **reload**: you must still be signed in (proves the cookie is accepted).
- [ ] Browser dev tools → Network: no red CORS errors. If you see one, `OJALOOM_ALLOWED_ORIGINS` must equal exactly `https://app.example.com` (https, no trailing slash).
- [ ] The green support button opens a WhatsApp chat to +234 707 423 5945.
- [ ] Click **Upgrade to Pro** (page "Oja Loom Pro") and pay with a Paystack **test** card: you return to the app and Pro is active. In the Paystack dashboard the webhook shows `200`.
- [ ] Add a customer with a phone number and an order → **Send ▾** shows WhatsApp and Email. On a phone, the share sheet opens with the PDF attached.
- [ ] **Run the restore drill** (section 8). A backup you have never restored is a hope, not a backup.
- [ ] Optional: Cloud Monitoring → Uptime checks → `https://api.example.com/health`, with an email alert.

## 8. Running it

| Task | How |
|---|---|
| Update the API | `git pull && deploy/gcp/03-deploy.sh` |
| Update the web app | push to `main` |
| Logs | Cloud Logging (container logs are shipped automatically), or `gcloud compute ssh ojaloom-api --zone ZONE --tunnel-through-iap --command 'sudo docker compose -f /opt/ojaloom/docker-compose.yml logs -f app'` |
| **Restore drill (monthly)** | `sudo /opt/ojaloom/restore-drill.sh` on the VM. Restores the newest backup into a scratch folder and prints `integrity_check` and row counts. Touches nothing live |
| Rotate a secret | `./02-secrets.sh` (adds a version), then `./03-deploy.sh` |
| Roll back the API | check out the previous git commit, run `03-deploy.sh` (schema changes are additive, so older code still opens the database) |
| Run a maintenance command | `sudo docker compose -f /opt/ojaloom/docker-compose.yml exec app python3 /app/ojaloom_server.py --grant-pro owner@shop.com --days 30` (also `--make-codes N`, `--reset-password EMAIL`) |

### If something breaks

| Situation | What happens |
|---|---|
| The API container crashes | Docker restarts it. Data is on the disk |
| The VM dies | Deletion protection prevents accidents. Recreate with `01-setup.sh`; the data disk (`auto-delete=no`) is re-attached and mounted, data intact |
| The data disk is lost or corrupted | `01-setup.sh` makes a blank disk; on start the entrypoint **restores from the bucket automatically** (only when no database exists). Loss ≈ the last second or so |
| You need a past state (bad import, deleted by mistake) | On the VM: `litestream restore -config /etc/litestream.yml -timestamp 2026-10-15T09:00:00Z -o /tmp/old.db /data/ojaloom.db`, inspect `/tmp/old.db`, then copy what you need. `-txid` also works. Use `-dry-run` first |
| Bucket unreadable at start-up (permissions, outage) | The container **refuses to start**; it never creates an empty database over a backup it could not see. Fix access, it starts by itself |
| Whole region down | Data is safe in the bucket (and snapshots). Create the stack in another region (change `REGION`/`ZONE`), restore happens automatically. Expect an hour of work, not seconds |

Recovery point ≈ seconds (Litestream ships every second) · recovery time ≈ minutes to an hour depending on the failure. That is the honest figure for a single VM.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Sign-in works, then you are logged out on reload | Web app and API are not on the same registrable domain, or the API is not served over https (cookie is `Secure`) |
| `blocked by CORS policy` | `OJALOOM_ALLOWED_ORIGINS` is not exactly the web app's origin. It is set in the `ojaloom-env` instance metadata; edit `01-setup.sh` inputs and re-run it, then `03-deploy.sh` |
| Webhook shows 401 in Paystack | The secret key in Secret Manager differs from the key of the Paystack account sending it (test vs live mixed up) |
| Return from Paystack shows "paid=0" | The payment is still pending or failed at Paystack. The webhook credits it when it arrives; refresh Billing |
| Caddy cannot get a certificate | `api.example.com` does not point at the VM yet, or ports 80/443 are blocked. `docker compose logs caddy` |
| Server exits immediately in production | It prints exactly which settings are unsafe. Fix them (`OJALOOM_*` in `.env.example`) |

## What this costs and how it scales

One small VM, a 20 GB disk, snapshots, a small bucket, and a static IP: use Google's pricing calculator for your region.
GitHub Pages hosting is free for public repositories; for a private repository, check what your GitHub plan includes. Paystack and Meta charge their own fees.

SQLite is single-writer, so the API is **one instance**. That comfortably serves a lot of small shops. When you outgrow it, the next step is
PostgreSQL (Cloud SQL) with several instances behind a load balancer. That is a real migration of every query and is not included.
Cloud Run is not recommended for this database: its filesystem is temporary and instances can overlap during deploys, which breaks a single-writer SQLite file.
