# Deploying Oja Loom without Google Cloud: GitHub Pages (web app) + a DigitalOcean droplet (API and database)

```
 customer / shop owner
        │ https
        ├───────────────► app.yourshop.com ── GitHub Pages ── static files (nothing secret)
        │                       │ fetch(credentials: include)
        └───────────────► api.yourshop.com ── DigitalOcean droplet (Debian, 512 MB)
                                              ├─ Caddy       HTTPS certificate, reverse proxy (ports 80/443)
                                              ├─ ojaloom     systemd service: Python API on 127.0.0.1:8000, unprivileged user
                                              └─ /var/lib/ojaloom   SQLite database
                                                    └─ Litestream ─► private bucket (Backblaze B2 / Cloudflare R2 / DO Spaces), ~1 s behind
        Paystack ─► api.yourshop.com/webhooks/paystack        Secrets: /etc/ojaloom/ojaloom.env (root-only file, never git)
```

No Docker, on purpose. Measured here: the Python server uses about 48 MB and Litestream about 35 MB. With Caddy and Debian itself the whole
thing sits around 200 to 250 MB of the 512 MB. Docker's daemon plus building an image on the machine would use most of the rest.

## What replaces what

| On Google Cloud | Here |
|---|---|
| Compute Engine VM | DigitalOcean droplet (Debian 12 or 13) |
| Docker + docker-compose | a systemd service (`deploy/digitalocean/ojaloom.service`) |
| Cloud Storage bucket | any S3-compatible bucket: Backblaze B2, Cloudflare R2 or DigitalOcean Spaces |
| Secret Manager | one root-only file, `/etc/ojaloom/ojaloom.env` (weaker: see "Security", below) |
| IAP tunnel + OS Login for SSH | SSH key + firewall (`ufw`) |
| Cloud Logging | `journalctl` |
| Persistent disk snapshots | not included. The bucket is the backup. Droplet Backups are optional |

**Unchanged:** GitHub Pages for the web app, Caddy, Litestream, Paystack, and the application code. The server has no Google dependency: the only
change to existing code is one line in `backend/entrypoint.sh` (`OJALOOM_HOST`, default unchanged) so the API can listen on localhost only.

## What it costs

Prices change, so check each page before paying. When I looked (October 2026): the 512 MiB droplet is about **$4/month**, DigitalOcean Spaces about
$5/month, and Backblaze B2 and Cloudflare R2 each advertise a free tier of about 10 GB, far more than this database needs. A domain is yearly.
GitHub Pages is free for public repositories. DigitalOcean bills in US dollars: you need a card that works internationally, or PayPal.
Optional droplet Backups cost a percentage of the droplet price (about 20% for weekly); you do not need them, because Litestream already
copies every change to your bucket.

## Before you start

- [ ] A **domain you own** (any registrar). This is not optional: the login cookie is `SameSite=Strict`, so the web app and API must share a registrable
      domain (`app.yourshop.com` + `api.yourshop.com`). `github.io` will not work, and the server refuses to start if you try. Free subdomain services are
      risky for the same reason: many are on the public suffix list.
- [ ] A **DigitalOcean account**, with 2-step verification turned on.
- [ ] An account for the **backup bucket** (Backblaze, Cloudflare or DigitalOcean), also with 2-step verification.
- [ ] A **GitHub repository** containing this folder.
- [ ] Pick the two names now: `app.yourshop.com` and `api.yourshop.com`.

## 1. Create the droplet

Create → Droplets, then:

- **Image:** Debian 12 or Debian 13.
- **Plan:** Basic → Regular → the **$4 / 512 MiB / 1 vCPU / 10 GiB** size. This size is not offered in every region. When it was introduced it was in NYC1, FRA1,
  SFO3, SGP1 and AMS3, so for Nigeria **Frankfurt (FRA1) or Amsterdam (AMS3)** is the right pick. If the panel does not show the $4 size for a region, choose another.
- **Authentication: SSH key**, not a password. On your computer run `ssh-keygen -t ed25519` and paste the contents of the `.pub` file into DigitalOcean.
  (Already created it with a password? Nothing is lost: follow section 1b below.)
- **Hostname:** `ojaloom-api`.

Note the droplet's **IPv4 address**. Optionally attach a *Reserved IP* so the address survives if you ever rebuild the droplet (check its current price).

## 1b. I created the droplet with a password

Passwords work, and DigitalOcean allows them, but it recommends keys. A password on a server facing the internet is guessed at all day by bots. Your droplet is new and empty,
so you have three choices:

**A. Add a key now and switch passwords off (recommended, about 5 minutes).** DigitalOcean's panel cannot add a key to a droplet that already exists, but you can do it yourself while the password still works:

