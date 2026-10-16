# Security notes

## What protects what

| Risk | Control | Where |
|---|---|---|
| A stranger's website calls your API with a signed-in owner's browser | CORS allow-list (only your web app's origin), `Origin` check on every write, **CSRF token** header, `SameSite=Strict` cookie. All four are tested | `backend` · `tests/test_backend.py` |
| Cookie stolen by injected script | `HttpOnly`; `Secure` in production; host-only (no `Domain=`, so sibling subdomains never receive it) | backend |
| Injected script on the web app | Strict CSP in the page: scripts and styles only from the site itself, **no inline scripts, no `eval`** (checked), `connect-src` only the API, `form-action 'none'`, `base-uri 'none'`. Public pages the API renders use per-request nonces | `frontend/index.html` · `build.py` |
| Fake payment | Payment is **confirmed with Paystack itself** (the browser's claim is ignored), the **amount and currency are checked** against what was asked, the webhook is **HMAC-SHA512 verified**, crediting is **idempotent** (a repeated webhook adds nothing) | `paystack_finalize`, `paystack_webhook` · 5 tests |
| Callback hijack through a forged `Host` header | Links and the Paystack callback are built from the configured `OJALOOM_PUBLIC_API_URL` | backend |
| The WhatsApp endpoint used to spam or leak | The server builds the PDF and reads the phone number from the database. The caller supplies only "receipt X". Another shop's receipt looks exactly like a missing one (404). Per-shop, per-user and per-customer limits. Every attempt is logged | `share_whatsapp` · 4 tests |
| Provider error text leaking | Meta's messages are never shown to users, and the token and phone numbers are never logged | `wa_call` |
| Database lost or corrupted | Litestream copies every change to a private bucket (~1 s behind) · daily disk snapshots, 14 days · bucket soft-delete 14 days · **restore drill** · `-timestamp` point-in-time recovery | `deploy/` · `tests/test_disaster_recovery.sh` |
| An empty database replacing a good one | The entrypoint **fails closed**: if the backup cannot be read, the container stops. Production refuses to start with no backup configured | `entrypoint.sh` (tested) |
| Wiping the data disk by mistake | The VM startup script formats a disk **only if it is completely blank and a one-time flag is set**; `03-deploy.sh` removes the flag after the first success. VM has deletion protection, disk `auto-delete=no` | `startup.sh` (probe logic tested on disk images) |
| Secrets in git or logs | Secrets live in Secret Manager, are written to a root-only `0600` file at boot, and are read by the container only. `.gitignore` blocks `.env`, databases and `config.sh`. Caddy never receives a secret. No access log (receipt links carry a token in the path) | `startup.sh`, `docker-compose.yml` |
| Compromised container | Non-root user, **read-only filesystem**, all Linux capabilities dropped, `no-new-privileges`, port 8000 never published | `Dockerfile`, `docker-compose.yml` |
| Stolen SSH access | **No public SSH.** Only through Google's IAP tunnel with OS Login (your Google identity and 2FA). Firewall allows only 80/443 | `01-setup.sh` |
| Over-broad cloud permissions | VM service account: log writer, metric writer, read/write **one bucket**, read **its own secrets**. No keys exist for it | `01-setup.sh` |
| Tampered downloads | Litestream is pinned by version **and SHA-256** (Docker build and CI). GitHub Actions are pinned to **commit SHAs**; Dependabot proposes updates for you to review | `Dockerfile`, `.github/` |
| Unsafe production config | The server **refuses to start** in production unless: https URLs, an https-only origin list, `--trust-proxy`, `--secure-cookies`, no overridden provider addresses, and a web app / API pair that can share a cookie | `production_problems()` · 5 tests |

The original application already had: PBKDF2-SHA256 (600k rounds), login and signup throttling, a hash-chained audit trail, image verification on upload,
values bound as SQL parameters, and a private (`0700`/`0600`) database location. These were kept untouched. (Where SQL text is built dynamically, it is assembled from fixed fragments and user values are still bound; I inspected those builders and found them sound, but I did not audit every query in the file.)

## What you must do (a checklist, not optional)

- [ ] Turn on **2-step verification** for your Google, GitHub, Paystack and Meta accounts. They are now the keys to the business.
- [ ] Give people the **least** Google Cloud access they need. Few Owners. Remove people who leave.
- [ ] **Verify the domain in GitHub Pages** (see DEPLOYMENT.md §2) and delete DNS records you no longer use (dangling records are how subdomains get taken over).
- [ ] Use `sk_test_` until you have tested end to end, then put `sk_live_` in Secret Manager only. Never paste keys in chat, email or git.
- [ ] Run the **restore drill monthly**, and set an uptime alert on `/health`.
- [ ] Merge Dependabot pull requests (after the CI is green) so pinned versions do not go stale.
- [ ] Rotate the Paystack and WhatsApp keys if anyone who knew them leaves, or if you ever suspect exposure (`02-secrets.sh`, then `03-deploy.sh`).

## Limits to know about

* **GitHub Pages cannot send HTTP security headers.** The CSP is delivered in a `<meta>` tag, which cannot express `frame-ancestors`, and Pages cannot send
  `X-Frame-Options`. The app protects itself by hiding if it is loaded inside a frame, and the API cannot be driven from another site (CORS + CSRF). If you need
  full header control for the web app, put it behind Cloudflare or serve it from Google Cloud instead.
* **A single VM is a single point of failure.** Recovery point is about a second; recovery time is minutes to an hour (DEPLOYMENT.md). There is no automatic failover.
* **No WAF or DDoS product** beyond Google's network and the app's own per-IP rate limits. Add Cloud Armor (needs a load balancer) if you are targeted.
* **Receipt links are capability links:** anyone who has the URL can open that receipt, by design (that is how customers see them). Tokens are long and random, and are removed from server logs.
* **Direct WhatsApp sends come from one shared number** (see `WHATSAPP.md`). Replies go there, not to the shop owner.
* **Paystack webhook source IPs are not allow-listed.** The HMAC signature is the control. That is Paystack's documented method, and a forged request fails it.
* **Not independently audited.** This was reviewed and tested by its author. For a business holding other people's payment-adjacent data, a professional review before launch is worth the money.
