# Oja Loom: production workspace

The original one-file app (`ojaloom__1_.py`, 7,636 lines) split into a **static web app** for GitHub Pages and an
**API server** you can host on Google Cloud or on a small DigitalOcean droplet (no Google needed), with Paystack, WhatsApp support, a Send menu (WhatsApp / Email) and a safe database setup.

```
ojaloom/
├─ backend/                 the API server. Python standard library only, no pip packages
│  ├─ ojaloom_server.py     API + public receipt/storefront/terms pages + Paystack webhook
│  ├─ Dockerfile            non-root, Litestream pinned by SHA-256
│  ├─ entrypoint.sh         restore the database from backup if missing, then run under Litestream (fails closed)
│  ├─ litestream.yml        continuous backup to a Cloud Storage bucket
│  └─ .env.example          every setting, documented
├─ frontend/                the web app, static files for GitHub Pages
│  ├─ index.html app.css app.js config.js
│  └─ build.py              builds dist/ (fills in the API address + CSP, adds cache-busting hashes, writes CNAME)
├─ deploy/
│  ├─ digitalocean/         bootstrap.sh  ssh-keys-only.sh  update.sh  restore-drill.sh  ojaloom-admin.sh  ojaloom.service  Caddyfile  (no Google, no Docker; fits a 512 MB droplet)
│  ├─ gcp/                  01-setup.sh  02-secrets.sh  03-deploy.sh  startup.sh  (Google Cloud)
│  └─ vm/                   docker-compose.yml  Caddyfile (automatic HTTPS)  restore-drill.sh
├─ .github/workflows/       frontend-pages.yml (deploys the site)   ci.yml (runs every test)
├─ tests/                   backend (Python) · web app in a DOM (Node) · disaster-recovery drill (shell)
├─ docs/                    DEPLOYMENT.md (Google Cloud)  DIGITALOCEAN.md  WHATSAPP.md  SECURITY.md
└─ backup/                  the untouched original (read-only, SHA-256 recorded) + git bundle of every stage
```

## Run it on your computer

```bash
# 1. the API (http://127.0.0.1:8000)
cd backend && python3 ojaloom_server.py --no-browser

# 2. the web app (http://127.0.0.1:5173)
cd frontend && API_BASE=http://127.0.0.1:8000 python3 build.py && python3 -m http.server 5173 --directory dist --bind 127.0.0.1
```
Open http://127.0.0.1:5173. (Use `127.0.0.1` for both, not `localhost`: login cookies are `SameSite=Strict`.)

## Run the tests

```bash
python3 tests/test_backend.py                                   # 25 tests: CORS, cookies, CSRF, Paystack, WhatsApp, production guard
(cd tests && npm ci && node frontend_dom.mjs)                   # 12 tests: the built app in a DOM against the real backend
LITESTREAM_BIN=/path/to/litestream bash tests/test_disaster_recovery.sh   # destroy the data directory, restore from backup
```

## What changed from the original

| Area | Before | Now |
|---|---|---|
| Structure | One Python file serving everything | `frontend/` (static) + `backend/` (API only). The original is untouched in `backup/` |
| Cross-site safety | Same-origin only | CORS allow-list (your web app only), credentialed; CSRF + Origin check kept; cookie `SameSite=Strict`, `HttpOnly`, `Secure`; strict CSP on the web app |
| Paystack | Present | Secret from env **or** a mounted secret file; callback built from a configured address (never a `Host` header); shopper returned to the web app; startup banner shows TEST/LIVE; production refuses unsafe settings. Verification, signature and amount checks were already good and are now covered by tests |
| Customer support | none | Floating WhatsApp button on every screen, "Chat with support" in the mobile More menu and Settings, number on the Terms page: **+234 707 423 5945** |
| Sending a PDF | One "WhatsApp" button | **Send ▾ menu: WhatsApp / Email** on receipts, order detail, customer statements and debt reminders (and on the public receipt page) |
| PDF into WhatsApp | Share sheet, or download + chat | 1) optional **direct delivery**: the server puts the PDF into the customer's WhatsApp 2) phone share sheet with the PDF file 3) desktop: save + chat/mail opens with the message written. See `docs/WHATSAPP.md` |
| Database | SQLite file | Same SQLite, now with continuous backup to a private bucket, daily disk snapshots, fail-closed restore, and a restore drill |

## What was verified, and what was not

**Run and passing here:** 25 backend tests · 12 DOM tests (the built app against the real backend, with a browser-faithful CORS `fetch`) ·
the disaster-recovery drill with the real Litestream 0.5.17 (data survives destroying the data directory; an unreadable backup stops the
container instead of creating an empty database) · `node --check`, CSP static checks, ShellCheck, YAML validation · every documented
environment variable confirmed to be read by the server.

**Not run here (no Docker daemon, no Google Cloud account, no internet to Paystack/Meta from the sandbox). Treat as written-but-unproven until you run them once:**
the Docker build · the `gcloud` scripts · the GitHub Actions workflows · real Paystack calls (only a mock of their documented API was used) ·
real WhatsApp Cloud API calls (only a mock; template approval is Meta's) · a real browser's share sheet (jsdom has none; behaviour was tested with a stub).
Each of these has a short "how to check" step in `docs/DEPLOYMENT.md`.

**DigitalOcean setup (`deploy/digitalocean/`).** Run and passing in a sandbox: the 25 backend tests on Python 3.11, 3.12 and 3.13 (Debian 12 and 13) · the
native service flow (unprivileged user, localhost-only, destroy the data folder, automatic restore) with the real Litestream against an S3-compatible
stand-in · your original disaster-recovery drill after the one-line `entrypoint.sh` change · the Caddyfile with real Caddy · ShellCheck · the settings validator.
**Not run:** `bootstrap.sh` on a real Debian droplet (apt, ufw, swap, systemd) · a real Spaces/B2/R2 bucket · a real certificate. Details in `docs/DIGITALOCEAN.md`.

## Known limits

* **One API instance.** SQLite allows one writer. Do not run two copies. Scaling out means moving to PostgreSQL (not included).
* **A custom domain is required.** The web app and API must share a registrable domain (`app.example.com` + `api.example.com`), because
  the login cookie is `SameSite=Strict`. `*.github.io` is a public suffix, so it will not work. The server refuses to start in production if you try.
* **A browser cannot choose the app for you.** No web page can pre-select WhatsApp in a phone's share sheet or attach a file to a `wa.me` link. Only the
  WhatsApp Business Cloud API can deliver a PDF with no extra tap. Details and trade-offs in `docs/WHATSAPP.md`.