1. **On your computer** (Windows 10/11 PowerShell, Mac or Linux Terminal), make a key. Press Enter at each question:
   ```
   ssh-keygen -t ed25519
   ```
   Then show it. Mac/Linux: `cat ~/.ssh/id_ed25519.pub`. Windows PowerShell: `type $env:USERPROFILE\.ssh\id_ed25519.pub`. It is **one line** that starts with `ssh-ed25519`. (The other file, without `.pub`, is your private key: never share it.)
2. **Log in with the password:** `ssh root@DROPLET_IP`. DigitalOcean may make you choose a new password on the first login. Choose a long one.
3. **Install the key** (on the droplet), then paste the one line (right-click pastes in most terminals), save with `Ctrl+O`, `Enter`, `Ctrl+X`:
   ```
   mkdir -p ~/.ssh && nano ~/.ssh/authorized_keys
   chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys
   ```
   On Mac/Linux, `ssh-copy-id root@DROPLET_IP` does this for you.
4. **Test it:** open a **second** window on your computer and run `ssh root@DROPLET_IP`. It must log you in **without asking for the droplet's password**. Keep the first window open.
5. **Turn passwords off** (in the first window, from the cloned repository of step 4):
   ```
   bash deploy/digitalocean/ssh-keys-only.sh
   ```
   It refuses to run if no valid key is installed, asks you to confirm that step 4 worked, and checks the result with the SSH server itself. Afterwards a password attempt is refused.
   To undo: `rm /etc/ssh/sshd_config.d/00-ojaloom.conf && systemctl reload ssh`.

**B. Start over with a key.** Create a new droplet (choose *SSH Key*, not *Password*), destroy the old one, and use the new IP in your DNS. Fine, since nothing is installed yet.

**C. Keep the password (not recommended).** Use a long random one (20+ characters, used nowhere else) and expect `bootstrap.sh` to warn you each time. The firewall rate-limits ssh, which slows
guessing but does not stop it. If you are ever locked out, DigitalOcean's web **Console** and **Recovery Console** (on the droplet's page) can get you back in.

## 2. Create the backup bucket

Make the bucket **private**. Write down five things for the settings file in step 4. I could only test against a local S3 stand-in, not against these services, so the
values below come from the providers' and Litestream's documentation. Step 7 (the restore drill) is what proves them.

| Provider | `LITESTREAM_REPLICA_URL` | `LITESTREAM_ENDPOINT` | `LITESTREAM_REGION` | Key ID / secret |
|---|---|---|---|---|
| **Backblaze B2** | `s3://BUCKET/ojaloom` | `https://s3.REGION.backblazeb2.com` (shown on the bucket page) | the `REGION` part, for example `us-west-004` | create an *Application Key* limited to this one bucket: `keyID` → `LITESTREAM_ACCESS_KEY_ID`, `applicationKey` → `LITESTREAM_SECRET_ACCESS_KEY` |
| **Cloudflare R2** | `s3://BUCKET/ojaloom` | `https://ACCOUNT_ID.r2.cloudflarestorage.com` | `auto` | an R2 API token with read and write on this one bucket |
| **DigitalOcean Spaces** | `s3://BUCKET/ojaloom` | `https://REGION.digitaloceanspaces.com` | the region slug, for example `fra1` | Spaces access key (a key limited to one bucket, if the panel offers it) |

Use a key that can reach **only this bucket**. Never make the bucket public.

## 3. DNS

At your registrar (or at DigitalOcean's DNS, if you point your domain's nameservers there):

| Type | Name | Value |
|---|---|---|
| `A` | `api` | the droplet's IPv4 address |
| `CNAME` | `app` | `YOUR-GITHUB-USER.github.io` |

Also **verify the domain in GitHub** (your account → Settings → Pages → *Add a domain*, add the TXT record it shows), exactly as in
[DEPLOYMENT.md](DEPLOYMENT.md) section 2. Delete DNS records you no longer use. Check the API name with `nslookup api.yourshop.com`: it must show the droplet's IP.

## 4. Set up the server

Open the droplet's console in the DigitalOcean panel, or `ssh root@DROPLET_IP`. If you are logged in as `root`, leave out `sudo` in any command below.

```bash
apt-get update && apt-get install -y git
git clone https://github.com/YOUR-USER/YOUR-REPO.git /root/ojaloom
cd /root/ojaloom

bash deploy/digitalocean/bootstrap.sh      # 1st run: creates /etc/ojaloom/ojaloom.env and stops
nano /etc/ojaloom/ojaloom.env              # fill it in (rules below)
bash deploy/digitalocean/bootstrap.sh --check    # only checks the settings; changes nothing
bash deploy/digitalocean/bootstrap.sh      # installs everything and starts it
```

A **private repository** needs a read-only *deploy key*: run `ssh-keygen -t ed25519` on the droplet, add the `.pub` as a read-only Deploy key in the repo's
Settings, and clone with the `git@github.com:...` address.

**Rules for the settings file:** one `KEY=value` per line, **no quotes**, and **no comment after a value** (comments go on their own line). Set these:

| Setting | Value |
|---|---|
| `OJALOOM_FRONTEND_URL` | `https://app.yourshop.com` |
| `OJALOOM_PUBLIC_API_URL` | `https://api.yourshop.com` (Caddy gets the certificate for this name) |
| `OJALOOM_ALLOWED_ORIGINS` | `https://app.yourshop.com` |
| `OJALOOM_OPERATOR_NAME`, `OJALOOM_SUPPORT_EMAIL` | shown on the Terms page |
| the five `LITESTREAM_*` lines | from step 2 |
| `OJALOOM_PAYSTACK_SECRET` | remove the leading `#` and paste your key. `sk_test_...` while testing |

`--check` refuses placeholders (`example.com`, `REPLACE_ME`), quotes, comments after values, and Windows line endings (it repairs those) before it changes anything.

What `bootstrap.sh` does, in order: validates the settings and warns if DNS does not point at this droplet · installs packages · adds **1 GB swap** ·
creates the unprivileged `ojaloom` user · installs **Litestream 0.5.17 only if its SHA-256 matches the pinned value** · installs Caddy from its official repository ·
copies the application into `/opt/ojaloom` (owned by root, so the service cannot modify its own code) · turns on the firewall (ssh, 80, 443) and automatic security updates ·
starts both services and waits for `https://api.yourshop.com/health`.

It ends with `SUCCESS: https://api.yourshop.com/health answers`. If it does not, see "Troubleshooting".

## 5. GitHub Pages (the web app)

Exactly as in [DEPLOYMENT.md](DEPLOYMENT.md) section 5, with your own names:

1. Repository → Settings → Secrets and variables → Actions → **Variables**: `API_BASE` = `https://api.yourshop.com`, `FRONTEND_DOMAIN` = `app.yourshop.com`
   (optional: `SUPPORT_WHATSAPP`).
2. Settings → Pages → Source: **GitHub Actions**. Set **Custom domain** to `app.yourshop.com`, and tick **Enforce HTTPS** once it is offered.
3. Push to `main` and watch the Actions tab.

## 6. Paystack

Dashboard → Settings → API Keys & Webhooks → Webhook URL: `https://api.yourshop.com/webhooks/paystack`. Use `sk_test_` until everything works, then put
`sk_live_` in the settings file and run `sudo systemctl restart ojaloom`.

## 7. Check it works (do this once)

1. `https://api.yourshop.com/health` answers in a browser.
2. Open `https://app.yourshop.com`, sign up, **reload the page**, and confirm you are still signed in. (If not, the two names are not on one domain.)
3. **Prove the backup.** Wait a minute, then:
   ```bash
   /opt/ojaloom/restore-drill.sh
   ```
   You want `integrity_check : ok` and counts that match what you created. This reads the bucket with the keys from the settings file, so it also proves those are right.
4. Run a test payment with a Paystack test card.

## Running it

| I want to | Command (as root, or with `sudo`) |
|---|---|
| see if it is up | `systemctl status ojaloom caddy` |
| read the logs | `journalctl -u ojaloom -n 100 --no-pager` (Caddy: `journalctl -u caddy`) |
| update after a `git pull` | `cd /root/ojaloom && git pull && bash deploy/digitalocean/update.sh` |
| change a setting or key | `nano /etc/ojaloom/ojaloom.env && systemctl restart ojaloom` |
| give someone Pro / make codes / reset a password | `ojaloom-admin --grant-pro owner@shop.com --days 30` · `ojaloom-admin --make-codes 5` · `ojaloom-admin --reset-password owner@shop.com` |
| check the backup works (monthly) | `/opt/ojaloom/restore-drill.sh` |
| see the data as it was at a past moment | `/opt/ojaloom/restore-drill.sh -timestamp 2026-10-15T09:00:00Z` (UTC; prints counts) |
| keep that restored file to inspect | `RESTORE_TO=/root/old /opt/ojaloom/restore-drill.sh -timestamp ...` (delete it afterwards: it holds customer data) |
| check memory | `free -h` |

An update restarts the API for a few seconds. Caddy waits up to 10 seconds for it, so visitors normally do not notice.

## If the droplet is lost

The database lives in your bucket. Create a new droplet, point the `api` DNS record at its IP, and repeat step 4 with the **same settings file**. On first start, with no
database on disk, `entrypoint.sh` restores the newest backup by itself. It **fails closed**: if it cannot read the backup it stops, rather than starting an empty database.
You lose at most about a second of changes. **Never run two copies at once**: SQLite allows one writer.

## Security

- Secrets are in `/etc/ojaloom/ojaloom.env`, readable by root only. That is **weaker than Google's Secret Manager**: anyone with root on the droplet, or with control of your
  DigitalOcean account, can read it. Use 2-step verification, and rotate the Paystack key if you ever suspect exposure.
- SSH is on the public internet. Use key login only (section 1b): the bootstrap warns while passwords are still accepted. You can add a DigitalOcean Cloud Firewall that allows port 22 only from
  your own IP, but then make sure you can still reach the droplet from where you work. If you do, keep ports 80 and 443 open or certificates will stop renewing.
- Security updates install themselves, but a **new kernel needs a reboot** now and then: run `reboot` when it suits you.
- The service runs as an unprivileged user, can write only to its own data folder, and listens on `127.0.0.1` so the internet reaches it only through Caddy.
  After setup, `systemd-analyze security ojaloom` gives a score for these protections.
- The full table, and the limits of this setup, are in [SECURITY.md](SECURITY.md).

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `bootstrap.sh` says the API did not start | `journalctl -u ojaloom -n 40`. Usually a wrong backup key, endpoint or region, or a placeholder left in the settings file. Fix it, run the script again |
| API log shows it cannot reach the backup, and the service keeps waiting | By design (fail closed). Check the five `LITESTREAM_*` values and the bucket name; the API will not start against an unreadable backup |
| `https://api...` does not answer, but `curl http://127.0.0.1:8000/health` on the droplet does | DNS not pointing here yet, or ports 80/443 blocked (a Cloud Firewall?). `journalctl -u caddy -n 40` |
| Sign-in works, but you are signed out after a reload | The web app and API are not on one registrable domain, or you opened the app by a different name than `FRONTEND_DOMAIN` |
| The server exits at once in production | It prints the exact problem (a non-https address, mismatched domains, no backup configured). `journalctl -u ojaloom` |
| Out of memory | `free -h`. The 1 GB swap should be on. Normal use is far below the 360 MB cap in the service file |
| "Not valid" settings errors | Run `bash deploy/digitalocean/bootstrap.sh --check`: it names every problem |

## If you want to drop Google completely

The files `deploy/gcp/`, `deploy/vm/` and the `gcs://` line in `backend/litestream.yml` are only used by the Google setup. Nothing here depends on them, so you can delete them
(and remove them from the `shell-scripts` job in `.github/workflows/ci.yml` and from `README.md`). `backend/Dockerfile` is harmless to keep.

## What was tested, and what was not

**Run here, and passing:** the 25 backend tests on Python 3.11 (Debian 12), 3.12 and 3.13 (Debian 13) · Litestream 0.5.17's SHA-256 pin against the real download ·
backup to an S3-compatible endpoint and restore of 500 rows with `integrity_check: ok` · the full service flow with the real `entrypoint.sh`, the real unit's
settings, an unprivileged user, the API listening only on `127.0.0.1`, the data folder deleted, and the database restored by itself from the bucket ·
the project's original disaster-recovery drill, after the one-line `entrypoint.sh` change · the Caddyfile with real Caddy v2.11 (valid; proxies; strips the `Server`
header; waits for a restarting API) · `ssh-keys-only.sh` against a real OpenSSH 9.6 server (refuses without a valid key; fixes folder permissions; after it, a password login is refused and a key login works; detects an overriding config file and undoes itself) · ShellCheck on all scripts · the settings validator against good and bad files · the restore drill, including `-timestamp` and `RESTORE_TO`.

**Not run (treat as unproven until you run them once):**

- `bootstrap.sh` on a **real Debian droplet**: the apt steps, swap, `ufw`, the Caddy repository, and starting systemd units. The sandbox had no systemd.
- `ssh-keys-only.sh` on **Debian's** OpenSSH (I tested OpenSSH 9.6 on Ubuntu; the settings it uses are standard, and it undoes itself if the server does not apply them).
- The **sandboxing options** in `ojaloom.service`. They are standard, but I have not seen them run under a real systemd.
- A **real Spaces, B2 or R2 bucket**. My stand-in did not check signatures, so a wrong key would not have been caught there. Step 7 is your check.
- A real **Let's Encrypt certificate**, real **Paystack**, real **GitHub Pages**.
- An upload larger than Caddy's 10 MB limit returned an error (502 in my test), not the clean 413 I expected. It is refused either way, and I did not investigate further.
