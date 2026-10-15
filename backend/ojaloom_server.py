#!/usr/bin/env python3
"""
Oja Loom API server
===================
The backend half of Oja Loom (the web app is a separate static site, see ../frontend).
It serves the JSON API, the public receipt / storefront / terms pages and the Paystack webhook.

Requirements:
    Python 3.10+ only. No pip packages required.

Run locally (the web app is expected at http://127.0.0.1:5173, see frontend/README.md):
    python ojaloom_server.py --no-browser

Run in production (behind an HTTPS reverse proxy, see ../docs/DEPLOYMENT.md):
    OJALOOM_ENV=production python ojaloom_server.py --host 0.0.0.0 --port 8000 --no-browser --trust-proxy --secure-cookies

Everything is configured with OJALOOM_* environment variables, see .env.example.
In production the server refuses to start while the configuration is unsafe (see production_problems()).

Data:
    A SQLite database is created automatically in ./ojaloom_data/ojaloom.db (or --data-dir).

Security notes:
    * Strict Content-Security-Policy with per-request nonces on every page this server renders
    * SameSite=Strict HttpOnly session cookie, CSRF token and an Origin allow-list on every write
    * CORS only for the origins in OJALOOM_ALLOWED_ORIGINS (credentials allowed for those and nobody else)
    * PBKDF2-SHA256 (600k rounds), login / signup throttling, uploaded images verified before storage
    * Paystack payments are confirmed with Paystack itself (never trusted from the browser); webhook is HMAC-SHA512 signed
    * Database folder is created private (0700) and the database file is 0600
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import csv
import datetime as dt
import hashlib
import getpass
import hmac
import html
import io
import http.cookies
import json
import math
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import struct
import traceback
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
import webbrowser
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable

APP_NAME = "Oja Loom"
APP_VERSION = "1.4.0-split"


def env(name: str, default: str = "") -> str:
    """Read OJALOOM_<name>. Falls back to the old OJAHQ_<name> so a server set up before the rename keeps working."""
    return os.environ.get("OJALOOM_" + name) or os.environ.get("OJAHQ_" + name) or default


def secret(name: str) -> str:
    """Like env(), but also accepts OJALOOM_<name>_FILE pointing at a file (Docker / Secret Manager style mounts)."""
    value = env(name)
    if value:
        return value.strip()
    path = env(name + "_FILE")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            print(f"warning: cannot read the file given in OJALOOM_{name}_FILE", file=sys.stderr)
    return ""
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
SESSION_DAYS = 14
MAX_SESSIONS_PER_USER = 10
PASSWORD_ITERATIONS = 600_000          # used for every new password hash
LEGACY_PASSWORD_ITERATIONS = 310_000   # hashes written by v1.0; upgraded at next login
MIN_PASSWORD_LENGTH = 10
MAX_BODY = 8 * 1024 * 1024
MAX_AUTH_BODY = 16 * 1024
MAX_IMAGE_CHARS = 3_000_000
MAX_MONEY_KOBO = 10**13                # N100 billion
MAX_QTY = 10_000_000
MAX_CUSTOM_CATEGORIES = 100
REQUEST_TIMEOUT = 30
LOW_STOCK_DEFAULT = 5
REFERRED_BONUS_DAYS = 7        # extra free days for a shop that signs up with a referral code
REFERRER_BONUS_DAYS = 14       # extra free days for the referrer each time a referred shop reaches its sales target
# Referral rewards keep getting tougher: the 1st reward needs the referred shop to complete 1 sale, the 2nd needs 2,
# the 3rd needs 4, and so on. Edit this list to change how steep it is; its length is the reward limit.
REFERRAL_SALES_REQUIRED = (1, 2, 4, 7, 10)
MAX_REWARDED_REFERRALS = len(REFERRAL_SALES_REQUIRED)   # rewards per referrer (was 20)
REFERRAL_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L lookalikes

# ---- plans and billing -----------------------------------------------------------------
PRO_PRICE_NAIRA = 1000          # Oja Loom Pro: N1,000 ...
PRO_PERIOD_DAYS = 30            # ... for every 30 days
FREE_MAX_PRODUCTS = 30          # what the free plan allows once the trial is over
FREE_MAX_ORDERS_PER_MONTH = 50
FREE_ACTIVITY_DAYS = 7          # edit history window on the free plan
FREE_REPORT_DAYS = 31           # longest report period on the free plan
# The paywall only bites when the operator switches it on (--enforce-paywall or OJALOOM_ENFORCE_PAYWALL=1).
# Until then every shop has every feature, so upgrading this file never locks anybody out by surprise.
PAYWALL_ENFORCED = env("ENFORCE_PAYWALL") in ("1", "true", "yes")
PAYSTACK_SECRET = secret("PAYSTACK_SECRET")   # card / bank / USSD payments through Paystack (sk_test_... or sk_live_...)
PAYSTACK_BASE = env("PAYSTACK_BASE", "https://api.paystack.co").rstrip("/")   # only ever changed by the automated tests
PAY_NOTE = env("PAY_NOTE")                 # shown on the Upgrade page (bank details, WhatsApp number...)
TERMS_VERSION = "2026-10-09"   # bump this when you change the Terms: every account is asked to accept again
OPERATOR_NAME = env("OPERATOR_NAME")      # who runs this Oja Loom; shown in the Terms
SUPPORT_EMAIL = env("SUPPORT_EMAIL")      # where people can reach you; shown in the Terms
PRO_FEATURES: dict[str, tuple[str, str]] = {
    "pdf_receipt": ("PDF receipts and invoices", "Branded PDF receipts and invoices with a QR code, payment history and the amount in words, plus 80 mm thermal slips."),
    "statement_pdf": ("Customer statements", "A full statement of account for any customer as a PDF you can send on WhatsApp."),
    "debts_pdf": ("Debt reports", "Everything owed to you, grouped by customer and by how late it is, as a PDF or spreadsheet."),
    "report_export": ("Report downloads", "Download sales reports as a PDF or a spreadsheet."),
    "long_reports": ("Reports for any dates", f"Free reports cover up to {FREE_REPORT_DAYS} days. Pro covers any period you choose."),
    "activity_export": ("Full edit history", f"Free keeps the last {FREE_ACTIVITY_DAYS} days in view. Pro shows everything, searchable, and exports it as a PDF or spreadsheet."),
    "unlimited": ("Unlimited products and orders", f"Free holds {FREE_MAX_PRODUCTS} products and {FREE_MAX_ORDERS_PER_MONTH} orders a month."),
    "expense_export": ("Expense reports", "Download your expenses as a PDF or a spreadsheet, with a breakdown by category and your net profit."),
    "storefront_pro": ("Storefront without Oja Loom branding", "Remove the 'powered by Oja Loom' line from your public store page."),
}

# Runtime switches (set from the command line in main()).
TRUST_PROXY = False
SECURE_COOKIES = False

# ---- deployment: the web app and this API are two separate sites ------------------------------
ENVIRONMENT = env("ENV", "development").strip().lower()      # "production" switches on the strict start-up checks
FRONTEND_URL = env("FRONTEND_URL", "http://127.0.0.1:5173").strip().rstrip("/")   # where the web app lives (GitHub Pages)
PUBLIC_API_URL = env("PUBLIC_API_URL").strip().rstrip("/")   # this server's own public https address, used in links it generates
ALLOWED_ORIGINS: frozenset[str] = frozenset(
    o.strip().rstrip("/").lower() for o in env("ALLOWED_ORIGINS", FRONTEND_URL).split(",") if o.strip()
)
SUPPORT_WHATSAPP = re.sub(r"\D+", "", env("SUPPORT_WHATSAPP", "2347074235945"))   # customer-support WhatsApp chat (international format)

# ---- WhatsApp Business Cloud API (optional): lets the server put a PDF straight into a customer's WhatsApp ----
WA_TOKEN = secret("WA_TOKEN")                      # permanent access token of a Meta system user
WA_PHONE_ID = env("WA_PHONE_ID")                   # the Cloud API "phone number ID" the PDFs are sent from
WA_GRAPH_BASE = env("WA_GRAPH_BASE", "https://graph.facebook.com").rstrip("/")
WA_GRAPH_VERSION = env("WA_GRAPH_VERSION", "v23.0")
WA_TEMPLATE_LANG = env("WA_TEMPLATE_LANG", "en")
WA_TEMPLATE_RECEIPT = env("WA_TEMPLATE_RECEIPT", "ojaloom_receipt")
WA_TEMPLATE_STATEMENT = env("WA_TEMPLATE_STATEMENT", "ojaloom_statement")
WA_DAILY_LIMIT_PER_CUSTOMER = 10

DATA_DIR: Path
DB_PATH: Path

DB_LOCK = threading.RLock()

# Product / business categories offered in every dropdown. Businesses can add their own.
DEFAULT_CATEGORIES: tuple[str, ...] = (
    "Fashion & Clothing",
    "Shoes & Bags",
    "Jewellery & Accessories",
    "Beauty & Personal Care",
    "Hair & Wigs",
    "Food & Drinks",
    "Groceries & Provisions",
    "Bakery & Snacks",
    "Phones & Accessories",
    "Electronics & Gadgets",
    "Home & Kitchen",
    "Furniture & Decor",
    "Health & Wellness",
    "Baby & Kids",
    "Books & Stationery",
    "Building & Hardware",
    "Auto Parts",
    "Agriculture & Farm Produce",
    "Services",
    "Other",
)

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PHONE_DIGITS_RE = re.compile(r"\D+")
IMAGE_RE = re.compile(r"^data:image/(png|jpeg|webp|gif);base64,([A-Za-z0-9+/=]+)$")

COMMON_PASSWORDS = frozenset(
    """
    1234567890 0123456789 1q2w3e4r5t qwertyuiop asdfghjkl1 password12 password123 password1234
    passw0rd123 iloveyou12 iloveyou123 welcome123 welcome1234 admin12345 administrator letmein123
    abcd123456 abcdefghij qwerty1234 qwerty12345 1234567891 11111111111 ojahq12345 ojahq123456 ojaloom12345 ojaloom123456
    """.split()
)


# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------

# --------------------------------------------------------------------------------------
# Throttling (in memory; resets on restart, which is fine for a single-process server)
# --------------------------------------------------------------------------------------
_RATE_LOCK = threading.Lock()
_RATE: dict[str, list[float]] = {}


def rate_limit(key: str, limit: int, window: int, record: bool = True) -> bool:
    """True when the caller is still under `limit` hits in the last `window` seconds."""
    now = time.monotonic()
    with _RATE_LOCK:
        hits = [t for t in _RATE.get(key, ()) if now - t < window]
        if len(hits) >= limit:
            _RATE[key] = hits
            return False
        if record:
            hits.append(now)
        if hits:
            _RATE[key] = hits
        else:
            _RATE.pop(key, None)
        if len(_RATE) > 20_000:  # keep memory bounded if someone sprays random keys
            for k in [k for k, v in _RATE.items() if not v or now - v[-1] > 3600]:
                _RATE.pop(k, None)
        return True


def rate_record(key: str) -> None:
    with _RATE_LOCK:
        _RATE.setdefault(key, []).append(time.monotonic())


def rate_clear(key: str) -> None:
    with _RATE_LOCK:
        _RATE.pop(key, None)

def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_now() -> str:
    return utcnow().isoformat(timespec="seconds")


def today_iso() -> str:
    return dt.date.today().isoformat()


def parse_date(value: str | None, default: dt.date) -> dt.date:
    if not value:
        return default
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return default


def money_to_kobo(value: Any) -> int:
    """Naira (string/number) -> integer kobo. Rejects junk, negatives and absurd sizes."""
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        raise ValueError("Enter a valid amount.")
    try:
        d = Decimal(str(value).strip().replace(",", "")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Enter a valid amount.")
    if d < 0:
        raise ValueError("Amounts cannot be negative.")
    kobo = int(d * 100)
    if kobo > MAX_MONEY_KOBO:
        raise ValueError("That amount is too large.")
    return kobo


def kobo_to_number(value: int | None) -> float:
    return round((value or 0) / 100, 2)


def parse_int(value: Any, label: str, minimum: int = 0, maximum: int = MAX_QTY, default: int = 0) -> int:
    """Whole number from user input with clear errors (blank -> default)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a whole number.")
    try:
        if isinstance(value, float):
            if not value.is_integer():
                raise ValueError
            n = int(value)
        else:
            n = int(str(value).strip())
    except (ValueError, TypeError):
        raise ValueError(f"{label} must be a whole number.")
    if n < minimum or n > maximum:
        raise ValueError(f"{label} must be between {minimum:,} and {maximum:,}.")
    return n


def to_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "business"


def normalize_ng_phone(value: str | None) -> str:
    if not value:
        return ""
    digits = PHONE_DIGITS_RE.sub("", value)
    if digits.startswith("234"):
        return digits
    if digits.startswith("0") and len(digits) >= 10:
        return "234" + digits[1:]
    if len(digits) == 10 and digits.startswith(("7", "8", "9")):
        return "234" + digits
    return digits


def public_phone(value: str | None) -> str:
    p = normalize_ng_phone(value)
    return f"+{p}" if p else ""


def new_id(prefix: str = "") -> str:
    return prefix + secrets.token_hex(16)


# --------------------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------------------

def hash_password(password: str, salt: bytes | None = None, iterations: int = PASSWORD_ITERATIONS) -> tuple[str, str, int]:
    if salt is None:
        salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return base64.b64encode(salt).decode(), base64.b64encode(digest).decode(), iterations


def verify_password(password: str, salt_b64: str, digest_b64: str, iterations: int = LEGACY_PASSWORD_ITERATIONS) -> bool:
    try:
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    return hmac.compare_digest(actual, expected)


def burn_password_check(password: str) -> None:
    """Spend the same time as a real check so unknown emails cannot be detected by timing."""
    hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), b"ojaloom-timing-pad", PASSWORD_ITERATIONS)


def validate_password(password: str, email: str = "") -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > 200:
        raise ValueError("Password is too long.")
    if password.lower() in COMMON_PASSWORDS or len(set(password)) <= 3:
        raise ValueError("That password is too easy to guess. Choose something less common.")
    local = email.split("@")[0].lower()
    if len(local) >= 4 and local in password.lower():
        raise ValueError("Your password should not contain your email name.")


def validate_email(email: str) -> str:
    email = email.strip().lower()
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise ValueError("Enter a valid email address.")
    return email


def require_text(value: Any, label: str, max_len: int = 200) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required.")
    if len(text) > max_len:
        raise ValueError(f"{label} is too long.")
    return text


def optional_text(value: Any, max_len: int = 2000) -> str:
    text = str(value or "").strip()
    if len(text) > max_len:
        raise ValueError("A field is too long.")
    return text


# --------------------------------------------------------------------------------------
# Images (stored as data: URIs in SQLite, served from /media/... so lists stay light)
# --------------------------------------------------------------------------------------

def clean_image(value: Any) -> str:
    """Return a verified image data URI or '' (meaning: no image)."""
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) > MAX_IMAGE_CHARS:
        raise ValueError("That image is too large. Use one under 2 MB.")
    m = IMAGE_RE.match(text)
    if not m:
        raise ValueError("Images must be PNG, JPEG, WebP or GIF files.")
    kind, b64 = m.groups()
    try:
        head = base64.b64decode(b64[:64])
    except Exception:
        raise ValueError("That image file is damaged.")
    ok = (
        (kind == "png" and head.startswith(b"\x89PNG\r\n\x1a\n"))
        or (kind == "jpeg" and head.startswith(b"\xff\xd8\xff"))
        or (kind == "gif" and head[:6] in (b"GIF87a", b"GIF89a"))
        or (kind == "webp" and head[:4] == b"RIFF" and head[8:12] == b"WEBP")
    )
    if not ok:
        raise ValueError("That file does not look like a real image.")
    return text


def decode_image(data_uri: str) -> tuple[str, bytes] | None:
    m = IMAGE_RE.match(data_uri or "")
    if not m:
        return None
    try:
        return f"image/{m.group(1)}", base64.b64decode(m.group(2))
    except Exception:
        return None


# --------------------------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------------------------

def clean_category(value: Any) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 60:
        raise ValueError("Category names can be at most 60 characters.")
    return text


def canonical_category(conn: sqlite3.Connection, business_id: str, value: Any) -> str:
    """Stored spelling of a category; saves it as one of the business's own when it is new."""
    name = clean_category(value)
    if not name:
        return ""
    folded = name.casefold()
    for default in DEFAULT_CATEGORIES:
        if default.casefold() == folded:
            return default
    row = conn.execute(
        "SELECT name FROM product_categories WHERE business_id=? AND name=? COLLATE NOCASE", (business_id, name)
    ).fetchone()
    if row:
        return row["name"]
    count = conn.execute("SELECT COUNT(*) FROM product_categories WHERE business_id=?", (business_id,)).fetchone()[0]
    if count >= MAX_CUSTOM_CATEGORIES:
        raise ValueError(f"You can save up to {MAX_CUSTOM_CATEGORIES} custom categories.")
    conn.execute(
        "INSERT INTO product_categories(id,business_id,name,created_at) VALUES(?,?,?,?)",
        (new_id("cat_"), business_id, name, iso_now()),
    )
    return name


def categories_payload(conn: sqlite3.Connection, business_id: str) -> list[dict[str, Any]]:
    """Everything the category dropdowns need: the business's own, legacy free-text values, then suggestions."""
    used: dict[str, list[Any]] = {}
    for r in conn.execute(
        "SELECT category, COUNT(*) n FROM products WHERE business_id=? AND category<>'' GROUP BY category", (business_id,)
    ):
        key = r["category"].casefold()
        if key in used:
            used[key][1] += r["n"]
        else:
            used[key] = [r["category"], r["n"]]
    defaults = {d.casefold(): d for d in DEFAULT_CATEGORIES}
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for s in conn.execute(
        "SELECT id,name FROM product_categories WHERE business_id=? ORDER BY name COLLATE NOCASE", (business_id,)
    ):
        key = s["name"].casefold()
        seen.add(key)
        items.append({"id": s["id"], "name": s["name"], "kind": "custom", "count": used.get(key, [0, 0])[1]})
    for key, (display, n) in sorted(used.items(), key=lambda kv: kv[1][0].casefold()):
        if key in seen or key in defaults:
            continue
        seen.add(key)
        items.append({"id": None, "name": display, "kind": "legacy", "count": n})
    for d in DEFAULT_CATEGORIES:
        items.append({"id": None, "name": d, "kind": "default", "count": used.get(d.casefold(), [0, 0])[1]})
    return items


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextlib.contextmanager
def transaction(conn: sqlite3.Connection, immediate: bool = False):
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


# --------------------------------------------------------------------------------------
# Referrals: a shop owner shares a link; the new shop gets bonus trial days at sign-up and the
# referrer is rewarded when that shop completes enough real sales. Each reward needs more sales than
# the one before it (see REFERRAL_SALES_REQUIRED) and a referrer can earn at most MAX_REWARDED_REFERRALS.
# --------------------------------------------------------------------------------------

def normalize_referral_code(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()[:12]


def referral_code_for(conn: sqlite3.Connection, business_id: str) -> str:
    row = conn.execute("SELECT referral_code FROM businesses WHERE id=?", (business_id,)).fetchone()
    if row and row["referral_code"]:
        return row["referral_code"]
    for _ in range(30):
        code = "".join(secrets.choice(REFERRAL_ALPHABET) for _ in range(7))
        if not conn.execute("SELECT 1 FROM businesses WHERE referral_code=?", (code,)).fetchone():
            conn.execute("UPDATE businesses SET referral_code=? WHERE id=? AND referral_code IS NULL", (code, business_id))
            break
    return conn.execute("SELECT referral_code FROM businesses WHERE id=?", (business_id,)).fetchone()[0]


def find_referrer(conn: sqlite3.Connection, code: str) -> sqlite3.Row | None:
    if len(code) < 5:
        return None
    return conn.execute("SELECT id,name,phone,email FROM businesses WHERE referral_code=?", (code,)).fetchone()


def grant_trial_days(conn: sqlite3.Connection, business_id: str, days: int) -> None:
    """Add free days on top of whatever is left of the trial (or from today if it already ended)."""
    row = conn.execute("SELECT trial_end FROM businesses WHERE id=?", (business_id,)).fetchone()
    if not row or days <= 0:
        return
    now = utcnow()
    try:
        current = dt.datetime.fromisoformat(row["trial_end"])
        if current.tzinfo is None:
            current = current.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        current = now
    new_end = (max(current, now) + dt.timedelta(days=days)).isoformat(timespec="seconds")
    stamp = iso_now()
    revive = "CASE WHEN {c} IN ('trialing','expired','trial_expired') THEN 'trialing' ELSE {c} END"
    conn.execute(f"UPDATE businesses SET trial_end=?, subscription_status={revive.format(c='subscription_status')}, updated_at=? WHERE id=?", (new_end, stamp, business_id))
    conn.execute(f"UPDATE subscriptions SET trial_end=?, status={revive.format(c='status')}, updated_at=? WHERE business_id=?", (new_end, stamp, business_id))


def referral_sales_needed(rewards_earned: int) -> int:
    """Completed sales a referred shop needs before the referrer's next reward. Rises with every reward earned."""
    return REFERRAL_SALES_REQUIRED[min(max(rewards_earned, 0), len(REFERRAL_SALES_REQUIRED) - 1)]


def completed_sales(conn: sqlite3.Connection, business_id: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM orders WHERE business_id=? AND status='completed' AND total>0", (business_id,)).fetchone()[0]


def rewards_earned_by(conn: sqlite3.Connection, referrer_id: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM referrals WHERE referrer_business_id=? AND status='rewarded' AND referrer_bonus_days>0",
        (referrer_id,),
    ).fetchone()[0]


def qualify_referral(conn: sqlite3.Connection, business_id: str, total_kobo: int) -> None:
    """Called when an order is marked Completed. The referrer is rewarded once the referred shop has completed
    as many sales as the referrer's next reward needs. The bar goes up with every reward earned."""
    if total_kobo <= 0:
        return
    ref = conn.execute("SELECT id,referrer_business_id FROM referrals WHERE referred_business_id=? AND status='joined'", (business_id,)).fetchone()
    if not ref:
        return
    earned = rewards_earned_by(conn, ref["referrer_business_id"])
    if earned >= MAX_REWARDED_REFERRALS:
        days, needed = 0, 1          # reward limit reached: the referral is closed without a reward
    else:
        days, needed = REFERRER_BONUS_DAYS, referral_sales_needed(earned)
    if completed_sales(conn, business_id) < needed:
        return                       # target not reached yet: the referral stays 'joined'
    conn.execute("UPDATE referrals SET status='rewarded', referrer_bonus_days=?, rewarded_at=? WHERE id=?", (days, iso_now(), ref["id"]))
    if days:
        grant_trial_days(conn, ref["referrer_business_id"], days)


def pending_rewards(conn: sqlite3.Connection, business_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT b.name, r.referrer_bonus_days AS days FROM referrals r JOIN businesses b ON b.id=r.referred_business_id
           WHERE r.referrer_business_id=? AND r.status='rewarded' AND r.reward_seen=0 AND r.referrer_bonus_days>0
           ORDER BY r.rewarded_at""",
        (business_id,),
    ).fetchall()
    return [{"name": r["name"], "days": r["days"]} for r in rows]


def referral_summary(conn: sqlite3.Connection, business_id: str) -> dict[str, Any]:
    rows = conn.execute(
        """SELECT r.status, r.referrer_bonus_days AS days, r.created_at, r.rewarded_at, r.referred_business_id AS rid, b.name
           FROM referrals r JOIN businesses b ON b.id=r.referred_business_id
           WHERE r.referrer_business_id=? ORDER BY r.created_at DESC LIMIT 200""",
        (business_id,),
    ).fetchall()
    rewarded = [r for r in rows if r["status"] == "rewarded"]
    earned_days = sum(r["days"] for r in rewarded)
    rewarded_count = rewards_earned_by(conn, business_id)
    slots_left = max(0, MAX_REWARDED_REFERRALS - rewarded_count)
    next_needed = referral_sales_needed(rewarded_count) if slots_left else None
    items = []
    for r in rows:
        item = {"name": r["name"], "status": r["status"], "days": r["days"], "joined_at": r["created_at"], "rewarded_at": r["rewarded_at"]}
        if r["status"] == "joined":
            item["sales"] = completed_sales(conn, r["rid"])
            item["needed"] = next_needed          # None once the reward limit is reached
        items.append(item)
    by = conn.execute(
        """SELECT b.name, r.referred_bonus_days AS days FROM referrals r JOIN businesses b ON b.id=r.referrer_business_id
           WHERE r.referred_business_id=?""",
        (business_id,),
    ).fetchone()
    return {
        "items": items,
        "stats": {"joined": len(rows), "rewarded": len(rewarded), "rewards": rewarded_count, "days_earned": earned_days,
                  "slots_left": slots_left, "next_needed": next_needed},
        "referred_by": {"name": by["name"], "bonus_days": by["days"]} if by else None,
        "rules": {"referred_bonus_days": REFERRED_BONUS_DAYS, "referrer_bonus_days": REFERRER_BONUS_DAYS,
                  "max_rewards": MAX_REWARDED_REFERRALS, "sales_required": list(REFERRAL_SALES_REQUIRED)},
    }


# --------------------------------------------------------------------------------------
# Edit history: every change to money, stock, customers and settings is written to an append-only,
# hash-chained log. SQLite triggers refuse edits and deletions, and each entry carries the hash of the
# one before it, so a change made behind the app's back is detected the next time the history is opened.
# --------------------------------------------------------------------------------------
AUDIT_TYPE_LABELS = {
    "order": "Order", "payment": "Payment", "debt": "Debt", "product": "Product", "customer": "Customer",
    "business": "Settings", "category": "Category", "account": "Account", "plan": "Plan", "expense": "Expense",
}
AUDIT_ACTION_LABELS = {
    "create": "Added", "update": "Edited", "delete": "Deleted", "adjust": "Corrected", "void": "Voided", "status": "Status changed",
    "security": "Security", "grant": "Plan changed", "terms": "Terms accepted",
}


def _parse_dt(value: Any) -> dt.datetime | None:
    """A stored ISO timestamp as an aware datetime (naive values are taken as UTC), or None."""
    s = str(value or "").strip()
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def naira_text(kobo: Any) -> str:
    return f"₦{int(kobo or 0) / 100:,.2f}"


_WORDS_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen").split()
_WORDS_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")


def _words_below_1000(n: int) -> str:
    parts: list[str] = []
    if n >= 100:
        parts.append(_WORDS_ONES[n // 100] + " hundred")
        n %= 100
        if n:
            parts.append("and")
    if n >= 20:
        parts.append(_WORDS_TENS[n // 10] + (("-" + _WORDS_ONES[n % 10]) if n % 10 else ""))
    elif n or not parts:
        parts.append(_WORDS_ONES[n])
    return " ".join(parts)


def _words_int(n: int) -> str:
    if n == 0:
        return "zero"
    parts: list[str] = []
    for size, name in ((10 ** 12, "trillion"), (10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")):
        if n >= size:
            parts.append(_words_below_1000(n // size) + " " + name)
            n %= size
    if n:
        parts.append(("and " if parts and n < 100 else "") + _words_below_1000(n))
    return " ".join(parts)


def naira_words(kobo: Any) -> str:
    """12050 (kobo) -> 'One hundred and twenty naira, fifty kobo only'."""
    k = abs(int(kobo or 0))
    naira, rest = divmod(k, 100)
    text = _words_int(naira) + " naira"
    if rest:
        text += ", " + _words_int(rest) + " kobo"
    text += " only"
    return text[0].upper() + text[1:]


def audit_change(key: str, label: str, old: Any, new: Any, kind: str = "text") -> dict[str, Any]:
    """One field of a change. kind: money (kobo), num, text, bool, date, list."""
    return {"key": key, "label": label, "kind": kind, "from": old, "to": new}


def _audit_norm(kind: str, v: Any) -> Any:
    if kind == "bool":
        return bool(v) and str(v).lower() not in ("0", "false", "no", "off")
    if kind in ("money", "num"):
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0
    if kind == "list":
        return list(v or [])
    return str(v if v is not None else "").strip()


def audit_diff(old: Any, new: Any, spec: list[tuple[str, str, str]]) -> list[dict[str, Any]]:
    """Compare two records over (key, label, kind) fields and return only what changed."""
    out: list[dict[str, Any]] = []
    for key, label, kind in spec:
        try:
            a = old[key] if old is not None else None
        except (KeyError, IndexError):
            a = None
        try:
            b = new[key]
        except (KeyError, IndexError):
            continue
        a, b = _audit_norm(kind, a), _audit_norm(kind, b)
        if a != b:
            out.append(audit_change(key, label, a, b, kind))
    return out


def _audit_actor(user: Any) -> tuple[str, str]:
    if not user:
        return "", "Server operator"
    try:
        uid = str(user["id"])
    except (KeyError, IndexError, TypeError):
        uid = ""
    name = ""
    for k in ("owner_name", "email"):
        try:
            name = str(user[k] or "").strip()
        except (KeyError, IndexError, TypeError):
            name = ""
        if name:
            break
    return uid, name or "Owner"


def _audit_digest(prev: str, fields: list[Any]) -> str:
    blob = json.dumps(fields, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256((prev + "\n" + blob).encode("utf-8")).hexdigest()


def _audit_fields(r: Any) -> list[Any]:
    return [r["id"], r["business_id"], r["user_id"], r["actor"], r["entity_type"], r["entity_id"], r["entity_label"], r["ref_id"],
            r["action"], r["summary"], r["changes"], r["reason"], r["ip"], r["created_at"]]


def audit(conn: sqlite3.Connection, business_id: str, user: Any, entity_type: str, entity_id: str, entity_label: str, action: str,
          summary: str, changes: list[dict[str, Any]] | None = None, reason: str = "", ref_id: str = "", ip: str = "") -> None:
    """Append one entry to the edit history. Call it inside the same transaction as the change it describes."""
    uid, actor = _audit_actor(user)
    entry = {
        "id": new_id("aud_"), "business_id": business_id, "user_id": uid, "actor": actor[:120], "entity_type": entity_type,
        "entity_id": str(entity_id or ""), "entity_label": str(entity_label or "")[:200], "ref_id": str(ref_id or "")[:200], "action": action,
        "summary": str(summary or "")[:400], "changes": json.dumps(changes or [], ensure_ascii=True, separators=(",", ":")),
        "reason": str(reason or "").strip()[:400], "ip": str(ip or "")[:64], "created_at": iso_now(),
    }
    with DB_LOCK:
        last = conn.execute("SELECT entry_hash FROM audit_log WHERE business_id=? ORDER BY seq DESC LIMIT 1", (business_id,)).fetchone()
        prev = last["entry_hash"] if last else ""
        digest = _audit_digest(prev, _audit_fields(entry))
        cur = conn.execute(
            """INSERT INTO audit_log(id,business_id,user_id,actor,entity_type,entity_id,entity_label,ref_id,action,summary,changes,reason,ip,created_at,prev_hash,entry_hash)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (entry["id"], business_id, uid, entry["actor"], entity_type, entry["entity_id"], entry["entity_label"], entry["ref_id"], action,
             entry["summary"], entry["changes"], entry["reason"], entry["ip"], entry["created_at"], prev, digest),
        )
        # remember where the chain ends, so cutting entries off the end is noticed too
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (f"audit_head:{business_id}", f"{cur.lastrowid}:{digest}"))


def audit_verify(conn: sqlite3.Connection, business_id: str) -> dict[str, Any]:
    """Re-check the whole chain. {'ok', 'checked', 'broken_at'}."""
    prev, checked, last_seq, last_hash, last_when = "", 0, 0, "", ""
    for r in conn.execute("SELECT * FROM audit_log WHERE business_id=? ORDER BY seq", (business_id,)):
        if r["prev_hash"] != prev or r["entry_hash"] != _audit_digest(prev, _audit_fields(r)):
            return {"ok": False, "checked": checked, "broken_at": r["created_at"]}
        prev, checked, last_seq, last_hash, last_when = r["entry_hash"], checked + 1, r["seq"], r["entry_hash"], r["created_at"]
    head = conn.execute("SELECT value FROM meta WHERE key=?", (f"audit_head:{business_id}",)).fetchone()
    if head:
        want_seq, _, want_hash = str(head["value"]).partition(":")
        if want_hash != last_hash or str(want_seq) != str(last_seq):
            return {"ok": False, "checked": checked, "broken_at": last_when or iso_now()}
    return {"ok": True, "checked": checked, "broken_at": None}


def audit_item(r: sqlite3.Row) -> dict[str, Any]:
    try:
        changes = json.loads(r["changes"] or "[]")
    except ValueError:
        changes = []
    return {
        "id": r["id"], "seq": r["seq"], "type": r["entity_type"], "type_label": AUDIT_TYPE_LABELS.get(r["entity_type"], r["entity_type"].title()),
        "action": r["action"], "action_label": AUDIT_ACTION_LABELS.get(r["action"], r["action"].title()),
        "entity_id": r["entity_id"], "ref_id": r["ref_id"], "label": r["entity_label"], "summary": r["summary"], "changes": changes,
        "reason": r["reason"], "actor": r["actor"], "created_at": r["created_at"],
    }


def _lagos_day_start_utc(day: dt.date) -> str:
    return dt.datetime(day.year, day.month, day.day, tzinfo=LAGOS).astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def audit_filters(bid: str, qs: dict[str, list[str]], window_days: int | None) -> tuple[str, list[Any], str, list[Any]]:
    """(where, args, type_where, type_args): the filter without the type chips, and the type chips on their own."""
    where, args = "business_id=?", [bid]
    search = (qs.get("search", [""])[0] or "").strip().lower()[:80]
    if search:
        like = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where += " AND lower(summary||' '||entity_label||' '||reason||' '||actor||' '||changes) LIKE ? ESCAPE '\\'"
        args.append(like)
    ent = (qs.get("entity_id", [""])[0] or "").strip()[:120]
    if ent:
        where += " AND (entity_id=? OR instr(' '||ref_id||' ', ' '||?||' ')>0)"
        args += [ent, ent]
    start, end = (qs.get("start", [""])[0] or "").strip(), (qs.get("end", [""])[0] or "").strip()
    if start:
        where += " AND created_at>=?"
        args.append(_lagos_day_start_utc(parse_date(start, dt.date.today())))
    if end:
        where += " AND created_at<?"
        args.append(_lagos_day_start_utc(parse_date(end, dt.date.today()) + dt.timedelta(days=1)))
    if window_days:
        where += " AND created_at>=?"
        args.append((utcnow() - dt.timedelta(days=window_days)).isoformat(timespec="seconds"))
    types = [t for t in re.split(r"[,\s]+", (qs.get("type", [""])[0] or "").lower()) if t in AUDIT_TYPE_LABELS]
    tw, ta = "", []
    if types:
        tw = " AND entity_type IN (" + ",".join("?" * len(types)) + ")"
        ta = list(types)
    return where, args, tw, ta


# --------------------------------------------------------------------------------------
# Plans: free trial, free plan, Oja Loom Pro (N1,000 for 30 days)
# --------------------------------------------------------------------------------------
def plan_state(biz: Any) -> dict[str, Any]:
    """What this shop may use right now. 'pro' is True when Pro features are open (paid, trial, or the paywall is off)."""
    def col(name: str) -> Any:
        try:
            return biz[name]
        except (KeyError, IndexError):
            return None
    now = utcnow()
    pro_until, trial_end = _parse_dt(col("pro_until")), _parse_dt(col("trial_end"))
    if pro_until and pro_until > now:
        state, ends = "pro", pro_until
    elif trial_end and trial_end > now:
        state, ends = "trial", trial_end
    else:
        state, ends = "free", None
    days_left = None
    if ends:
        days_left = max(0, -(-int((ends - now).total_seconds()) // 86400))
    return {
        "state": state, "pro": state != "free" or not PAYWALL_ENFORCED, "enforced": PAYWALL_ENFORCED,
        "price": PRO_PRICE_NAIRA, "period_days": PRO_PERIOD_DAYS, "days_left": days_left, "ends_at": ends.isoformat(timespec="seconds") if ends else None,
        "features": {k: {"name": n, "pitch": p} for k, (n, p) in PRO_FEATURES.items()},
        "limits": {"products": FREE_MAX_PRODUCTS, "orders_per_month": FREE_MAX_ORDERS_PER_MONTH, "activity_days": FREE_ACTIVITY_DAYS, "report_days": FREE_REPORT_DAYS},
    }


def pro_gate(biz: Any, feature: str) -> None:
    """Refuse (HTTP 402) when the shop is on the free plan and the paywall is on."""
    if plan_state(biz)["pro"]:
        return
    name = PRO_FEATURES.get(feature, ("This feature", ""))[0]
    raise AppError(f"{name}: included with Oja Loom Pro (₦{PRO_PRICE_NAIRA:,} a month).", 402, {"upgrade": feature})


def grant_pro(conn: sqlite3.Connection, business_id: str, days: int) -> str:
    """Add Pro days on top of any Pro time the shop still has. Returns the new end date (ISO)."""
    row = conn.execute("SELECT pro_until FROM businesses WHERE id=?", (business_id,)).fetchone()
    now = utcnow()
    base = max(_parse_dt(row["pro_until"]) or now, now) if row else now
    until = (base + dt.timedelta(days=int(days))).isoformat(timespec="seconds")
    conn.execute("UPDATE businesses SET pro_until=?, plan='pro', updated_at=? WHERE id=?", (until, iso_now(), business_id))
    return until

# --------------------------------------------------------------------------------------
# Billing: activation codes (sell them by transfer / WhatsApp) and optional Paystack checkout
# --------------------------------------------------------------------------------------
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def make_billing_codes(conn: sqlite3.Connection, n: int, days: int, note: str = "") -> list[str]:
    out: list[str] = []
    for _ in range(n):
        code = "OJA-" + "-".join("".join(secrets.choice(CODE_ALPHABET) for _ in range(4)) for _ in range(3))
        conn.execute("INSERT INTO billing_codes(code,days,note,created_at) VALUES(?,?,?,?)", (code, days, note[:120], iso_now()))
        out.append(code)
    return out


def redeem_billing_code(conn: sqlite3.Connection, business_id: str, user: Any, raw: Any) -> tuple[int, str]:
    code = re.sub(r"[^A-Za-z0-9]", "", str(raw or "")).upper()
    if len(code) == 15 and code.startswith("OJA"):
        code = code[3:]
    if len(code) != 12:
        raise ValueError("That code does not look right. It looks like OJA-ABCD-EFGH-JKMN.")
    pretty = "OJA-" + "-".join(code[i:i + 4] for i in (0, 4, 8))
    row = conn.execute("SELECT * FROM billing_codes WHERE code=?", (pretty,)).fetchone()
    if not row or row["redeemed_at"]:
        raise ValueError("That code is not valid, or it has already been used.")
    cur = conn.execute("UPDATE billing_codes SET redeemed_by=?, redeemed_at=? WHERE code=? AND redeemed_at IS NULL", (business_id, iso_now(), pretty))
    if cur.rowcount != 1:
        raise ValueError("That code is not valid, or it has already been used.")
    until = grant_pro(conn, business_id, row["days"])
    conn.execute(
        "INSERT INTO billing_payments(id,business_id,provider,reference,amount,days,status,created_at,paid_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (new_id("bil_"), business_id, "code", pretty, PRO_PRICE_NAIRA * 100, row["days"], "paid", iso_now(), iso_now()),
    )
    audit(conn, business_id, user, "plan", business_id, "Oja Loom Pro", "grant", f"Oja Loom Pro activated for {row['days']} days with a code", [
        audit_change("pro_until", "Pro until", "", until[:10], "date")])
    return row["days"], until


def paystack_call(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not PAYSTACK_SECRET:
        raise AppError("Online payment is not set up on this server. Use an activation code instead.", 503)
    req = urllib.request.Request(
        PAYSTACK_BASE + path, method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": "Bearer " + PAYSTACK_SECRET, "Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        with contextlib.suppress(Exception):
            return json.loads(exc.read().decode("utf-8"))
        raise AppError("The payment provider refused that request.", 502)
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise AppError("Could not reach the payment provider. Please try again in a moment.", 502)


def paystack_finalize(reference: str) -> bool:
    """Confirm a Paystack payment with Paystack itself, then add the Pro days. Safe to call twice."""
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM billing_payments WHERE reference=? AND provider='paystack'", (reference,)).fetchone()
    if not row:
        return False
    if row["status"] == "paid":
        return True
    data = paystack_call("GET", "/transaction/verify/" + urllib.parse.quote(reference, safe="")).get("data") or {}
    if data.get("status") != "success" or int(data.get("amount") or 0) != row["amount"] or str(data.get("currency", "NGN")).upper() != "NGN":
        return False
    with DB_LOCK, db_connect() as conn, transaction(conn, True):
        cur = conn.execute("UPDATE billing_payments SET status='paid', paid_at=? WHERE reference=? AND status='pending'", (iso_now(), reference))
        if cur.rowcount == 1:
            until = grant_pro(conn, row["business_id"], row["days"])
            audit(conn, row["business_id"], None, "plan", row["business_id"], "Oja Loom Pro", "grant",
                  f"Oja Loom Pro paid online: {PRO_PERIOD_DAYS} days", [audit_change("pro_until", "Pro until", "", until[:10], "date")])
    return True


# --------------------------------------------------------------------------------------
# Report exports (PDF / CSV): same rule as the Reports page, completed orders in the date range
# --------------------------------------------------------------------------------------
MAX_EXPORT_ORDERS = 5000
MAX_PDF_ORDER_ROWS = 500


def report_export_data(conn: sqlite3.Connection, bid: str, start: dt.date, end: dt.date) -> dict[str, Any]:
    a, z = start.isoformat(), end.isoformat()
    kpi = conn.execute(
        "SELECT COALESCE(SUM(total),0) sales, COUNT(*) cnt, COALESCE(SUM(estimated_gross_profit),0) profit FROM orders "
        "WHERE business_id=? AND status='completed' AND substr(order_date,1,10) BETWEEN ? AND ?", (bid, a, z)).fetchone()
    best = conn.execute(
        """SELECT oi.product_name name, SUM(oi.quantity) quantity, SUM(oi.line_total) sales FROM order_items oi
           JOIN orders o ON o.id=oi.order_id WHERE oi.business_id=? AND o.status='completed' AND substr(o.order_date,1,10) BETWEEN ? AND ?
           GROUP BY oi.product_id, oi.product_name ORDER BY quantity DESC LIMIT 15""", (bid, a, z)).fetchall()
    top = conn.execute(
        """SELECT c.full_name name, COUNT(o.id) orders, SUM(o.total) spent FROM orders o JOIN customers c ON c.id=o.customer_id
           WHERE o.business_id=? AND o.status='completed' AND substr(o.order_date,1,10) BETWEEN ? AND ?
           GROUP BY c.id, c.full_name ORDER BY spent DESC LIMIT 15""", (bid, a, z)).fetchall()
    debt = conn.execute("SELECT COALESCE(SUM(remaining_balance),0) FROM debts WHERE business_id=? AND status<>'paid'", (bid,)).fetchone()[0]
    orders = conn.execute(
        """SELECT o.order_number, substr(o.order_date,1,10) AS order_date, COALESCE(c.full_name,'Walk-in customer') AS customer,
                  o.subtotal, o.discount, o.total, o.amount_paid, o.balance, o.payment_method, o.estimated_gross_profit AS profit,
                  (SELECT GROUP_CONCAT(oi.product_name || ' x' || oi.quantity, '; ') FROM order_items oi WHERE oi.order_id=o.id) AS items
           FROM orders o LEFT JOIN customers c ON c.id=o.customer_id
           WHERE o.business_id=? AND o.status='completed' AND substr(o.order_date,1,10) BETWEEN ? AND ?
           ORDER BY o.order_date DESC, o.created_at DESC LIMIT ?""", (bid, a, z, MAX_EXPORT_ORDERS)).fetchall()
    cnt = kpi["cnt"]
    exp_total = expense_total(conn, bid, a, z)
    by_day = {r["d"]: r["t"] for r in conn.execute(
        "SELECT substr(order_date,1,10) d, SUM(total) t FROM orders WHERE business_id=? AND status='completed' AND substr(order_date,1,10) BETWEEN ? AND ? GROUP BY d",
        (bid, a, z))}
    daily = [((start + dt.timedelta(days=i)).isoformat(), by_day.get((start + dt.timedelta(days=i)).isoformat(), 0)) for i in range((end - start).days + 1)]
    return {
        "start": a, "end": z, "sales": kpi["sales"], "count": cnt, "profit": kpi["profit"], "daily": daily,
        "avg": int(kpi["sales"] / cnt) if cnt else 0, "debt": debt, "expenses": exp_total, "net": kpi["profit"] - exp_total,
        "best": [dict(r) for r in best], "top": [dict(r) for r in top], "orders": [dict(r) for r in orders], "orders_total": cnt,
    }


def _csv_text(value: Any) -> str:
    """Stop spreadsheet formula injection: a customer called '=HYPERLINK(...)' must stay plain text."""
    s = str(value if value is not None else "")
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def report_csv(data: dict[str, Any]) -> bytes:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(["Date", "Order number", "Customer", "Items", "Subtotal (NGN)", "Discount (NGN)", "Total (NGN)",
                "Amount paid (NGN)", "Balance (NGN)", "Payment method", "Estimated profit (NGN)"])
    money = lambda k: f"{(k or 0) / 100:.2f}"  # noqa: E731
    for o in data["orders"]:
        w.writerow([o["order_date"], _csv_text(o["order_number"]), _csv_text(o["customer"]), _csv_text(o["items"]), money(o["subtotal"]),
                    money(o["discount"]), money(o["total"]), money(o["amount_paid"]), money(o["balance"]), _csv_text(o["payment_method"]),
                    money(o["profit"])])
    return out.getvalue().encode("utf-8-sig")  # BOM so Excel shows accents correctly


_BIZ_FIELDS = (
    "id", "name", "slug", "owner_name", "phone", "email", "category", "description", "address", "currency", "plan",
    "subscription_status", "trial_start", "trial_end", "allow_negative_inventory", "receipt_message",
    "storefront_enabled", "pro_until", "created_at", "updated_at",
)
# Heavy columns (logo) are left out of everyday queries; has_logo says whether one exists.
BIZ_COLS = ",".join(_BIZ_FIELDS) + ",(logo_data<>'') AS has_logo"
BIZ_COLS_B = ",".join("b." + f for f in _BIZ_FIELDS) + ",(b.logo_data<>'') AS has_logo"
PRODUCT_COLS = (
    "id,business_id,name,description,(image_data<>'') AS has_image,selling_price,cost_price,stock_quantity,"
    "low_stock_threshold,category,sku,active,created_at,updated_at"
)


def init_db() -> None:
    existed = DATA_DIR.exists()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not existed:
        with contextlib.suppress(OSError):
            os.chmod(DATA_DIR, 0o700)
    with DB_LOCK, db_connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                owner_name TEXT NOT NULL DEFAULT '',
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS businesses (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE COLLATE NOCASE,
                owner_name TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL DEFAULT '',
                logo_data TEXT NOT NULL DEFAULT '',
                currency TEXT NOT NULL DEFAULT 'NGN',
                plan TEXT NOT NULL DEFAULT 'starter',
                subscription_status TEXT NOT NULL DEFAULT 'trialing',
                trial_start TEXT NOT NULL,
                trial_end TEXT NOT NULL,
                allow_negative_inventory INTEGER NOT NULL DEFAULT 0,
                receipt_message TEXT NOT NULL DEFAULT 'Thank you for your business.',
                storefront_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS business_members (
                business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL DEFAULT 'owner',
                created_at TEXT NOT NULL,
                PRIMARY KEY (business_id, user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_members_user ON business_members(user_id);

            CREATE TABLE IF NOT EXISTS product_categories (
                id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (business_id, name)
            );

            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                image_data TEXT NOT NULL DEFAULT '',
                selling_price INTEGER NOT NULL CHECK(selling_price >= 0),
                cost_price INTEGER NOT NULL CHECK(cost_price >= 0),
                stock_quantity INTEGER NOT NULL DEFAULT 0,
                low_stock_threshold INTEGER NOT NULL DEFAULT 5 CHECK(low_stock_threshold >= 0),
                category TEXT NOT NULL DEFAULT '',
                sku TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_products_business_name ON products(business_id, name);
            CREATE INDEX IF NOT EXISTS idx_products_business_stock ON products(business_id, stock_quantity);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_products_business_sku_unique ON products(business_id, sku) WHERE sku <> '';

            CREATE TABLE IF NOT EXISTS customers (
                id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
                full_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_customers_business_name ON customers(business_id, full_name);
            CREATE INDEX IF NOT EXISTS idx_customers_business_phone ON customers(business_id, phone);

            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
                customer_id TEXT REFERENCES customers(id) ON DELETE SET NULL,
                order_number TEXT NOT NULL,
                subtotal INTEGER NOT NULL DEFAULT 0,
                discount INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0,
                amount_paid INTEGER NOT NULL DEFAULT 0,
                balance INTEGER NOT NULL DEFAULT 0,
                estimated_gross_profit INTEGER NOT NULL DEFAULT 0,
                payment_method TEXT NOT NULL DEFAULT 'Bank Transfer',
                status TEXT NOT NULL DEFAULT 'pending',
                notes TEXT NOT NULL DEFAULT '',
                order_date TEXT NOT NULL,
                inventory_applied INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (business_id, order_number),
                CHECK (discount >= 0),
                CHECK (amount_paid >= 0),
                CHECK (status IN ('pending','confirmed','processing','ready','completed','cancelled'))
            );
            CREATE INDEX IF NOT EXISTS idx_orders_business_date ON orders(business_id, order_date DESC);
            CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(business_id, status);

            CREATE TABLE IF NOT EXISTS order_items (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
                product_id TEXT NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
                product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                unit_price INTEGER NOT NULL CHECK(unit_price >= 0),
                unit_cost INTEGER NOT NULL CHECK(unit_cost >= 0),
                line_total INTEGER NOT NULL CHECK(line_total >= 0),
                created_at TEXT NOT NULL,
                UNIQUE (order_id, product_id)
            );
            CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
            CREATE INDEX IF NOT EXISTS idx_order_items_product ON order_items(product_id);

            CREATE TABLE IF NOT EXISTS payments (
                id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
                order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                customer_id TEXT REFERENCES customers(id) ON DELETE SET NULL,
                amount INTEGER NOT NULL CHECK(amount > 0),
                payment_method TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                paid_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_payments_order ON payments(order_id, paid_at DESC);
            CREATE INDEX IF NOT EXISTS idx_payments_customer ON payments(customer_id, paid_at DESC);

            CREATE TABLE IF NOT EXISTS debts (
                id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
                order_id TEXT NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
                customer_id TEXT REFERENCES customers(id) ON DELETE SET NULL,
                original_amount INTEGER NOT NULL,
                amount_paid INTEGER NOT NULL,
                remaining_balance INTEGER NOT NULL,
                due_date TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (status IN ('outstanding','partially_paid','paid','overdue'))
            );
            CREATE INDEX IF NOT EXISTS idx_debts_business_status ON debts(business_id, status);

            CREATE TABLE IF NOT EXISTS receipts (
                id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
                order_id TEXT NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
                public_token TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                csrf_token TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

            CREATE TABLE IF NOT EXISTS subscriptions (
                id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL UNIQUE REFERENCES businesses(id) ON DELETE CASCADE,
                plan TEXT NOT NULL,
                status TEXT NOT NULL,
                trial_start TEXT NOT NULL,
                trial_end TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT '',
                provider_reference TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        # ---- migrations -------------------------------------------------------------
        user_cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        if "password_iter" not in user_cols:
            conn.execute(
                f"ALTER TABLE users ADD COLUMN password_iter INTEGER NOT NULL DEFAULT {LEGACY_PASSWORD_ITERATIONS}"
            )
        if "referral_code" not in {r["name"] for r in conn.execute("PRAGMA table_info(businesses)")}:
            conn.execute("ALTER TABLE businesses ADD COLUMN referral_code TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_businesses_referral_code ON businesses(referral_code) WHERE referral_code IS NOT NULL")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS referrals (
                id TEXT PRIMARY KEY,
                referrer_business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
                referred_business_id TEXT NOT NULL UNIQUE REFERENCES businesses(id) ON DELETE CASCADE,
                code TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'joined' CHECK(status IN ('joined','rewarded')),
                referred_bonus_days INTEGER NOT NULL DEFAULT 0,
                referrer_bonus_days INTEGER NOT NULL DEFAULT 0,
                rewarded_at TEXT,
                reward_seen INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_business_id, created_at)")
        for r in conn.execute("SELECT id FROM businesses WHERE referral_code IS NULL").fetchall():
            referral_code_for(conn, r["id"])
        if "adjustment" not in {r["name"] for r in conn.execute("PRAGMA table_info(orders)")}:
            conn.execute("ALTER TABLE orders ADD COLUMN adjustment INTEGER NOT NULL DEFAULT 0")
        if "pro_until" not in {r["name"] for r in conn.execute("PRAGMA table_info(businesses)")}:
            conn.execute("ALTER TABLE businesses ADD COLUMN pro_until TEXT")
        if "terms_version" not in {r["name"] for r in conn.execute("PRAGMA table_info(users)")}:
            conn.execute("ALTER TABLE users ADD COLUMN terms_version TEXT NOT NULL DEFAULT ''")
            conn.execute("ALTER TABLE users ADD COLUMN terms_accepted_at TEXT NOT NULL DEFAULT ''")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS audit_log (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT NOT NULL UNIQUE,
                business_id TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT '',
                actor TEXT NOT NULL DEFAULT '',
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL DEFAULT '',
                entity_label TEXT NOT NULL DEFAULT '',
                ref_id TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL,
                summary TEXT NOT NULL,
                changes TEXT NOT NULL DEFAULT '[]',
                reason TEXT NOT NULL DEFAULT '',
                ip TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                prev_hash TEXT NOT NULL DEFAULT '',
                entry_hash TEXT NOT NULL DEFAULT ''
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS expenses (
                id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
                amount INTEGER NOT NULL CHECK(amount > 0),
                category TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                vendor TEXT NOT NULL DEFAULT '',
                spent_on TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_expenses_business_date ON expenses(business_id, spent_on DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_business ON audit_log(business_id, seq DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(business_id, entity_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ref ON audit_log(business_id, ref_id)")
        # The history is append-only: the database itself refuses edits and deletions.
        conn.execute("CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log BEGIN SELECT RAISE(ABORT,'The edit history cannot be changed.'); END")
        conn.execute("CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log BEGIN SELECT RAISE(ABORT,'The edit history cannot be deleted.'); END")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS billing_codes (
                code TEXT PRIMARY KEY,
                days INTEGER NOT NULL DEFAULT 30,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                redeemed_by TEXT,
                redeemed_at TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS billing_payments (
                id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
                provider TEXT NOT NULL,
                reference TEXT NOT NULL UNIQUE,
                amount INTEGER NOT NULL,
                days INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                paid_at TEXT
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_billing_business ON billing_payments(business_id, paid_at)")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS outbound_messages (
                id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                doc TEXT NOT NULL,
                ref TEXT NOT NULL,
                to_phone TEXT NOT NULL,
                status TEXT NOT NULL,
                provider_id TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_outbound_business ON outbound_messages(business_id, to_phone, created_at)")
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version','6')")
    with contextlib.suppress(OSError):
        os.chmod(DB_PATH, 0o600)


def cleanup_sessions() -> None:
    with db_connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (iso_now(),))


def user_business(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row | None:
    return conn.execute(
        f"""
        SELECT {BIZ_COLS_B} FROM businesses b
        JOIN business_members bm ON bm.business_id=b.id
        WHERE bm.user_id=?
        ORDER BY CASE bm.role WHEN 'owner' THEN 0 ELSE 1 END, b.created_at
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()


def assert_member(conn: sqlite3.Connection, user_id: str, business_id: str) -> None:
    row = conn.execute(
        "SELECT 1 FROM business_members WHERE user_id=? AND business_id=?", (user_id, business_id)
    ).fetchone()
    if not row:
        raise PermissionError("You do not have access to this business.")


def next_order_number(conn: sqlite3.Connection, business_id: str) -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d")
    for _ in range(20):
        code = f"OJL-{stamp}-{secrets.randbelow(9000)+1000}"
        if not conn.execute(
            "SELECT 1 FROM orders WHERE business_id=? AND order_number=?", (business_id, code)
        ).fetchone():
            return code
    return f"OJL-{stamp}-{secrets.token_hex(4).upper()}"


def sync_order_financials(conn: sqlite3.Connection, order_id: str) -> sqlite3.Row:
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        raise ValueError("Order not found.")
    paid = conn.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE order_id=?", (order_id,)).fetchone()[0]
    balance = max(order["total"] - paid, 0)
    if paid > order["total"]:
        raise ValueError("Payments cannot exceed the order total.")
    conn.execute(
        "UPDATE orders SET amount_paid=?, balance=?, updated_at=? WHERE id=?",
        (paid, balance, iso_now(), order_id),
    )
    if order["status"] == "cancelled" or balance <= 0:
        debt = conn.execute("SELECT id FROM debts WHERE order_id=?", (order_id,)).fetchone()
        if debt:
            conn.execute(
                "UPDATE debts SET amount_paid=?, remaining_balance=0, status='paid', updated_at=? WHERE order_id=?",
                (paid, iso_now(), order_id),
            )
    else:
        existing = conn.execute("SELECT * FROM debts WHERE order_id=?", (order_id,)).fetchone()
        due = existing["due_date"] if existing else None
        status = "partially_paid" if paid > 0 else "outstanding"
        if due:
            try:
                if dt.date.fromisoformat(due) < dt.date.today():
                    status = "overdue"
            except ValueError:
                pass
        if existing:
            conn.execute(
                """
                UPDATE debts SET original_amount=?, amount_paid=?, remaining_balance=?, status=?, updated_at=?
                WHERE order_id=?
                """,
                (order["total"], paid, balance, status, iso_now(), order_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO debts(id,business_id,order_id,customer_id,original_amount,amount_paid,remaining_balance,due_date,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    new_id("debt_"), order["business_id"], order_id, order["customer_id"], order["total"], paid,
                    balance, None, status, iso_now(), iso_now()
                ),
            )
    return conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()


def set_debt_due_date(conn: sqlite3.Connection, order_id: str, due_date: str | None) -> None:
    due = (due_date or "").strip() or None
    if due:
        try:
            dt.date.fromisoformat(due)
        except ValueError:
            raise ValueError("Due date must be a valid date.")
    debt = conn.execute("SELECT * FROM debts WHERE order_id=?", (order_id,)).fetchone()
    if not debt:
        return
    if debt["remaining_balance"] <= 0:
        status = "paid"
    elif due and dt.date.fromisoformat(due) < dt.date.today():
        status = "overdue"
    elif debt["amount_paid"] > 0:
        status = "partially_paid"
    else:
        status = "outstanding"
    conn.execute("UPDATE debts SET due_date=?, status=?, updated_at=? WHERE order_id=?", (due, status, iso_now(), order_id))


def restore_inventory(conn: sqlite3.Connection, order_id: str) -> None:
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order or not order["inventory_applied"]:
        return
    items = conn.execute("SELECT product_id, quantity FROM order_items WHERE order_id=?", (order_id,)).fetchall()
    for item in items:
        conn.execute(
            "UPDATE products SET stock_quantity=stock_quantity+?, updated_at=? WHERE id=? AND business_id=?",
            (item["quantity"], iso_now(), item["product_id"], order["business_id"]),
        )
    conn.execute("UPDATE orders SET inventory_applied=0, updated_at=? WHERE id=?", (iso_now(), order_id))


def apply_inventory(conn: sqlite3.Connection, order_id: str) -> None:
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order or order["inventory_applied"]:
        return
    business = conn.execute("SELECT * FROM businesses WHERE id=?", (order["business_id"],)).fetchone()
    items = conn.execute("SELECT product_id, quantity, product_name FROM order_items WHERE order_id=?", (order_id,)).fetchall()
    for item in items:
        product = conn.execute(
            "SELECT * FROM products WHERE id=? AND business_id=?", (item["product_id"], order["business_id"])
        ).fetchone()
        if not product:
            raise ValueError(f"Product {item['product_name']} no longer exists.")
        if not business["allow_negative_inventory"] and product["stock_quantity"] < item["quantity"]:
            raise ValueError(
                f"Not enough stock for {item['product_name']}. Available: {product['stock_quantity']}."
            )
    for item in items:
        conn.execute(
            "UPDATE products SET stock_quantity=stock_quantity-?, updated_at=? WHERE id=? AND business_id=?",
            (item["quantity"], iso_now(), item["product_id"], order["business_id"]),
        )
    conn.execute("UPDATE orders SET inventory_applied=1, updated_at=? WHERE id=?", (iso_now(), order_id))


def create_receipt_if_missing(conn: sqlite3.Connection, order_id: str, business_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM receipts WHERE order_id=?", (order_id,)).fetchone()
    if row:
        return row
    rid = new_id("rcp_")
    token = secrets.token_urlsafe(24)
    conn.execute(
        "INSERT INTO receipts(id,business_id,order_id,public_token,created_at) VALUES(?,?,?,?,?)",
        (rid, business_id, order_id, token, iso_now()),
    )
    return conn.execute("SELECT * FROM receipts WHERE id=?", (rid,)).fetchone()


def parse_order_items(conn: sqlite3.Connection, business_id: str, raw_items: Any) -> tuple[list[dict[str, Any]], int, int]:
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("Add at least one product to the order.")
    seen: set[str] = set()
    parsed: list[dict[str, Any]] = []
    subtotal = 0
    gross = 0
    for raw in raw_items:
        product_id = str((raw or {}).get("product_id") or "")
        try:
            qty = int((raw or {}).get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
        if not product_id or qty <= 0 or qty > MAX_QTY:
            raise ValueError("Every order item needs a product and quantity greater than zero.")
        if product_id in seen:
            raise ValueError("The same product cannot appear twice in one order.")
        seen.add(product_id)
        product = conn.execute(
            "SELECT * FROM products WHERE id=? AND business_id=? AND active=1", (product_id, business_id)
        ).fetchone()
        if not product:
            raise ValueError("One selected product is missing or inactive.")
        line_total = product["selling_price"] * qty
        subtotal += line_total
        gross += (product["selling_price"] - product["cost_price"]) * qty
        parsed.append(
            {
                "product_id": product_id,
                "product_name": product["name"],
                "quantity": qty,
                "unit_price": product["selling_price"],
                "unit_cost": product["cost_price"],
                "line_total": line_total,
            }
        )
    return parsed, subtotal, gross


def row_to_product(row: sqlite3.Row) -> dict[str, Any]:
    stock = row["stock_quantity"]
    threshold = row["low_stock_threshold"]
    state = "out" if stock <= 0 else "low" if stock <= threshold else "in"
    has_image = bool(row["has_image"])
    return {
        "id": row["id"], "name": row["name"], "description": row["description"], "has_image": has_image,
        "image_url": f"/media/product/{row['id']}?v={urllib.parse.quote(row['updated_at'])}" if has_image else "",
        "selling_price": kobo_to_number(row["selling_price"]), "cost_price": kobo_to_number(row["cost_price"]),
        "profit_per_unit": kobo_to_number(row["selling_price"] - row["cost_price"]),
        "stock_quantity": row["stock_quantity"], "low_stock_threshold": row["low_stock_threshold"],
        "stock_state": state, "category": row["category"], "sku": row["sku"], "active": bool(row["active"]),
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def order_payload(conn: sqlite3.Connection, row: sqlite3.Row, include_items: bool = False) -> dict[str, Any]:
    customer = None
    if row["customer_id"]:
        customer = conn.execute("SELECT id,full_name,phone,email FROM customers WHERE id=?", (row["customer_id"],)).fetchone()
    result: dict[str, Any] = {
        "id": row["id"], "order_number": row["order_number"], "customer_id": row["customer_id"],
        "customer": dict(customer) if customer else None,
        "subtotal": kobo_to_number(row["subtotal"]), "discount": kobo_to_number(row["discount"]),
        "total": kobo_to_number(row["total"]), "amount_paid": kobo_to_number(row["amount_paid"]),
        "balance": kobo_to_number(row["balance"]), "adjustment": kobo_to_number(row["adjustment"]),
        "estimated_gross_profit": kobo_to_number(row["estimated_gross_profit"]),
        "payment_method": row["payment_method"], "status": row["status"], "notes": row["notes"],
        "order_date": row["order_date"], "inventory_applied": bool(row["inventory_applied"]),
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }
    if include_items:
        items = conn.execute("SELECT * FROM order_items WHERE order_id=? ORDER BY created_at", (row["id"],)).fetchall()
        result["items"] = [
            {
                "id": i["id"], "product_id": i["product_id"], "product_name": i["product_name"], "quantity": i["quantity"],
                "unit_price": kobo_to_number(i["unit_price"]), "unit_cost": kobo_to_number(i["unit_cost"]),
                "line_total": kobo_to_number(i["line_total"]),
            }
            for i in items
        ]
        payments = conn.execute("SELECT * FROM payments WHERE order_id=? ORDER BY paid_at DESC", (row["id"],)).fetchall()
        result["payments"] = [
            {
                "id": p["id"], "amount": kobo_to_number(p["amount"]), "payment_method": p["payment_method"],
                "note": p["note"], "paid_at": p["paid_at"],
            }
            for p in payments
        ]
        receipt = conn.execute("SELECT * FROM receipts WHERE order_id=?", (row["id"],)).fetchone()
        result["receipt"] = dict(receipt) if receipt else None
        debt = conn.execute("SELECT id,due_date,status,remaining_balance FROM debts WHERE order_id=?", (row["id"],)).fetchone()
        result["debt"] = dict(debt) if debt else None
    return result


def order_item_lines(items: Iterable[Any]) -> list[str]:
    """Readable one-line summaries of order items for the edit history."""
    return [f"{i['quantity']} \u00d7 {i['product_name']} @ {naira_text(i['unit_price'])}" for i in items]


STORE_CSS = r"""
:root{--bg:#f4f5f9;--surface:#fff;--line:#e6e8f0;--ink:#0f1430;--muted:#656d8a;--brand:#2c3a9c;--brand-ink:#fff;--soft:#e9ecfb;--gold:#f2b01e;--ok:#157a4b;--ok-soft:#e3f5ec;--bad:#c0352b;--bad-soft:#fdeceb}
@media(prefers-color-scheme:dark){:root{--bg:#0c1030;--surface:#131942;--line:#242c5e;--ink:#eceffd;--muted:#98a0cf;--brand:#8d9bff;--brand-ink:#0c1030;--soft:#1e2760;--ok:#5fd39a;--ok-soft:#10382b;--bad:#ff8a80;--bad-soft:#3d1a1d}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;-webkit-font-smoothing:antialiased}
.hero{background:#161e4d;background-image:radial-gradient(circle at 1px 1px,rgba(255,255,255,.07) 1px,transparent 0);background-size:18px 18px;color:#fff}
.hero-in{max-width:1040px;margin:auto;padding:42px 20px 36px;display:flex;gap:18px;align-items:center}
.logo{width:72px;height:72px;border-radius:20px;object-fit:cover;background:rgba(255,255,255,.12);flex:none;display:grid;place-items:center;font-size:30px;font-weight:800;color:var(--gold)}
h1{margin:0;font-size:clamp(24px,4vw,34px);letter-spacing:-.03em;line-height:1.1}
.sub{color:#c8cdf0;margin-top:8px;max-width:62ch}
.contact{color:#aab2e6;font-size:14px;margin-top:8px}
.wrap{max-width:1040px;margin:auto;padding:22px 20px 56px}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px}
.chip{padding:8px 14px;border-radius:999px;border:1px solid var(--line);background:var(--surface);color:var(--ink);text-decoration:none;font-weight:600;font-size:14px}
.chip:hover{border-color:var(--brand)}
.chip[aria-current=true]{background:var(--brand);border-color:var(--brand);color:var(--brand-ink)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:16px}
.item{background:var(--surface);border:1px solid var(--line);border-radius:16px;overflow:hidden;display:flex;flex-direction:column}
.pic{aspect-ratio:1/1;width:100%;object-fit:cover;background:var(--soft);display:block}
.ph{aspect-ratio:1/1;display:grid;place-items:center;background:var(--soft);color:var(--brand);font-size:36px;font-weight:800}
.body{padding:14px;display:flex;flex-direction:column;gap:6px;flex:1}
.cat{font-size:12.5px;color:var(--muted)}
.name{font-weight:700;line-height:1.25}
.desc{font-size:14px;color:var(--muted);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.foot{margin-top:auto;padding-top:8px;display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}
.price{font-weight:800;font-size:18px;letter-spacing:-.02em}
.tag{font-size:12.5px;font-weight:600;padding:3px 9px;border-radius:999px;background:var(--ok-soft);color:var(--ok)}
.tag.out{background:var(--bad-soft);color:var(--bad)}
.btn{display:block;text-align:center;background:var(--brand);color:var(--brand-ink);text-decoration:none;font-weight:700;padding:11px 14px;border-radius:11px;margin:0 14px 14px}
.btn:hover{filter:brightness(1.08)}
.empty{grid-column:1/-1;text-align:center;padding:60px 20px;color:var(--muted)}
.powered{text-align:center;color:var(--muted);font-size:13px;margin-top:34px}
.ownerbar{position:sticky;top:0;z-index:20;background:#0b0f2b;color:#e6e9ff;display:flex;gap:12px;align-items:center;justify-content:space-between;padding:10px 16px;font-size:14px}
.ownerbar a{color:#fff;font-weight:700;text-decoration:none;background:rgba(255,255,255,.14);padding:8px 13px;border-radius:9px;white-space:nowrap}
.ownerbar a:hover{background:rgba(255,255,255,.24)}
.ownerbar span{opacity:.85}
a:focus-visible{outline:3px solid var(--gold);outline-offset:2px}
@media(max-width:560px){.hero-in{padding:28px 16px 24px}.logo{width:56px;height:56px;border-radius:16px;font-size:24px}.grid{grid-template-columns:repeat(2,1fr);gap:12px}.wrap{padding:18px 14px 44px}.body{padding:12px}.btn{margin:0 12px 12px;padding:10px 8px;font-size:14px}}
"""

RECEIPT_CSS = r"""
:root{--bg:#eceef7;--ink:#0f1430;--muted:#656d8a;--line:#e3e6ef;--soft:#f1f3fb;--brand:#2c3a9c;--dark:#18206b;--gold:#f2b01e;--ok:#157a4b;--ok-bg:#e3f5ec;--warn:#a85a00;--warn-bg:#fff1dc;--bad:#c0352b;--bad-bg:#fdeceb}
@media(prefers-color-scheme:dark){:root{--bg:#0c1030}}
*{box-sizing:border-box;-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;-webkit-font-smoothing:antialiased}
.bar{max-width:820px;margin:18px auto 0;padding:0 16px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.bar .grow{flex:1}
.btn{border:1px solid #d5d9e6;background:#fff;color:var(--ink);padding:10px 14px;border-radius:10px;text-decoration:none;font:inherit;font-weight:650;cursor:pointer;display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
.btn:hover{border-color:var(--brand)}
.btn.primary{background:var(--brand);border-color:var(--brand);color:#fff}
.btn.lock{border-style:dashed;color:var(--muted)}
.btn[disabled]{opacity:.6;cursor:progress}
.wanote{max-width:760px;margin:10px auto 0;padding:10px 14px;border-radius:10px;background:var(--ok-bg);color:var(--ok);font-size:14px;font-weight:600}
.wanote[hidden]{display:none}
.btn.back{background:transparent;border-color:transparent;color:var(--ink);padding-left:4px}
@media(prefers-color-scheme:dark){.btn.back{color:#eceffd}}
.menu{position:relative}
.menu summary{list-style:none}.menu summary::-webkit-details-marker{display:none}
.menu .pop{position:absolute;right:0;top:calc(100% + 6px);min-width:230px;background:#fff;border:1px solid var(--line);border-radius:12px;box-shadow:0 18px 40px -16px rgba(15,20,48,.4);padding:6px;z-index:5}
.menu .pop a,.menu .pop button{display:block;width:100%;text-align:left;border:0;background:transparent;font:inherit;cursor:pointer;padding:9px 12px;border-radius:8px;color:var(--ink);text-decoration:none;font-weight:650}
.menu .pop a:hover,.menu .pop button:hover{background:var(--soft)}
.menu .pop small{display:block;color:var(--muted);font-weight:400;font-size:12.5px}
.slip{max-width:820px;margin:14px auto 44px;background:#fff;color:var(--ink);border-radius:16px;overflow:hidden;box-shadow:0 24px 60px -24px rgba(15,20,48,.45);position:relative}
.slip[data-mark]::before{content:attr(data-mark);position:absolute;left:50%;top:52%;transform:translate(-50%,-50%) rotate(-30deg);font-size:clamp(64px,17vw,150px);font-weight:900;letter-spacing:.04em;color:var(--mark);opacity:.07;pointer-events:none;white-space:nowrap}
.band{background:linear-gradient(135deg,var(--dark),var(--brand));color:#fff;padding:26px 32px;display:flex;justify-content:space-between;gap:20px;border-bottom:3px solid var(--gold)}
.who{display:flex;gap:14px;align-items:center;min-width:0}
.tile{width:54px;height:54px;border-radius:12px;background:#fff;display:grid;place-items:center;flex:none;overflow:hidden;font-weight:800;font-size:24px;color:var(--brand)}
.tile img{width:100%;height:100%;object-fit:contain;padding:4px}
h1{margin:0 0 3px;font-size:21px;letter-spacing:-.02em;line-height:1.15;overflow-wrap:anywhere}
.band .sub{opacity:.78;font-size:13px}
.kind{text-align:right;flex:none}
.kind .lbl{color:var(--gold);font-weight:800;letter-spacing:.16em;font-size:12px;text-transform:uppercase}
.kind .no{font-size:19px;font-weight:800;margin-top:2px}
.kind .dt{opacity:.8;font-size:13px}
.body{padding:26px 32px 30px;position:relative}
.meta{display:flex;justify-content:space-between;gap:24px;flex-wrap:wrap}
.cap{font-size:11px;font-weight:800;letter-spacing:.12em;color:var(--muted);text-transform:uppercase}
.who2 strong{font-size:17px;display:block;margin:2px 0}
.muted{color:var(--muted)}
.facts{min-width:250px}
.facts div{display:flex;justify-content:space-between;gap:20px;padding:2px 0}
.facts .pillrow{justify-content:flex-end;margin-top:8px}
.pill{display:inline-block;padding:4px 12px;border-radius:999px;font-weight:800;font-size:11px;letter-spacing:.07em;text-transform:uppercase}
.pill.ok{background:var(--ok-bg);color:var(--ok)}.pill.warn{background:var(--warn-bg);color:var(--warn)}.pill.bad{background:var(--bad-bg);color:var(--bad)}
.scroll{overflow-x:auto;margin-top:22px}
table{width:100%;border-collapse:collapse}
th{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);font-weight:800;text-align:left;padding:9px 10px;background:var(--soft)}
th:first-child{border-radius:8px 0 0 8px}th:last-child{border-radius:0 8px 8px 0}
td{padding:11px 10px;vertical-align:top}
tbody tr:nth-child(even) td{background:#f8f9fd}
tbody tr+tr td{border-top:0}
.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.idx{color:var(--muted);width:30px}
.sums{display:flex;justify-content:space-between;gap:28px;margin-top:24px;flex-wrap:wrap;align-items:flex-start}
.qrbox{display:flex;gap:14px;align-items:flex-start;max-width:370px}
.qrbox a{flex:none;display:block;border:1px solid var(--line);border-radius:10px;padding:6px;background:#fff;line-height:0}
.qr{width:92px;height:92px}
.qrbox p{margin:3px 0 0;font-size:13px;color:var(--muted)}
.words{margin-top:14px;max-width:370px}
.words em{display:block;margin-top:2px}
.totals{width:min(100%,300px);margin-left:auto}
.totals div{display:flex;justify-content:space-between;gap:16px;padding:4px 0;font-variant-numeric:tabular-nums}
.totals .grand{border-top:2px solid var(--ink);margin-top:8px;padding-top:12px;font-size:20px;font-weight:800}
.totals .paid span:last-child{color:var(--ok)}
.balbox{margin-top:12px;border-radius:12px;padding:12px 14px;display:flex!important;justify-content:space-between;align-items:center;font-weight:800}
.balbox.warn{background:var(--warn-bg);color:var(--warn)}.balbox.ok{background:var(--ok-bg);color:var(--ok)}.balbox.bad{background:var(--bad-bg);color:var(--bad)}
.balbox b{font-size:19px}
h2{font-size:15px;margin:28px 0 0;display:flex;align-items:center;gap:8px}
h2::before{content:"";width:3px;height:15px;border-radius:2px;background:var(--brand)}
.notes{margin:10px 0 0;white-space:pre-wrap}
.thanks{margin-top:26px;background:var(--soft);border-left:3px solid var(--gold);border-radius:10px;padding:14px 18px;font-style:italic}
.foot{margin-top:18px;text-align:center;color:var(--muted);font-size:12.5px}
.foot a{color:inherit}
.btn:focus-visible,a:focus-visible{outline:3px solid var(--gold);outline-offset:2px}
@media(max-width:600px){.band{padding:20px 18px;flex-direction:column;gap:16px}.kind{text-align:left}.body{padding:20px 16px 24px}.facts{min-width:0;width:100%}.totals{width:100%}.qrbox{max-width:none}}
@media print{body{background:#fff}.bar{display:none}.slip{box-shadow:none;margin:0;max-width:none;border-radius:0}}
"""


# --------------------------------------------------------------------------------------
# Receipt PDF: a small pure-Python PDF writer that mirrors the receipt web page
# (standard Helvetica fonts, vector shapes, JPEG/PNG logo support, hand-drawn Naira sign)
# --------------------------------------------------------------------------------------
NAIRA = "\u20a6"
PDF_W, PDF_H = 595.28, 841.89  # A4 in points

# Helvetica / Helvetica-Bold advance widths (1/1000 em) for Windows-1252 codes 32..255
_HELV_W = (
    278,278,355,556,556,889,667,191,333,333,389,584,278,333,278,278,
    556,556,556,556,556,556,556,556,556,556,278,278,584,584,584,556,
    1015,667,667,722,722,667,611,778,722,278,500,667,556,833,722,778,
    667,778,722,667,611,722,667,944,667,667,611,278,278,278,469,556,
    333,556,556,500,556,556,278,556,556,222,222,500,222,833,556,556,
    556,556,333,500,278,556,500,722,500,500,500,334,260,334,584,556,
    556,556,222,556,333,1000,556,556,333,1000,667,333,1000,556,611,556,
    556,222,222,333,333,350,556,1000,333,1000,500,333,944,556,500,667,
    278,333,556,556,556,556,260,556,333,737,370,556,584,333,737,333,
    400,584,333,333,333,556,537,278,333,333,365,556,834,834,834,611,
    667,667,667,667,667,667,1000,722,667,667,667,667,278,278,278,278,
    722,722,778,778,778,778,778,584,778,722,722,722,722,667,667,611,
    556,556,556,556,556,556,889,500,556,556,556,556,222,222,222,222,
    556,556,556,556,556,556,556,584,611,556,556,556,556,500,556,500,
)
_HELV_BOLD_W = (
    278,333,474,556,556,889,722,238,333,333,389,584,278,333,278,278,
    556,556,556,556,556,556,556,556,556,556,333,333,584,584,584,611,
    975,722,722,722,722,667,611,778,722,278,556,722,611,833,722,778,
    667,778,722,667,611,722,667,944,667,667,611,333,278,333,584,556,
    333,556,611,556,611,556,333,611,611,278,278,556,278,889,611,611,
    611,611,389,556,333,611,556,778,556,556,500,389,280,389,584,556,
    556,556,278,556,500,1000,556,556,333,1000,667,333,1000,556,611,556,
    556,278,278,500,500,350,556,1000,333,1000,556,333,944,556,500,667,
    278,333,556,556,556,556,280,556,333,737,370,556,584,333,737,333,
    400,584,333,333,333,611,556,278,333,333,365,556,834,834,834,611,
    722,722,722,722,722,722,1000,722,667,667,667,667,278,278,278,278,
    722,722,778,778,778,778,778,584,778,722,722,722,722,667,667,611,
    556,556,556,556,556,556,889,556,556,556,556,556,278,278,278,278,
    611,611,611,611,611,611,611,584,611,611,611,611,611,556,611,556,
)


def pdf_safe(text: Any) -> str:
    """Make text printable with the built-in WinAnsi fonts (accents are kept, others fall back to base letters)."""
    out: list[str] = []
    for ch in str(text or ""):
        if ch == NAIRA:
            out.append(ch)
            continue
        if ch in "\r\n\t":
            out.append(" ")
            continue
        if ch == "\u2212":
            out.append("\u2013")
            continue
        if ord(ch) < 32:
            continue
        try:
            ch.encode("cp1252")
            out.append(ch)
            continue
        except UnicodeEncodeError:
            pass
        base = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c))
        try:
            base.encode("cp1252")
            out.append(base)
        except UnicodeEncodeError:
            out.append("?")
    return "".join(out)


def pdf_char_w(ch: str, bold: bool = False, style: str | None = None) -> int:
    st = style or ("b" if bold else "r")
    if ch == NAIRA:
        # an N plus room for the two bars that stick out of it, so the digit after never touches them
        return pdf_char_w("N", bold, style) + 60
    if st in ("m", "mb"):
        return 600  # Courier is fixed-width
    try:
        code = ch.encode("cp1252")[0]
    except Exception:
        return 556
    if code < 32:
        return 278
    return (_HELV_BOLD_W if st == "b" else _HELV_W)[code - 32]  # Helvetica-Oblique has the same widths as Helvetica


def pdf_width(text: str, size: float, bold: bool = False, style: str | None = None, spacing: float = 0.0) -> float:
    s = pdf_safe(text)
    return sum(pdf_char_w(c, bold, style) for c in s) * size / 1000.0 + spacing * len(s)


def pdf_wrap(text: str, size: float, bold: bool, max_w: float, style: str | None = None) -> list[str]:
    lines: list[str] = []
    cur = ""
    for word in pdf_safe(text).split(" "):
        if not word:
            continue
        trial = word if not cur else cur + " " + word
        if pdf_width(trial, size, bold, style) <= max_w:
            cur = trial
            continue
        if cur:
            lines.append(cur)
            cur = ""
        while len(word) > 1 and pdf_width(word, size, bold, style) > max_w:
            n = len(word)
            while n > 1 and pdf_width(word[:n], size, bold, style) > max_w:
                n -= 1
            lines.append(word[:n])
            word = word[n:]
        cur = word
    if cur:
        lines.append(cur)
    return lines


def pdf_fit(text: str, size: float, bold: bool, max_w: float, style: str | None = None) -> str:
    t = pdf_safe(text)
    if pdf_width(t, size, bold, style) <= max_w:
        return t
    while t and pdf_width(t + "…", size, bold, style) > max_w:
        t = t[:-1]
    return t.rstrip() + "…"


def _pdf_str(text: str) -> bytes:
    raw = pdf_safe(text).replace(NAIRA, "N").encode("cp1252", "replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _pdf_color(hexcolor: str) -> str:
    r, g, b = (int(hexcolor[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return f"{r:.3f} {g:.3f} {b:.3f}"


def _mix(c1: str, c2: str, t: float) -> str:
    """Blend two #rrggbb colours (t=0 gives c1, t=1 gives c2)."""
    a = [int(c1[i : i + 2], 16) for i in (1, 3, 5)]
    z = [int(c2[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, z))


def _rr_path(x: float, y: float, w: float, h: float, r: float, corners: tuple[int, int, int, int] = (1, 1, 1, 1)) -> str:
    """Rounded rectangle path in PDF coordinates (origin bottom-left). corners = top-left, top-right, bottom-right, bottom-left."""
    r = max(0.0, min(r, w / 2, h / 2))
    if r == 0 or not any(corners):
        return f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re "
    tl, tr, br, bl = (r if c else 0.0 for c in corners)
    k = 0.5523
    p = [f"{x + bl:.2f} {y:.2f} m", f"{x + w - br:.2f} {y:.2f} l"]
    if br:
        p.append(f"{x + w - br + k * br:.2f} {y:.2f} {x + w:.2f} {y + br - k * br:.2f} {x + w:.2f} {y + br:.2f} c")
    p.append(f"{x + w:.2f} {y + h - tr:.2f} l")
    if tr:
        p.append(f"{x + w:.2f} {y + h - tr + k * tr:.2f} {x + w - tr + k * tr:.2f} {y + h:.2f} {x + w - tr:.2f} {y + h:.2f} c")
    p.append(f"{x + tl:.2f} {y + h:.2f} l")
    if tl:
        p.append(f"{x + tl - k * tl:.2f} {y + h:.2f} {x:.2f} {y + h - tl + k * tl:.2f} {x:.2f} {y + h - tl:.2f} c")
    p.append(f"{x:.2f} {y + bl:.2f} l")
    if bl:
        p.append(f"{x:.2f} {y + bl - k * bl:.2f} {x + bl - k * bl:.2f} {y:.2f} {x + bl:.2f} {y:.2f} c")
    return " ".join(p) + " h "


_FONT_OF = {"r": "F1", "b": "F2", "i": "F3", "m": "F4", "mb": "F5"}


class _PdfPage:
    """One page. Coordinates passed in are measured from the TOP-left, like on a web page.
    Drawing order: bg0 (card backgrounds) -> bg (bands, charts) -> mid (watermarks) -> fg (text, lines)."""

    def __init__(self, doc: "PdfDoc", w: float, h: float):
        self.doc, self.w, self.h = doc, w, h
        self.layers: dict[str, list[bytes]] = {"bg0": [], "bg": [], "mid": [], "fg": []}
        self.images: set[str] = set()
        self.gs: set[str] = set()
        self.shadings: set[str] = set()
        self.links: list[tuple[float, float, float, float, str]] = []

    def _add(self, layer: str, ops: str) -> None:
        self.layers[layer].append(ops.encode("latin-1"))

    def _alpha(self, alpha: float) -> str:
        if alpha >= 0.999:
            return ""
        name = self.doc.gstate(alpha)
        self.gs.add(name)
        return f"/{name} gs "

    def rrect(self, x: float, top: float, w: float, h: float, r: float = 0, fill: str | None = None, stroke: str | None = None,
              lw: float = 0.8, layer: str = "fg", alpha: float = 1.0, corners: tuple[int, int, int, int] = (1, 1, 1, 1)) -> None:
        path = _rr_path(x, self.h - top - h, w, h, r, corners)
        ops = "q " + self._alpha(alpha)
        if fill:
            ops += f"{_pdf_color(fill)} rg "
        if stroke:
            ops += f"{_pdf_color(stroke)} RG {lw:.2f} w "
        ops += path + ("B" if fill and stroke else "f" if fill else "S") + " Q"
        self._add(layer, ops)

    def circle(self, cx: float, top_cy: float, r: float, fill: str | None = None, stroke: str | None = None, lw: float = 0.8,
               layer: str = "fg", alpha: float = 1.0) -> None:
        y, k = self.h - top_cy, 0.5523 * r
        path = (
            f"{cx + r:.2f} {y:.2f} m {cx + r:.2f} {y + k:.2f} {cx + k:.2f} {y + r:.2f} {cx:.2f} {y + r:.2f} c "
            f"{cx - k:.2f} {y + r:.2f} {cx - r:.2f} {y + k:.2f} {cx - r:.2f} {y:.2f} c "
            f"{cx - r:.2f} {y - k:.2f} {cx - k:.2f} {y - r:.2f} {cx:.2f} {y - r:.2f} c "
            f"{cx + k:.2f} {y - r:.2f} {cx + r:.2f} {y - k:.2f} {cx + r:.2f} {y:.2f} c h "
        )
        ops = "q " + self._alpha(alpha)
        if fill:
            ops += f"{_pdf_color(fill)} rg "
        if stroke:
            ops += f"{_pdf_color(stroke)} RG {lw:.2f} w "
        self._add(layer, ops + path + ("B" if fill and stroke else "f" if fill else "S") + " Q")

    def gradient(self, x: float, top: float, w: float, h: float, c0: str, c1: str, direction: str = "h", r: float = 0,
                 corners: tuple[int, int, int, int] = (1, 1, 1, 1), layer: str = "bg") -> None:
        y = self.h - top - h
        if direction == "v":
            coords = (x, y + h, x, y)
        elif direction == "d":
            coords = (x, y + h, x + w, y)
        else:
            coords = (x, y, x + w, y)
        name = self.doc.shading(c0, c1, coords)
        self.shadings.add(name)
        self._add(layer, f"q {_rr_path(x, y, w, h, r, corners)}W n /{name} sh Q")

    def accent(self, x: float, top: float, w: float, h: float, r: float, bar_h: float, color: str) -> None:
        """A coloured bar along the top edge of a rounded card (clipped to the card's corners)."""
        clip = _rr_path(x, self.h - top - h, w, h, r)
        self._add("bg", f"q {clip}W n {_pdf_color(color)} rg {x:.2f} {self.h - top - bar_h:.2f} {w:.2f} {bar_h:.2f} re f Q")

    def hline(self, x1: float, x2: float, y: float, color: str, lw: float = 0.8, dash: tuple[int, int] | None = None, alpha: float = 1.0) -> None:
        d = f"[{dash[0]} {dash[1]}] 0 d " if dash else ""
        self._add("fg", f"q {self._alpha(alpha)}{_pdf_color(color)} RG {lw:.2f} w {d}{x1:.2f} {self.h - y:.2f} m {x2:.2f} {self.h - y:.2f} l S Q")

    def vline(self, x: float, y1: float, y2: float, color: str, lw: float = 0.8) -> None:
        self._add("fg", f"q {_pdf_color(color)} RG {lw:.2f} w {x:.2f} {self.h - y1:.2f} m {x:.2f} {self.h - y2:.2f} l S Q")

    def check(self, cx: float, top_cy: float, size: float, color: str, lw: float = 1.6) -> None:
        y = self.h - top_cy
        pts = [(cx - size * 0.45, y - size * 0.02), (cx - size * 0.12, y - size * 0.35), (cx + size * 0.5, y + size * 0.38)]
        self._add("fg", f"q {_pdf_color(color)} RG {lw:.2f} w 1 J 1 j {pts[0][0]:.2f} {pts[0][1]:.2f} m {pts[1][0]:.2f} {pts[1][1]:.2f} l {pts[2][0]:.2f} {pts[2][1]:.2f} l S Q")

    def arrow(self, x1: float, x2: float, top_y: float, color: str, lw: float = 0.9, head: float = 3.2) -> None:
        y = self.h - top_y
        self._add(
            "fg",
            f"q {_pdf_color(color)} RG {lw:.2f} w 1 J 1 j {x1:.2f} {y:.2f} m {x2:.2f} {y:.2f} l S "
            f"{x2 - head:.2f} {y + head:.2f} m {x2:.2f} {y:.2f} l {x2 - head:.2f} {y - head:.2f} l S Q",
        )

    def qr(self, matrix: list[list[int]], x: float, top: float, size: float, fg: str = "#000000", bg: str | None = "#ffffff", quiet: int = 2) -> None:
        n = len(matrix)
        cells = n + 2 * quiet
        m = size / cells
        if bg:
            self.rrect(x, top, size, size, 0, fill=bg, layer="fg")
        ops = [f"q {_pdf_color(fg)} rg"]
        for r, row in enumerate(matrix):
            c = 0
            while c < n:
                if row[c]:
                    start = c
                    while c < n and row[c]:
                        c += 1
                    ops.append(f"{x + (start + quiet) * m:.3f} {self.h - top - (r + quiet + 1) * m:.3f} {(c - start) * m + 0.02:.3f} {m + 0.02:.3f} re")
                else:
                    c += 1
        ops.append("f Q")
        self._add("fg", " ".join(ops))

    def link(self, x: float, top: float, w: float, h: float, url: str) -> None:
        if re.fullmatch(r"https?://[\x21-\x7e]+", url or ""):
            self.links.append((x, self.h - top - h, x + w, self.h - top, url))

    def watermark(self, s: str, cx: float, top_cy: float, size: float, angle: float, color: str, alpha: float = 0.08, layer: str = "mid") -> None:
        s = pdf_safe(s)
        width = pdf_width(s, size, True)
        a = math.radians(angle)
        cos, sin = math.cos(a), math.sin(a)
        # rotate about the centre of the text
        ox = -width / 2 * cos + (size * 0.35) * sin
        oy = -width / 2 * sin - (size * 0.35) * cos
        self._add(
            layer,
            f"q {self._alpha(alpha)}{_pdf_color(color)} rg {cos:.4f} {sin:.4f} {-sin:.4f} {cos:.4f} {cx + ox:.2f} {self.h - top_cy + oy:.2f} cm "
            f"BT /F2 {size:.1f} Tf ({_pdf_str(s).decode('latin-1')}) Tj ET Q",
        )

    def text(self, x: float, base: float, s: str, size: float, bold: bool = False, color: str = "#000000", align: str = "l",
             style: str | None = None, spacing: float = 0.0, alpha: float = 1.0) -> float:
        s = pdf_safe(s)
        st = style or ("b" if bold else "r")
        total = pdf_width(s, size, False, st, spacing)
        if align == "r":
            x -= total
        elif align == "c":
            x -= total / 2
        font = _FONT_OF[st]
        y = self.h - base
        al = self._alpha(alpha)
        tc = f"{spacing:.2f} Tc " if spacing else ""
        cur = x
        for part in re.split(f"({NAIRA})", s):
            if not part:
                continue
            if part == NAIRA:
                nw = pdf_char_w("N", False, st) * size / 1000.0
                gap = 0.06 * size
                self._add("fg", f"q {al}{_pdf_color(color)} rg BT /{font} {size:.2f} Tf {cur:.2f} {y:.2f} Td (N) Tj ET Q")
                lw = size * (0.085 if st in ("b", "mb") else 0.065)
                over = size * 0.035
                for frac in (0.27, 0.44):
                    yy = y + size * frac
                    self._add("fg", f"q {al}{_pdf_color(color)} RG {lw:.2f} w {cur - over:.2f} {yy:.2f} m {cur + nw + over:.2f} {yy:.2f} l S Q")
                cur += nw + gap + spacing
            else:
                self._add("fg", f"q {al}{_pdf_color(color)} rg BT /{font} {size:.2f} Tf {tc}{cur:.2f} {y:.2f} Td (" + _pdf_str(part).decode("latin-1") + ") Tj ET Q")
                cur += pdf_width(part, size, False, st, spacing)
        return total

    def image(self, name: str, x: float, top: float, w: float, h: float, radius: float = 0) -> None:
        self.images.add(name)
        clip = f"{_rr_path(x, self.h - top - h, w, h, radius)}W n " if radius else ""
        self._add("fg", f"q {clip}{w:.2f} 0 0 {h:.2f} {x:.2f} {self.h - top - h:.2f} cm /{name} Do Q")


class PdfDoc:
    def __init__(self, title: str, author: str = "Oja Loom", subject: str = ""):
        self.title, self.author, self.subject = title, author, subject
        self.pages: list[_PdfPage] = []
        self.images: list[tuple[str, dict[str, Any]]] = []
        self._gstates: dict[float, str] = {}
        self._shadings: list[tuple[str, str, str, tuple[float, ...]]] = []

    def page(self, w: float = PDF_W, h: float = PDF_H) -> _PdfPage:
        p = _PdfPage(self, w, h)
        self.pages.append(p)
        return p

    def add_image(self, img: dict[str, Any]) -> str:
        for name, known in self.images:
            if known is img:
                return name
        name = f"Im{len(self.images) + 1}"
        self.images.append((name, img))
        return name

    def gstate(self, alpha: float) -> str:
        key = round(max(0.0, min(1.0, alpha)), 3)
        if key not in self._gstates:
            self._gstates[key] = f"GS{len(self._gstates) + 1}"
        return self._gstates[key]

    def shading(self, c0: str, c1: str, coords: tuple[float, ...]) -> str:
        key = (c0, c1, tuple(round(v, 2) for v in coords))
        for name, a, z, co in self._shadings:
            if (a, z, co) == key:
                return name
        name = f"Sh{len(self._shadings) + 1}"
        self._shadings.append((name, key[0], key[1], key[2]))
        return name

    @staticmethod
    def _stream(entries: bytes, data: bytes) -> bytes:
        return entries + b" /Length %d >>\nstream\n" % len(data) + data + b"\nendstream"

    def render(self) -> bytes:
        objs: dict[int, bytes] = {}
        counter = [8]

        def alloc() -> int:
            counter[0] += 1
            return counter[0]

        for num, base in ((3, "Helvetica"), (4, "Helvetica-Bold"), (5, "Helvetica-Oblique"), (6, "Courier"), (7, "Courier-Bold")):
            objs[num] = b"<< /Type /Font /Subtype /Type1 /BaseFont /%s /Encoding /WinAnsiEncoding >>" % base.encode()
        font_res = b"/F1 3 0 R /F2 4 0 R /F3 5 0 R /F4 6 0 R /F5 7 0 R"
        img_ids: dict[str, int] = {}
        for name, img in self.images:
            iid = alloc()
            img_ids[name] = iid
            entries = b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace %s /BitsPerComponent 8 /Filter %s" % (
                img["w"], img["h"], img["cs"], img["filter"])
            if img.get("parms"):
                entries += b" /DecodeParms " + img["parms"]
            if img.get("smask"):
                sid = alloc()
                objs[sid] = self._stream(
                    b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode" % (img["w"], img["h"]),
                    img["smask"],
                )
                entries += b" /SMask %d 0 R" % sid
            objs[iid] = self._stream(entries, img["data"])
        gs_ids: dict[str, int] = {}
        for alpha, name in self._gstates.items():
            gid = alloc()
            gs_ids[name] = gid
            objs[gid] = b"<< /Type /ExtGState /ca %.3f /CA %.3f >>" % (alpha, alpha)
        sh_ids: dict[str, int] = {}
        for name, c0, c1, co in self._shadings:
            sid = alloc()
            sh_ids[name] = sid
            objs[sid] = (
                b"<< /ShadingType 2 /ColorSpace /DeviceRGB /Coords [%.2f %.2f %.2f %.2f] /Extend [true true] "
                b"/Function << /FunctionType 2 /Domain [0 1] /C0 [%s] /C1 [%s] /N 1 >> >>" % (co[0], co[1], co[2], co[3], _pdf_color(c0).encode(), _pdf_color(c1).encode())
            )
        kids: list[int] = []
        for pg in self.pages:
            body = b"\n".join(b"\n".join(pg.layers[k]) for k in ("bg0", "bg", "mid", "fg"))
            cid = alloc()
            objs[cid] = self._stream(b"<< /Filter /FlateDecode", zlib.compress(body, 9))
            annots = []
            for (x1, y1, x2, y2, url) in pg.links:
                aid = alloc()
                objs[aid] = (
                    b"<< /Type /Annot /Subtype /Link /Rect [%.2f %.2f %.2f %.2f] /Border [0 0 0] /A << /S /URI /URI (%s) >> >>"
                    % (x1, y1, x2, y2, url.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("ascii", "ignore"))
                )
                annots.append(aid)
            pid = alloc()
            xo = b" ".join(b"/%s %d 0 R" % (n.encode(), img_ids[n]) for n in sorted(pg.images))
            gso = b" ".join(b"/%s %d 0 R" % (n.encode(), gs_ids[n]) for n in sorted(pg.gs))
            sho = b" ".join(b"/%s %d 0 R" % (n.encode(), sh_ids[n]) for n in sorted(pg.shadings))
            ann = (b" /Annots [%s]" % b" ".join(b"%d 0 R" % a for a in annots)) if annots else b""
            objs[pid] = (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] /Contents %d 0 R%s "
                b"/Resources << /Font << %s >> /XObject << %s >> /ExtGState << %s >> /Shading << %s >> >> >>" % (pg.w, pg.h, cid, ann, font_res, xo, gso, sho)
            )
            kids.append(pid)
        objs[1] = b"<< /Type /Catalog /Pages 2 0 R /ViewerPreferences << /DisplayDocTitle true >> >>"
        objs[2] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), len(kids))
        stamp = utcnow().strftime("D:%Y%m%d%H%M%SZ").encode()
        objs[8] = b"<< /Title (%s) /Author (%s) /Subject (%s) /Producer (Oja Loom) /Creator (Oja Loom) /CreationDate (%s) >>" % (
            _pdf_str(self.title), _pdf_str(self.author), _pdf_str(self.subject), stamp)
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: dict[int, int] = {}
        for num in sorted(objs):
            offsets[num] = len(out)
            out += b"%d 0 obj\n" % num + objs[num] + b"\nendobj\n"
        xref = len(out)
        size = max(objs) + 1
        out += b"xref\n0 %d\n0000000000 65535 f \n" % size
        for num in range(1, size):
            out += b"%010d 00000 n \n" % offsets[num]
        out += b"trailer\n<< /Size %d /Root 1 0 R /Info 8 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, xref)
        return bytes(out)


# ---- logo images ---------------------------------------------------------------------
_LOGO_CACHE: dict[str, dict[str, Any] | None] = {}


def _jpeg_image(data: bytes) -> dict[str, Any] | None:
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            prec, h, w, comps = data[i + 4], (data[i + 5] << 8) | data[i + 6], (data[i + 7] << 8) | data[i + 8], data[i + 9]
            if prec != 8 or comps not in (1, 3):
                return None
            return {"w": w, "h": h, "cs": b"/DeviceGray" if comps == 1 else b"/DeviceRGB", "filter": b"/DCTDecode", "data": data, "parms": None, "smask": None}
        if marker == 0xD8 or marker == 0x01 or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        i += 2 + ((data[i + 2] << 8) | data[i + 3])
    return None


def _png_unfilter(raw: bytes, w: int, h: int, bpp: int) -> bytearray:
    stride = w * bpp
    out = bytearray(h * stride)
    prev = bytearray(stride)
    pos = 0
    for y in range(h):
        ft = raw[pos]
        row = bytearray(raw[pos + 1 : pos + 1 + stride])
        pos += 1 + stride
        if ft == 1:
            for i in range(bpp, stride):
                row[i] = (row[i] + row[i - bpp]) & 255
        elif ft == 2:
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 255
        elif ft == 3:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + ((left + prev[i]) >> 1)) & 255
        elif ft == 4:
            for i in range(stride):
                a = row[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                row[i] = (row[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        elif ft != 0:
            raise ValueError("bad PNG filter")
        out[y * stride : (y + 1) * stride] = row
        prev = row
    return out


def _png_image(data: bytes) -> dict[str, Any] | None:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos, idat, plte = 8, [], b""
    w = h = depth = ctype = interlace = 0
    while pos + 8 <= len(data):
        ln = struct.unpack(">I", data[pos : pos + 4])[0]
        kind, body = data[pos + 4 : pos + 8], data[pos + 8 : pos + 8 + ln]
        pos += 12 + ln
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            plte = body
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if depth != 8 or interlace != 0 or not w or not h or w * h > 600_000:
        return None
    raw = b"".join(idat)
    if ctype in (0, 2, 3):
        if ctype == 3:
            if not plte:
                return None
            cs = b"[/Indexed /DeviceRGB %d <%s>]" % (len(plte) // 3 - 1, plte.hex().encode())
        else:
            cs = b"/DeviceGray" if ctype == 0 else b"/DeviceRGB"
        colors = 3 if ctype == 2 else 1
        parms = b"<< /Predictor 15 /Colors %d /BitsPerComponent 8 /Columns %d >>" % (colors, w)
        return {"w": w, "h": h, "cs": cs, "filter": b"/FlateDecode", "data": raw, "parms": parms, "smask": None}
    if ctype in (4, 6):
        bpp = 2 if ctype == 4 else 4
        px = _png_unfilter(zlib.decompress(raw), w, h, bpp)
        if ctype == 4:
            color, cs = bytes(px[0::2]), b"/DeviceGray"
        else:
            rgb = bytearray(w * h * 3)
            rgb[0::3], rgb[1::3], rgb[2::3] = px[0::4], px[1::4], px[2::4]
            color, cs = bytes(rgb), b"/DeviceRGB"
        return {"w": w, "h": h, "cs": cs, "filter": b"/FlateDecode", "data": zlib.compress(color), "parms": None, "smask": zlib.compress(bytes(px[bpp - 1 :: bpp]))}
    return None


def pdf_logo(data_uri: str) -> dict[str, Any] | None:
    """The business logo as a PDF image, or None when the format cannot be embedded (e.g. WebP)."""
    m = IMAGE_RE.match(data_uri or "")
    if not m:
        return None
    try:
        data = base64.b64decode(m.group(2))
    except Exception:
        return None
    key = hashlib.sha1(data).hexdigest()
    if key in _LOGO_CACHE:
        return _LOGO_CACHE[key]
    try:
        img = _jpeg_image(data) if m.group(1) == "jpeg" else _png_image(data) if m.group(1) == "png" else None
    except Exception:
        img = None
    if len(_LOGO_CACHE) >= 16:
        _LOGO_CACHE.pop(next(iter(_LOGO_CACHE)))
    _LOGO_CACHE[key] = img
    return img


# --------------------------------------------------------------------------------------
# QR codes (ISO/IEC 18004, byte mode, versions 1-14): receipts carry one that opens the online copy
# --------------------------------------------------------------------------------------
import re as _re
from functools import lru_cache as _lru_cache

# ---------------------------------------------------------------------------
# Static tables.  Index 0 is version 1, index 13 is version 14.
# ---------------------------------------------------------------------------

_MAX_VERSION = 14

# Total codewords (data + error correction) in a symbol of each version.
_qr_TOTAL_CODEWORDS = (26, 44, 70, 100, 134, 172, 196, 242, 292, 346, 404, 466, 532, 581)

# Per ECC level: (EC codewords per block, number of blocks), one entry per version.
# Data codewords = total - ec_per_block * blocks; when the total does not divide
# evenly, the last (total % blocks) blocks carry one extra data codeword.
_ECC_TABLE = {
    "L": ((7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30),
          (1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4)),
    "M": ((10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24),
          (1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9)),
    "Q": ((13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20),
          (1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16)),
    "H": ((17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24),
          (1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16)),
}

# 2-bit ECC indicator used inside the format information.
_ECC_FORMAT_BITS = {"L": 1, "M": 0, "Q": 3, "H": 2}

# Alignment pattern centre coordinates (used for both rows and columns).
_ALIGN_POSITIONS = (
    (), (6, 18), (6, 22), (6, 26), (6, 30), (6, 34), (6, 22, 38),
    (6, 24, 42), (6, 26, 46), (6, 28, 50), (6, 30, 54), (6, 32, 58),
    (6, 34, 62), (6, 26, 46, 66),
)

# The eight data mask conditions; a module is inverted where the predicate is true.
_MASK_FUNCS = (
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
)

# Penalty rule helpers (applied to rows/columns rendered as '0'/'1' strings).
_RUN_RE = _re.compile(r"0{5,}|1{5,}")                              # N1: runs of >= 5
_FINDER_LIKE_RE = _re.compile(r"(?=(?:00001011101|10111010000))")  # N3: overlapping hits


# ---------------------------------------------------------------------------
# Reed-Solomon over GF(256), primitive polynomial x^8+x^4+x^3+x^2+1 (0x11D)
# ---------------------------------------------------------------------------

def _build_gf_tables() -> tuple[list[int], list[int]]:
    """Return (exp, log); exp is doubled in length so products need no modulo."""
    exp = [0] * 512
    log = [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


_qr_EXP, _qr_LOG = _build_gf_tables()


@_lru_cache(maxsize=None)
def _qr_rs_generator(degree: int) -> tuple[tuple[int, int], ...]:
    """prod_{i<degree}(x - a^i) as (index, log(coeff)) pairs for the non-leading
    coefficients, highest power first (the leading coefficient is always 1)."""
    poly = [1]
    for i in range(degree):
        root = _qr_EXP[i]
        nxt = poly + [0]                       # poly * x
        for j, coef in enumerate(poly):        # + poly * root
            if coef:
                nxt[j + 1] ^= _qr_EXP[_qr_LOG[coef] + _qr_LOG[root]]
        poly = nxt
    return tuple((i, _qr_LOG[c]) for i, c in enumerate(poly[1:]) if c)


def _qr_rs_remainder(data: list[int], degree: int) -> list[int]:
    """Remainder of data(x) * x^degree divided by the generator polynomial."""
    gen = _qr_rs_generator(degree)
    rem = [0] * degree
    for byte in data:
        factor = byte ^ rem[0]
        del rem[0]
        rem.append(0)
        if factor:
            lf = _qr_LOG[factor]
            for i, lg in gen:
                rem[i] ^= _qr_EXP[lg + lf]
    return rem


# ---------------------------------------------------------------------------
# Data encoding
# ---------------------------------------------------------------------------

def _qr_data_codewords(version: int, ecc: str) -> int:
    ec_len, blocks = _ECC_TABLE[ecc]
    return _qr_TOTAL_CODEWORDS[version - 1] - ec_len[version - 1] * blocks[version - 1]


def _select_version(nbytes: int, ecc: str) -> int:
    """Smallest version (1..14) whose data capacity holds nbytes in byte mode."""
    for version in range(1, _MAX_VERSION + 1):
        count_bits = 8 if version <= 9 else 16
        if 4 + count_bits + 8 * nbytes <= 8 * _qr_data_codewords(version, ecc):
            return version
    raise ValueError(
        f"data too long: {nbytes} bytes do not fit in version {_MAX_VERSION} "
        f"at error-correction level {ecc}"
    )


def _qr_encode_data(payload: bytes, version: int, capacity: int) -> list[int]:
    """Mode indicator + char count + data + terminator + padding -> data codewords."""
    count_bits = 8 if version <= 9 else 16
    n = len(payload)
    # 0100 | character count | data bytes, packed into one big integer.
    value = (0b0100 << (count_bits + 8 * n)) | (n << (8 * n)) | int.from_bytes(payload, "big")
    nbits = 4 + count_bits + 8 * n
    term = min(4, 8 * capacity - nbits)        # terminator: up to four 0 bits
    value <<= term
    nbits += term
    pad = -nbits % 8                           # zero-pad to a codeword boundary
    value <<= pad
    nbits += pad
    codewords = list(value.to_bytes(nbits // 8, "big"))
    pad_bytes = (0xEC, 0x11)                   # alternating pad codewords
    while len(codewords) < capacity:
        codewords.append(pad_bytes[(len(codewords) - nbits // 8) & 1])
    return codewords


def _add_ecc_and_interleave(data: list[int], version: int, ecc: str) -> list[int]:
    """Split into blocks (group 1 short, group 2 one byte longer), append RS
    codewords to each, then interleave data columns followed by EC columns."""
    ec_len = _ECC_TABLE[ecc][0][version - 1]
    nblocks = _ECC_TABLE[ecc][1][version - 1]
    total = _qr_TOTAL_CODEWORDS[version - 1]
    num_short = nblocks - total % nblocks      # blocks in group 1
    short_len = total // nblocks - ec_len      # data codewords in a group 1 block
    blocks = []
    pos = 0
    for i in range(nblocks):
        size = short_len + (i >= num_short)
        blocks.append(data[pos:pos + size])
        pos += size
    ec_blocks = [_qr_rs_remainder(b, ec_len) for b in blocks]
    out = []
    for i in range(short_len + 1):
        for b in blocks:
            if i < len(b):
                out.append(b[i])
    for i in range(ec_len):
        for e in ec_blocks:
            out.append(e[i])
    return out


# ---------------------------------------------------------------------------
# Symbol geometry (cached per version)
# ---------------------------------------------------------------------------

def _bch_remainder(value: int, poly: int, check_bits: int, info_bits: int) -> int:
    """Remainder of value * x^check_bits modulo the BCH generator `poly`."""
    rem = value
    for _ in range(check_bits):
        rem = (rem << 1) ^ ((rem >> (check_bits - 1)) * poly)
    return rem & ((1 << check_bits) - 1)


def _version_info_bits(version: int) -> int:
    """18-bit version information: 6 data bits + BCH(18,6), generator 0x1F25."""
    return (version << 12) | _bch_remainder(version, 0x1F25, 12, 6)


def _format_info_bits(ecc: str, mask: int) -> int:
    """15-bit format information: 5 data bits + BCH(15,5) (0x537), XOR 0x5412."""
    data = (_ECC_FORMAT_BITS[ecc] << 3) | mask
    return ((data << 10) | _bch_remainder(data, 0x537, 10, 5)) ^ 0x5412


@_lru_cache(maxsize=None)
def _format_positions(size: int) -> tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]]:
    """(row, col) of format bit i (0 = LSB) for the two copies of the format info."""
    first = ([(i, 8) for i in range(6)] + [(7, 8), (8, 8), (8, 7)]
             + [(8, 14 - i) for i in range(9, 15)])
    second = ([(8, size - 1 - i) for i in range(8)]
              + [(size - 15 + i, 8) for i in range(8, 15)])
    return tuple(first), tuple(second)


@_lru_cache(maxsize=None)
def _qr_layout(version: int):
    """Everything that depends only on the version:
    (template_rows, free_rows, data_positions)

    template_rows : rows holding the dark function modules (format area left 0)
    free_rows     : rows with 1 where a module is available for data
    data_positions: (row, bit_shift) of every data module in placement order
    """
    size = 4 * version + 17
    dark = [[0] * size for _ in range(size)]
    func = [[0] * size for _ in range(size)]

    def put(r: int, c: int, v: int) -> None:
        dark[r][c] = v
        func[r][c] = 1

    # Timing patterns (row 6 and column 6), alternating, dark on even index.
    for i in range(size):
        put(6, i, 1 - i % 2)
        put(i, 6, 1 - i % 2)

    # Finder patterns with their one-module light separators (9x9 around centre).
    for cr, cc in ((3, 3), (3, size - 4), (size - 4, 3)):
        for dr in range(-4, 5):
            for dc in range(-4, 5):
                r, c = cr + dr, cc + dc
                if 0 <= r < size and 0 <= c < size:
                    put(r, c, 0 if max(abs(dr), abs(dc)) in (2, 4) else 1)

    # Alignment patterns at every position pair except those hitting a finder.
    pos = _ALIGN_POSITIONS[version - 1]
    last = len(pos) - 1
    for i, r in enumerate(pos):
        for j, c in enumerate(pos):
            if (i, j) in ((0, 0), (0, last), (last, 0)):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    put(r + dr, c + dc, 0 if max(abs(dr), abs(dc)) == 1 else 1)

    # Reserve both format-information areas (bits written later, per mask).
    for copy in _format_positions(size):
        for r, c in copy:
            put(r, c, 0)
    put(size - 8, 8, 1)                        # the always-dark module

    # Version information (versions >= 7): two 6x3 blocks.
    if version >= 7:
        bits = _version_info_bits(version)
        for i in range(18):
            bit = (bits >> i) & 1
            a, b = size - 11 + i % 3, i // 3
            put(b, a, bit)                     # top-right block
            put(a, b, bit)                     # bottom-left block

    # Zig-zag data placement order: column pairs from the right, skipping the
    # vertical timing column, alternating upward / downward.
    positions = []
    upward = True
    for right in range(size - 1, 0, -2):
        if right <= 6:
            right -= 1
        for step in range(size):
            r = size - 1 - step if upward else step
            for c in (right, right - 1):
                if not func[r][c]:
                    positions.append((r, size - 1 - c))
        upward = not upward

    full = (1 << size) - 1
    template = tuple(int("".join(map(str, row)), 2) for row in dark)
    free = tuple(full ^ int("".join(map(str, row)), 2) for row in func)
    return template, free, tuple(positions)


@_lru_cache(maxsize=None)
def _mask_rows(version: int) -> tuple[tuple[int, ...], ...]:
    """For each of the 8 masks, row integers with 1 where the mask inverts."""
    size = 4 * version + 17
    result = []
    for fn in _MASK_FUNCS:
        rows = []
        for r in range(size):
            rows.append(int("".join("1" if fn(r, c) else "0" for c in range(size)), 2))
        result.append(tuple(rows))
    return tuple(result)


# ---------------------------------------------------------------------------
# Mask evaluation
# ---------------------------------------------------------------------------

def _qr_penalty(rows: list[int], size: int) -> int:
    """Total penalty (rules N1..N4) of a complete symbol given as row integers."""
    full = (1 << size) - 1
    fmt = f"0{size}b"
    row_strs = [format(r, fmt) for r in rows]
    col_strs = ["".join(col) for col in zip(*row_strs)]
    score = 0
    for line in row_strs + col_strs:
        # N1: runs of >= 5 same-colour modules score 3 + (run - 5).
        for run in _RUN_RE.findall(line):
            score += len(run) - 2
        # N3: 1:1:3:1:1 finder-like pattern with 4 light modules on one side.
        score += 40 * len(_FINDER_LIKE_RE.findall(line))
    # N2: 2x2 blocks of one colour score 3 each.
    for a, b in zip(rows, rows[1:]):
        dk = a & b
        lt = ~(a | b) & full
        score += 3 * ((dk & (dk >> 1)).bit_count() + (lt & (lt >> 1)).bit_count())
    # N4: 10 points per full 5% step the dark ratio is away from 50%.
    total = size * size
    dark = sum(r.bit_count() for r in rows)
    k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
    return score + 10 * max(k, 0)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def qr_matrix(text: str, ecc: str = "M") -> list[list[int]]:
    """Encode `text` (UTF-8, byte mode) as a QR Code and return its modules.

    Returns a square list of rows, 1 = dark and 0 = light, without a quiet zone.
    The smallest version (1..14) that fits is used; ValueError is raised for an
    unknown ECC level or if the data does not fit in version 14.
    """
    level = ecc.upper() if isinstance(ecc, str) else ecc
    if level not in _ECC_TABLE:
        raise ValueError(f"unknown error-correction level {ecc!r} (use L, M, Q or H)")
    payload = text.encode("utf-8")
    version = _select_version(len(payload), level)
    size = 4 * version + 17

    data = _qr_encode_data(payload, version, _qr_data_codewords(version, level))
    bitstream = "".join(format(b, "08b") for b in _add_ecc_and_interleave(data, version, level))

    template, free, positions = _qr_layout(version)
    masks = _mask_rows(version)

    # Drop the codeword bits into the data modules; leftover modules are the
    # remainder bits and stay 0.
    data_rows = [0] * size
    for (r, shift), bit in zip(positions, bitstream):
        if bit == "1":
            data_rows[r] |= 1 << shift

    format_pos = _format_positions(size)
    best_rows = None
    best_score = -1
    for mask in range(8):
        rows = [t | ((d ^ m) & f)
                for t, d, m, f in zip(template, data_rows, masks[mask], free)]
        bits = _format_info_bits(level, mask)
        for i in range(15):
            if (bits >> i) & 1:
                for copy in format_pos:
                    r, c = copy[i]
                    rows[r] |= 1 << (size - 1 - c)
        score = _qr_penalty(rows, size)
        if best_rows is None or score < best_score:
            best_rows, best_score = rows, score

    shifts = range(size - 1, -1, -1)
    return [[(row >> s) & 1 for s in shifts] for row in best_rows]


# ---- documents: shared look --------------------------------------------------------------
P_INK, P_MUTED, P_LINE, P_SOFT = "#0f1430", "#656d8a", "#e3e6ef", "#f1f3fb"
P_BRAND, P_BRAND_DARK, P_GOLD = "#2c3a9c", "#18206b", "#f2b01e"
P_OK, P_OK_BG, P_WARN, P_WARN_BG, P_BAD, P_BAD_BG = "#157a4b", "#e3f5ec", "#a85a00", "#fff1dc", "#c0352b", "#fdeceb"
LAGOS = dt.timezone(dt.timedelta(hours=1))  # Nigeria has no daylight saving: WAT is always UTC+1


def _pretty_date(iso: str) -> str:
    try:
        d = dt.date.fromisoformat(str(iso)[:10])
        return f"{d.day} {d.strftime('%b %Y')}"
    except ValueError:
        return str(iso or "")


def _pretty_when(iso: str) -> tuple[str, str]:
    """(date, time) of a stored UTC timestamp, shown in Lagos time."""
    d = _parse_dt(iso)
    if not d:
        return str(iso or "")[:10], ""
    d = d.astimezone(LAGOS)
    hour = d.hour % 12 or 12
    return f"{d.day} {d.strftime('%b %Y')}", f"{hour}:{d.minute:02d} {'am' if d.hour < 12 else 'pm'}"


def _n2(kobo: Any) -> str:
    return f"{NAIRA}{int(kobo or 0) / 100:,.2f}"


def _n0(kobo: Any) -> str:
    k = int(kobo or 0)
    return f"{NAIRA}{k / 100:,.0f}" if k % 100 == 0 else _n2(k)


def _n_short(kobo: Any) -> str:
    v = abs(int(kobo or 0)) / 100
    s = f"{v / 1e6:.1f}M" if v >= 1e6 else f"{v / 1e3:.1f}k" if v >= 1e4 else f"{v:,.0f}"
    return NAIRA + s.replace(".0M", "M").replace(".0k", "k")


def _fit_text(pg: Any, x: float, base: float, s: str, size: float, bold: bool = False, color: str = "#000000", align: str = "l",
              max_w: float | None = None, min_size: float = 5.5, **kw: Any) -> float:
    """Draw `s` and shrink the type until it fits `max_w`, so a very large amount never runs into its neighbour. Returns the size used."""
    if max_w:
        while size > min_size and pdf_width(s, size, bold) > max_w:
            size = round(size - 0.25, 2)
    pg.text(x, base, s, size, bold, color, align, **kw)
    return size


def _logo_tile(doc: PdfDoc, pg: _PdfPage, b: Any, logo_uri: str, x: float, top: float, size: float, tile: str = "#ffffff", ink: str = P_BRAND) -> None:
    """The business logo (kept in proportion) on a rounded tile, or its first letter when there is no embeddable logo."""
    r = size * 0.22
    pg.rrect(x, top, size, size, r, fill=tile, layer="bg")
    logo = pdf_logo(logo_uri) if b["has_logo"] else None
    if logo:
        pad = size * 0.09
        box = size - 2 * pad
        scale = min(box / logo["w"], box / logo["h"])
        w, h = logo["w"] * scale, logo["h"] * scale
        pg.image(doc.add_image(logo), x + (size - w) / 2, top + (size - h) / 2, w, h, size * 0.12)
    else:
        pg.text(x + size / 2, top + size * 0.68, (pdf_safe(b["name"]).strip()[:1] or "O").upper(), size * 0.46, True, ink, "c")


class _Kit:
    """A4 documents: branded header band on page 1, slim running header after that, page numbers in the footer."""

    def __init__(self, b: Any, logo_uri: str, doc_title: str, heading: str, subtitle: str = "", meta: Iterable[str] = (),
                 branding: bool = True, margin: float = 42.0):
        self.b, self.logo_uri, self.heading, self.subtitle, self.meta, self.branding = b, logo_uri, heading, subtitle, list(meta), branding
        self.doc = PdfDoc(doc_title, author=pdf_safe(b["name"]) or "Oja Loom", subject=heading)
        self.M, self.CW = margin, PDF_W - 2 * margin
        self.R = margin + self.CW
        self.LIMIT = PDF_H - 56.0
        self.pg: _PdfPage = None  # type: ignore[assignment]
        self.y = 0.0
        self.new_page(True)

    def new_page(self, first: bool = False) -> _PdfPage:
        pg = self.pg = self.doc.page()
        M, R = self.M, self.R
        name = pdf_safe(self.b["name"])
        if first:
            band = 104.0
            pg.gradient(0, 0, PDF_W, band, P_BRAND_DARK, P_BRAND, "d")
            pg.rrect(0, band, PDF_W, 3, fill=P_GOLD, layer="bg")
            _logo_tile(self.doc, pg, self.b, self.logo_uri, M, 27, 50)
            tx = M + 64
            sub_fit = pdf_fit(self.subtitle, 12, True, 230)
            right_w = max(pdf_width(sub_fit, 12, True), pdf_width(self.heading.upper(), 10.5, True, None, 1.6), 150) + 14
            name_w = R - right_w - tx
            lines = pdf_wrap(name, 17, True, name_w) or [""]
            if len(lines) > 2:
                lines = [lines[0], pdf_fit(" ".join(lines[1:]), 17, True, name_w)]
            base = 46.0 if len(lines) == 1 else 40.0
            for i, ln in enumerate(lines):
                pg.text(tx, base + i * 19, ln, 17, True, "#ffffff")
            base += (len(lines) - 1) * 19 + 15
            for part in (public_phone(self.b["phone"]), self.b["address"]):
                if part:
                    pg.text(tx, base, pdf_fit(part, 9, False, R - right_w - tx), 9, False, "#ffffff", alpha=0.78)
                    base += 12.5
            pg.text(R, 40, self.heading.upper(), 10.5, True, P_GOLD, "r", spacing=1.6)
            pg.text(R, 58, sub_fit, 12, True, "#ffffff", "r")
            for i, m in enumerate(self.meta[:3]):
                pg.text(R, 73 + i * 12, m, 8.5, False, "#ffffff", "r", alpha=0.8)
            self.y = band + 28
        else:
            pg.gradient(0, 0, PDF_W, 34, P_BRAND_DARK, P_BRAND, "h")
            pg.rrect(0, 34, PDF_W, 1.6, fill=P_GOLD, layer="bg")
            sub_s = pdf_fit(self.subtitle, 8.5, False, 190)
            tail = f"  \u00b7  {self.heading}"
            name_room = (R - M) - pdf_width(sub_s, 8.5, False) - pdf_width(tail, 8.5, True) - 20
            pg.text(M, 21.5, f"{pdf_fit(name, 8.5, True, max(60.0, name_room))}{tail}", 8.5, True, "#ffffff")
            pg.text(R, 21.5, sub_s, 8.5, False, "#ffffff", "r", alpha=0.85)
            self.y = 34 + 26
        return pg

    def need(self, h: float) -> bool:
        if self.y + h > self.LIMIT:
            self.new_page()
            return True
        return False

    def section(self, text: str, note: str = "") -> None:
        self.need(46)
        pg, y = self.pg, self.y
        pg.rrect(self.M, y + 1, 3, 14, 1.5, fill=P_BRAND)
        pg.text(self.M + 11, y + 12.5, text, 12, True, P_INK)
        if note:
            pg.text(self.R, y + 12, note, 8.5, False, P_MUTED, "r")
        self.y = y + 28

    def kpis(self, cards: list[tuple[str, str, str]]) -> None:
        """Row of summary boxes: (label, value, colour)."""
        self.need(80)
        pg, y, n, gap = self.pg, self.y, len(cards), 10.0
        bw = (self.CW - (n - 1) * gap) / n
        for i, (label, value, tone) in enumerate(cards):
            x = self.M + i * (bw + gap)
            pg.rrect(x, y, bw, 58, 8, fill=P_SOFT)
            pg.rrect(x, y + 10, 3, 38, 1.5, fill=tone)
            pg.text(x + 15, y + 21, label.upper(), 7.5, True, P_MUTED, spacing=0.6)
            size = 16.0
            while pdf_width(value, size, True) > bw - 28 and size > 9:
                size -= 0.5
            pg.text(x + 15, y + 44, value, size, True, tone if tone != P_BRAND else P_INK)
        self.y = y + 58 + 18

    def table_head(self, cols: list[tuple[str, float, str]]) -> None:
        pg, y = self.pg, self.y
        pg.rrect(self.M, y, self.CW, 21, 5, fill=P_SOFT)
        for label, x, al in cols:
            pg.text(x, y + 14, label.upper(), 7.5, True, P_MUTED, al, spacing=0.5)
        self.y = y + 25

    def finish(self) -> bytes:
        n = len(self.doc.pages)
        today = _pretty_date(today_iso())
        for i, pg in enumerate(self.doc.pages, 1):
            pg.hline(self.M, self.R, PDF_H - 40, P_LINE, 0.7)
            left = f"Generated {today}" + ("  ·  Made with Oja Loom" if self.branding else "")
            pg.text(self.M, PDF_H - 26, left, 7.5, False, P_MUTED)
            pg.text(self.R, PDF_H - 26, f"Page {i} of {n}", 7.5, False, P_MUTED, "r")
        return self.doc.render()


def _status_pill(pg: _PdfPage, x: float, top: float, label: str, fg: str, bg: str, align: str = "l") -> float:
    w = pdf_width(label, 8.5, True, None, 0.4) + 22
    if align == "r":
        x -= w
    pg.rrect(x, top, w, 18, 9, fill=bg)
    pg.text(x + 11, top + 12.4, label, 8.5, True, fg, spacing=0.4)
    return w


def _order_state(o: Any) -> tuple[str, str, str]:
    """(label, text colour, background) for an order's payment state."""
    if o["status"] == "cancelled":
        return "CANCELLED", P_BAD, P_BAD_BG
    if o["balance"] <= 0:
        return "PAID IN FULL", P_OK, P_OK_BG
    if o["amount_paid"] > 0:
        return "PART PAID", P_WARN, P_WARN_BG
    return "UNPAID", P_WARN, P_WARN_BG


# ---- the receipt / invoice ------------------------------------------------------------------
def build_receipt_pdf(b: Any, o: Any, c: Any, items: list[Any], payments: list[Any] | None = None, logo_uri: str = "", url: str = "",
                      kind: str = "receipt", due_date: str | None = None, branding: bool = True) -> bytes:
    if kind == "thermal":
        return build_thermal_pdf(b, o, c, items, payments or [], logo_uri, url, branding)
    payments = list(payments or [])
    invoice = kind == "invoice"
    title = "Invoice" if invoice else "Receipt"
    state_label, state_fg, state_bg = _order_state(o)
    kit = _Kit(b, logo_uri, f"{title} {o['order_number']}", title, o["order_number"], [_pretty_date(o["order_date"])], branding)
    M, CW, R = kit.M, kit.CW, kit.R
    doc = kit.doc
    overdue = bool(invoice and due_date and o["balance"] > 0 and str(due_date)[:10] < today_iso() and o["status"] != "cancelled")

    # ---- who / when
    pg, y = kit.pg, kit.y
    col2 = M + CW * 0.56
    pg.text(M, y + 8, "BILLED TO", 7.5, True, P_MUTED, spacing=0.8)
    cname = pdf_wrap(c["full_name"] if c else "Walk-in customer", 13, True, col2 - M - 20)[:2] or [""]
    for i, ln in enumerate(cname):
        pg.text(M, y + 26 + i * 16, ln, 13, True, P_INK)
    cy = y + 26 + (len(cname) - 1) * 16
    for part in ((public_phone(c["phone"]) if c else ""), (c["address"] if c and "address" in c.keys() else "")):
        for ln in (pdf_wrap(part, 9.5, False, col2 - M - 20)[:2] if part else []):
            cy += 13.5
            pg.text(M, cy, ln, 9.5, False, P_MUTED)
    details = [("Issue date", _pretty_date(o["order_date"]))]
    if invoice:
        details.append(("Due date", _pretty_date(due_date) if due_date else "On receipt"))
    details.append(("Payment method", str(o["payment_method"])))
    dy = y + 8
    for label, value in details:
        pg.text(col2, dy, label, 9, False, P_MUTED)
        pg.text(R, dy, pdf_fit(value, 9.5, True, R - col2 - 80), 9.5, True, P_INK, "r")
        dy += 17
    _status_pill(pg, R, dy - 4, state_label, state_fg, state_bg, "r")
    y = max(cy + 14, dy + 22) + 10
    kit.y = y

    # ---- items
    ITEM_X, QTY_X, PRICE_X, AMT_X = M + 30, R - 214, R - 112, R - 8
    kit.table_head([("#", M + 10, "l"), ("Item", ITEM_X, "l"), ("Qty", QTY_X, "r"), ("Unit price", PRICE_X, "r"), ("Amount", AMT_X, "r")])
    for n, it in enumerate(items, 1):
        lines = pdf_wrap(it["product_name"], 10, False, QTY_X - 62 - ITEM_X) or [""]
        row_h = len(lines) * 13 + 14
        if kit.need(row_h + 4):
            kit.table_head([("#", M + 10, "l"), ("Item", ITEM_X, "l"), ("Qty", QTY_X, "r"), ("Unit price", PRICE_X, "r"), ("Amount", AMT_X, "r")])
        pg, y = kit.pg, kit.y
        if n % 2 == 0:
            pg.rrect(M, y, CW, row_h, 4, fill="#f8f9fd", layer="bg")
        pg.text(M + 10, y + 17, str(n), 9, False, P_MUTED)
        for i, ln in enumerate(lines):
            pg.text(ITEM_X, y + 17 + i * 13, ln, 10, False, P_INK)
        _fit_text(pg, QTY_X, y + 17, f"{it['quantity']:,}", 10, False, P_INK, "r", 54)
        _fit_text(pg, PRICE_X, y + 17, _n2(it["unit_price"]), 10, False, P_INK, "r", PRICE_X - QTY_X - 10 + 0)
        _fit_text(pg, AMT_X, y + 17, _n2(it["line_total"]), 10, True, P_INK, "r", AMT_X - PRICE_X - 10)
        kit.y = y + row_h
    kit.pg.hline(M, R, kit.y + 2, P_LINE, 0.9)
    kit.y += 16

    # ---- totals (left: QR + amount in words, right: the sums)
    adj = int(o["adjustment"] or 0) if "adjustment" in o.keys() else 0
    rows: list[tuple[str, str, str]] = [("Subtotal", _n2(o["subtotal"]), P_INK)]
    if o["discount"]:
        rows.append(("Discount", "− " + _n2(o["discount"]), P_INK))
    if adj:
        rows.append(("Correction", ("+ " if adj > 0 else "− ") + _n2(abs(adj)), P_INK))
    tw = 232.0
    tx = R - tw
    need_h = len(rows) * 18 + 150
    kit.need(max(need_h, 124))
    pg, y = kit.pg, kit.y
    ty = y
    for label, value, color in rows:
        pg.text(tx, ty + 12, label, 10, False, P_MUTED)
        _fit_text(pg, R, ty + 12, value, 10, False, color, "r", tw - 72)
        ty += 18
    pg.hline(tx, R, ty + 4, P_INK, 1.2)
    ty += 12
    pg.text(tx, ty + 15, "Total", 14, True, P_INK)
    _fit_text(pg, R, ty + 15, _n2(o["total"]), 14, True, P_INK, "r", tw - 52)
    ty += 28
    pg.text(tx, ty + 11, "Amount paid", 10, False, P_MUTED)
    _fit_text(pg, R, ty + 11, _n2(o["amount_paid"]), 10, False, P_OK if o["amount_paid"] else P_INK, "r", tw - 88)
    ty += 22
    if o["status"] == "cancelled":
        box_bg, box_fg, box_label, box_val = P_BAD_BG, P_BAD, "Cancelled", ""
    elif o["balance"] <= 0:
        box_bg, box_fg, box_label, box_val = P_OK_BG, P_OK, "Paid in full", ""
    else:
        box_bg, box_fg, box_label, box_val = P_WARN_BG, P_WARN, "Balance due", _n2(o["balance"])
    pg.rrect(tx - 8, ty, tw + 16, 38, 8, fill=box_bg)
    if box_val:
        pg.text(tx + 6, ty + 24, box_label, 10.5, True, box_fg)
        _fit_text(pg, R - 6, ty + 25, box_val, 15, True, box_fg, "r", tw - 4 - 12 - pdf_width(box_label, 10.5, True) - 8)
    else:
        if box_label == "Paid in full":
            pg.check(tx + 14, ty + 19, 11, box_fg, 1.8)
            pg.text(tx + 30, ty + 24, box_label, 11, True, box_fg)
        else:
            pg.text(tx + 6, ty + 24, box_label, 11, True, box_fg)
    ty += 38

    lx_w = CW - tw - 34
    ly = y
    qr = None
    if url:
        try:
            qr = qr_matrix(url, "M")
        except ValueError:
            qr = None
    if qr:
        pg.rrect(M, ly, 84, 84, 8, fill="#ffffff", stroke=P_LINE, lw=0.9)
        pg.qr(qr, M + 6, ly + 6, 72, P_INK, None, 0)
        pg.link(M, ly, 84, 84, url)
        pg.text(M + 98, ly + 14, "VIEW ONLINE", 7.5, True, P_MUTED, spacing=0.8)
        for i, ln in enumerate(pdf_wrap(f"Scan with your phone camera to open this {title.lower()} online, share or print it.", 8.5, False, lx_w - 98)[:4]):
            pg.text(M + 98, ly + 29 + i * 11.5, ln, 8.5, False, P_MUTED)
        ly += 84 + 12
    words_amt = o["balance"] if (invoice and o["balance"] > 0) else o["amount_paid"] if o["amount_paid"] else o["total"]
    words_label = "AMOUNT DUE IN WORDS" if (invoice and o["balance"] > 0) else ("AMOUNT PAID IN WORDS" if o["amount_paid"] else "TOTAL IN WORDS")
    pg.text(M, ly + 10, words_label, 7.5, True, P_MUTED, spacing=0.8)
    for i, ln in enumerate(pdf_wrap(naira_words(words_amt), 9.5, False, lx_w, "i")[:3]):
        pg.text(M, ly + 25 + i * 13, ln, 9.5, False, P_INK, style="i")
        ly += 0
    ly += 25 + 13 * min(3, max(1, len(pdf_wrap(naira_words(words_amt), 9.5, False, lx_w, "i"))))
    kit.y = max(ty, ly) + 18

    # ---- payments
    if payments:
        kit.section("Payments received", f"{len(payments)} payment{'s' if len(payments) != 1 else ''}")
        D_X, M_X, N_X, A_X, B_X = M + 10, M + 100, M + 210, R - 100, R - 8
        cols = [("Date", D_X, "l"), ("Method", M_X, "l"), ("Note", N_X, "l"), ("Paid", A_X, "r"), ("Balance after", B_X, "r")]
        kit.table_head(cols)
        running = int(o["total"] or 0)
        for p in payments:
            if kit.need(24):
                kit.table_head(cols)
            running -= int(p["amount"])
            pg, y = kit.pg, kit.y
            pg.text(D_X, y + 14, _pretty_date(p["paid_at"]), 9.5, False, P_INK)
            pg.text(M_X, y + 14, pdf_fit(p["payment_method"], 9.5, False, 100), 9.5, False, P_INK)
            note = p["note"] if "note" in p.keys() else ""
            pg.text(N_X, y + 14, pdf_fit(note or "–", 9, False, A_X - 96 - N_X), 9, False, P_MUTED)
            _fit_text(pg, A_X, y + 14, _n2(p["amount"]), 9.5, True, P_OK, "r", 88)
            _fit_text(pg, B_X, y + 14, _n2(max(0, running)), 9.5, False, P_INK, "r", B_X - A_X - 10)
            pg.hline(M, R, y + 21, P_LINE, 0.6)
            kit.y = y + 21
        kit.y += 14

    # ---- notes + thank-you
    if (o["notes"] or "").strip():
        kit.section("Notes")
        for ln in pdf_wrap(o["notes"], 9.5, False, CW):
            kit.need(16)
            kit.pg.text(M, kit.y + 10, ln, 9.5, False, P_INK)
            kit.y += 14
        kit.y += 10
    msg = pdf_wrap(b["receipt_message"] or "Thank you for your business.", 10, False, CW - 36)
    box_h = len(msg) * 14 + 24
    kit.need(box_h + 6)
    pg, y = kit.pg, kit.y
    pg.rrect(M, y, CW, box_h, 9, fill=P_SOFT)
    pg.rrect(M, y + 8, 3, box_h - 16, 1.5, fill=P_GOLD)
    for i, ln in enumerate(msg):
        pg.text(M + 18, y + 19 + i * 14, ln, 10, False, P_INK, style="i")
    kit.y = y + box_h + 10
    if invoice and due_date and o["balance"] > 0:
        kit.need(20)
        kit.pg.text(M, kit.y + 10, f"Payment is due by {_pretty_date(due_date)}.", 9, True, P_WARN if not overdue else P_BAD)
    return kit.finish()


def build_thermal_pdf(b: Any, o: Any, c: Any, items: list[Any], payments: list[Any], logo_uri: str = "", url: str = "", branding: bool = True) -> bytes:
    """80 mm till-roll slip: one tall page, black on white, sized to fit its content."""
    W, M = 226.77, 12.0
    CX, R = W / 2, W - M
    CW = W - 2 * M
    ink = "#000000"
    qr = None
    if url:
        try:
            qr = qr_matrix(url, "M")
        except ValueError:
            qr = None

    def draw(height: float) -> tuple[bytes, float]:
        doc = PdfDoc(f"Receipt {o['order_number']}", author=pdf_safe(b["name"]) or "Oja Loom", subject="Receipt")
        pg = doc.page(W, height)
        y = 14.0
        logo = pdf_logo(logo_uri) if b["has_logo"] else None
        if logo:
            box = 44.0
            sc = min(box / logo["w"], box / logo["h"])
            lw_, lh_ = logo["w"] * sc, logo["h"] * sc
            pg.image(doc.add_image(logo), CX - lw_ / 2, y, lw_, lh_)
            y += lh_ + 8
        for ln in pdf_wrap(b["name"], 13, True, CW)[:3]:
            y += 14
            pg.text(CX, y, ln, 13, True, ink, "c")
        for part in (public_phone(b["phone"]), b["address"]):
            for ln in (pdf_wrap(part, 8.5, False, CW)[:3] if part else []):
                y += 11
                pg.text(CX, y, ln, 8.5, False, ink, "c")
        y += 10
        pg.hline(M, R, y, ink, 0.8, (2, 2))
        y += 4
        for label, value in (("Receipt", o["order_number"]), ("Date", _pretty_date(o["order_date"])),
                             ("Customer", (c["full_name"] if c else "Walk-in customer"))):
            y += 12
            pg.text(M, y, label, 8.5, False, ink)
            pg.text(R, y, pdf_fit(value, 8.5, True, CW - 50), 8.5, True, ink, "r")
        y += 8
        pg.hline(M, R, y, ink, 0.8, (2, 2))
        y += 4
        for it in items:
            lines = pdf_wrap(it["product_name"], 9, True, CW)
            for ln in lines:
                y += 11.5
                pg.text(M, y, ln, 9, True, ink)
            y += 11.5
            left, amt = f"{it['quantity']} x {_n2(it['unit_price'])}", _n2(it["line_total"])
            if pdf_width(left, 8.5, False) + pdf_width(amt, 9, False) + 10 > CW:
                pg.text(M, y, pdf_fit(left, 8.5, False, CW), 8.5, False, ink)
                y += 11
            else:
                pg.text(M, y, left, 8.5, False, ink)
            _fit_text(pg, R, y, amt, 9, False, ink, "r", CW)
            y += 3
        y += 5
        pg.hline(M, R, y, ink, 0.8, (2, 2))
        y += 4
        adj = int(o["adjustment"] or 0) if "adjustment" in o.keys() else 0
        rows = [("Subtotal", _n2(o["subtotal"]))]
        if o["discount"]:
            rows.append(("Discount", "- " + _n2(o["discount"])))
        if adj:
            rows.append(("Correction", ("+ " if adj > 0 else "- ") + _n2(abs(adj))))
        for label, value in rows:
            y += 12
            pg.text(M, y, label, 9, False, ink)
            _fit_text(pg, R, y, value, 9, False, ink, "r", CW - 58)
        y += 18
        pg.text(M, y, "TOTAL", 12.5, True, ink)
        _fit_text(pg, R, y, _n2(o["total"]), 12.5, True, ink, "r", CW - 54)
        for label, value in (("Paid", _n2(o["amount_paid"])), (f"Paid by {o['payment_method']}", "")):
            if not value:
                continue
            y += 13
            pg.text(M, y, pdf_fit(label, 9, False, CW * 0.55), 9, False, ink)
            _fit_text(pg, R, y, value, 9, False, ink, "r", CW * 0.45)
        y += 15
        if o["status"] == "cancelled":
            label, big = "CANCELLED", ""
        elif o["balance"] <= 0:
            label, big = "PAID IN FULL", ""
        else:
            label, big = "BALANCE DUE", _n2(o["balance"])
        pg.rrect(M, y - 3, CW, 24, 4, stroke=ink, lw=1.1)
        pg.text(M + 8, y + 13, label, 9.5, True, ink)
        if big:
            _fit_text(pg, R - 8, y + 13, big, 11, True, ink, "r", CW - 16 - pdf_width(label, 9.5, True) - 8)
        y += 24 + 8
        words = pdf_wrap(naira_words(o["amount_paid"] or o["total"]), 8, False, CW, "i")[:3]
        for ln in words:
            y += 10.5
            pg.text(CX, y, ln, 8, False, ink, "c", style="i")
        if payments:
            y += 8
            pg.hline(M, R, y, ink, 0.8, (2, 2))
            y += 3
            for p in payments[-6:]:
                y += 11
                pg.text(M, y, f"{_pretty_date(p['paid_at'])}  {pdf_fit(p['payment_method'], 8, False, 80)}", 8, False, ink)
                _fit_text(pg, R, y, _n2(p["amount"]), 8, False, ink, "r", CW - 120)
            y += 4
        if qr:
            y += 12
            size = 92.0
            pg.qr(qr, CX - size / 2, y, size, ink, "#ffffff", 2)
            pg.link(CX - size / 2, y, size, size, url)
            y += size + 10
            pg.text(CX, y, "Scan to view online", 8, False, ink, "c")
        y += 14
        for ln in pdf_wrap(b["receipt_message"] or "Thank you for your business.", 9, False, CW, "i")[:4]:
            y += 11
            pg.text(CX, y, ln, 9, False, ink, "c", style="i")
        if branding:
            y += 16
            pg.text(CX, y, "Made with Oja Loom", 7, False, "#666666", "c")
        return doc.render(), y + 18

    _, need_h = draw(3000.0)
    data, _h = draw(max(180.0, need_h))
    return data


# ---- customer statement ----------------------------------------------------------------------
def build_statement_pdf(biz: Any, cust: dict[str, Any], blocks: list[dict[str, Any]], logo_uri: str = "", base_url: str = "") -> bytes:
    today = today_iso()
    entries: list[dict[str, Any]] = []
    for i, blk in enumerate(blocks):
        o = blk["order"]
        summary = ", ".join(f"{it['quantity']} × {it['product_name']}" for it in blk["items"])
        entries.append({"date": str(o["order_date"])[:10], "rank": 0, "seq": i, "kind": "order", "ref": o["order_number"], "text": summary,
                        "debit": int(o["total"] or 0), "credit": 0, "due": blk.get("due_date"), "open": int(o["balance"] or 0)})
        for j, p in enumerate(blk["payments"]):
            entries.append({"date": str(p["paid_at"])[:10], "rank": 1, "seq": i * 1000 + j, "kind": "payment", "ref": o["order_number"],
                            "text": p["payment_method"], "debit": 0, "credit": int(p["amount"]), "due": None, "open": 0})
    entries.sort(key=lambda e: (e["date"], e["rank"], e["seq"]))
    billed, paid = sum(e["debit"] for e in entries), sum(e["credit"] for e in entries)
    owing = billed - paid
    overdue = sum(blk["order"]["balance"] for blk in blocks if blk.get("due_date") and str(blk["due_date"])[:10] < today and blk["order"]["balance"] > 0)
    first = entries[0]["date"] if entries else today
    kit = _Kit(biz, logo_uri, f"Statement - {cust['full_name']}", "Statement of account", pdf_safe(cust["full_name"]),
               [f"{_pretty_date(first)} – {_pretty_date(today)}", f"As at {_pretty_date(today)}"])
    M, CW, R = kit.M, kit.CW, kit.R
    pg, y = kit.pg, kit.y
    pg.text(M, y + 8, "STATEMENT FOR", 7.5, True, P_MUTED, spacing=0.8)
    pg.text(M, y + 26, pdf_fit(cust["full_name"], 14, True, CW * 0.6), 14, True, P_INK)
    sub = "  ·  ".join(x for x in [public_phone(cust.get("phone")), cust.get("address") or ""] if x)
    if sub:
        pg.text(M, y + 41, pdf_fit(sub, 9.5, False, CW * 0.7), 9.5, False, P_MUTED)
    label, fg, bg = ("OWES NOTHING", P_OK, P_OK_BG) if owing <= 0 else (("OVERDUE", P_BAD, P_BAD_BG) if overdue else ("BALANCE OWING", P_WARN, P_WARN_BG))
    _status_pill(pg, R, y + 4, label, fg, bg, "r")
    kit.y = y + 60
    kit.kpis([("Total billed", _n0(billed), P_BRAND), ("Total paid", _n0(paid), P_OK),
              ("Balance owing", _n0(max(owing, 0)), P_WARN if owing > 0 else P_OK), ("Overdue", _n0(overdue), P_BAD if overdue else P_MUTED)])
    kit.section("Account activity", f"{len(entries)} entr{'ies' if len(entries) != 1 else 'y'}")
    D_X, T_X, DB_X, CR_X, BL_X = M + 8, M + 66, R - 172, R - 90, R - 8
    NUM_W = 74
    cols = [("Date", D_X, "l"), ("Description", T_X, "l"), ("Charged", DB_X, "r"), ("Paid", CR_X, "r"), ("Balance", BL_X, "r")]
    kit.table_head(cols)
    if not entries:
        kit.pg.text(M, kit.y + 12, "No orders have been recorded for this customer yet.", 9.5, False, P_MUTED)
        kit.y += 28
    running = 0
    desc_w = DB_X - NUM_W - 8 - T_X
    for e in entries:
        running += e["debit"] - e["credit"]
        sub_lines = pdf_wrap(e["text"], 8.5, False, desc_w)[:3] if e["kind"] == "order" else []
        extra, is_late = "", False
        if e["kind"] == "order" and e["due"] and e["open"] > 0:
            is_late = str(e["due"])[:10] < today
            extra = pdf_fit(("Overdue \u00b7 was due " if is_late else "Due ") + _pretty_date(e["due"]), 8, True, desc_w)
        row_h = 20 + 11.5 * (len(sub_lines) + (1 if extra else 0)) if e["kind"] == "order" else 31.5
        if kit.need(row_h + 4):
            kit.table_head(cols)
        pg, y = kit.pg, kit.y
        pg.text(D_X, y + 14, _pretty_date(e["date"]), 9, False, P_MUTED)
        if e["kind"] == "order":
            pg.text(T_X, y + 14, pdf_fit(e["ref"], 9.5, True, desc_w), 9.5, True, P_INK)
            for i, ln in enumerate(sub_lines):
                pg.text(T_X, y + 25 + i * 11.5, ln, 8.5, False, P_MUTED)
            if extra:
                pg.text(T_X, y + 25 + len(sub_lines) * 11.5, extra, 8, True, P_BAD if is_late else P_WARN)
            _fit_text(pg, DB_X, y + 14, _n2(e["debit"]), 9.5, False, P_INK, "r", NUM_W)
        else:
            pg.text(T_X, y + 14, "Payment received", 9.5, True, P_OK)
            pg.text(T_X, y + 25, pdf_fit(f"{e['text']} \u00b7 for {e['ref']}", 8.5, False, desc_w), 8.5, False, P_MUTED)
            _fit_text(pg, CR_X, y + 14, _n2(e["credit"]), 9.5, True, P_OK, "r", NUM_W)
        _fit_text(pg, BL_X, y + 14, _n2(running), 9.5, True if running > 0 else False, P_INK if running > 0 else P_OK, "r", NUM_W)
        pg.hline(M, R, y + row_h, P_LINE, 0.6)
        kit.y = y + row_h
    kit.need(90)
    pg, y = kit.pg, kit.y + 16
    box_bg, box_fg = (P_OK_BG, P_OK) if owing <= 0 else (P_WARN_BG, P_WARN)
    pg.rrect(R - 250, y, 250, 46, 9, fill=box_bg)
    pg.text(R - 236, y + 20, "BALANCE OWING" if owing > 0 else "ACCOUNT SETTLED", 8, True, box_fg, spacing=0.7)
    pg.text(R - 236, y + 38, "As at " + _pretty_date(today), 8.5, False, box_fg)
    _fit_text(pg, R - 14, y + 31, _n2(max(owing, 0)), 17, True, box_fg, "r", 150)
    contact = public_phone(biz["phone"])
    for i, ln in enumerate(pdf_wrap("Every order and payment recorded for this customer is listed above, oldest first. "
                                    + (f"If anything looks wrong, please call {contact}." if contact else "If anything looks wrong, please tell us."), 8.5, False, CW - 280)[:4]):
        pg.text(M, y + 14 + i * 11.5, ln, 8.5, False, P_MUTED)
    kit.y = y + 56
    return kit.finish()


# ---- debts (who owes what, and for how long) ---------------------------------------------------
DEBT_BUCKETS = (("current", "Not due yet"), ("d30", "1–30 days late"), ("d60", "31–60 days late"), ("d90", "61–90 days late"), ("d90p", "Over 90 days late"))


def debts_report_data(conn: sqlite3.Connection, bid: str) -> dict[str, Any]:
    today = dt.date.today()
    rows = conn.execute(
        """SELECT d.id, d.order_id, d.original_amount, d.amount_paid, d.remaining_balance, d.due_date, o.order_number, substr(o.order_date,1,10) order_date,
                  COALESCE(c.full_name,'Walk-in customer') customer, COALESCE(c.phone,'') phone, COALESCE(d.customer_id,'') customer_id
           FROM debts d JOIN orders o ON o.id=d.order_id LEFT JOIN customers c ON c.id=d.customer_id
           WHERE d.business_id=? AND d.status<>'paid' AND d.remaining_balance>0 AND o.status<>'cancelled'
           ORDER BY customer COLLATE NOCASE, o.order_date""", (bid,)).fetchall()
    buckets = {k: 0 for k, _ in DEBT_BUCKETS}
    out: list[dict[str, Any]] = []
    groups: dict[str, dict[str, Any]] = {}
    for r in rows:
        late = 0
        if r["due_date"]:
            try:
                late = (today - dt.date.fromisoformat(r["due_date"][:10])).days
            except ValueError:
                late = 0
        key = "current" if late <= 0 else "d30" if late <= 30 else "d60" if late <= 60 else "d90" if late <= 90 else "d90p"
        buckets[key] += r["remaining_balance"]
        row = dict(r)
        row["days_late"], row["bucket"] = max(late, 0), key
        out.append(row)
        g = groups.setdefault(r["customer_id"] or r["customer"], {"name": r["customer"], "phone": r["phone"], "rows": [], "owed": 0})
        g["rows"].append(row)
        g["owed"] += r["remaining_balance"]
    total = sum(r["remaining_balance"] for r in out)
    late_total = total - buckets["current"]
    return {
        "as_of": today.isoformat(), "rows": out, "total": total, "overdue_total": late_total, "buckets": buckets,
        "groups": sorted(groups.values(), key=lambda g: -g["owed"]), "customers": len(groups),
    }


def debts_csv(data: dict[str, Any]) -> bytes:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(["Customer", "Phone", "Order number", "Order date", "Due date", "Days late", "Original amount (NGN)", "Paid (NGN)", "Still owed (NGN)"])
    money = lambda k: f"{(k or 0) / 100:.2f}"  # noqa: E731
    for r in data["rows"]:
        w.writerow([_csv_text(r["customer"]), _csv_text(r["phone"]), _csv_text(r["order_number"]), r["order_date"], r["due_date"] or "", r["days_late"],
                    money(r["original_amount"]), money(r["amount_paid"]), money(r["remaining_balance"])])
    return out.getvalue().encode("utf-8-sig")


def build_debts_pdf(biz: Any, data: dict[str, Any], logo_uri: str = "", branding: bool = True) -> bytes:
    kit = _Kit(biz, logo_uri, f"Debts report {data['as_of']}", "Debts report", f"As at {_pretty_date(data['as_of'])}",
               [f"{data['customers']} customer{'s' if data['customers'] != 1 else ''} owe you"], branding)
    M, CW, R = kit.M, kit.CW, kit.R
    kit.kpis([("Total owed to you", _n0(data["total"]), P_BRAND), ("Past due date", _n0(data["overdue_total"]), P_BAD if data["overdue_total"] else P_OK),
              ("Customers owing", f"{data['customers']:,}", P_INK), ("Open debts", f"{len(data['rows']):,}", P_INK)])
    if not data["rows"]:
        kit.pg.text(M, kit.y + 10, "Nobody owes you anything right now.", 11, True, P_OK)
        kit.y += 30
        return kit.finish()

    # ---- how late is the money? (stacked bar + legend)
    kit.section("How late is the money?", "Based on each debt's due date")
    colors = [P_OK, "#e6a313", "#e0701b", P_BAD, "#7d1d16"]
    pg, y = kit.pg, kit.y
    total = max(1, data["total"])
    x = M
    for (key, _label), colr in zip(DEBT_BUCKETS, colors):
        amt = data["buckets"][key]
        if amt <= 0:
            continue
        seg = max(4.0, CW * amt / total)
        pg.rrect(x, y, seg - 1.5, 16, 3, fill=colr)
        x += seg
    y += 28
    cw5 = CW / 5
    for i, ((key, label), colr) in enumerate(zip(DEBT_BUCKETS, colors)):
        cx = M + i * cw5
        pg.rrect(cx, y + 1, 8, 8, 2, fill=colr)
        pg.text(cx + 13, y + 9, label, 8, False, P_MUTED)
        pg.text(cx + 13, y + 24, _n0(data["buckets"][key]), 11, True, P_INK)
    kit.y = y + 44

    # ---- grouped by customer
    kit.section("Who owes you", "Largest balance first")
    O_X, D_X, DUE_X, L_X, OWED_X = M + 14, M + 128, M + 204, M + 290, R - 8
    cols = [("Order", O_X, "l"), ("Ordered", D_X, "l"), ("Due", DUE_X, "l"), ("Late by", L_X, "l"), ("Still owed", OWED_X, "r")]
    for g in data["groups"]:
        if kit.need(80):
            pass
        pg, y = kit.pg, kit.y
        pg.rrect(M, y, CW, 26, 6, fill=P_SOFT)
        owed_txt = _n2(g["owed"])
        owed_size = _fit_text(pg, R - 8, y + 17, owed_txt, 10.5, True, P_INK, "r", 150)
        name_room = CW - 20 - pdf_width(owed_txt, owed_size, True) - 16
        phone_txt = public_phone(g["phone"])
        phone_w = pdf_width(phone_txt, 8.5, False) + 12 if phone_txt else 0
        name_w = max(60.0, min(260.0, name_room - phone_w))
        pg.text(M + 10, y + 17, pdf_fit(g["name"], 10.5, True, name_w), 10.5, True, P_INK)
        if phone_txt and pdf_width(pdf_fit(g["name"], 10.5, True, name_w), 10.5, True) + phone_w + 10 <= name_room:
            pg.text(M + 10 + pdf_width(pdf_fit(g["name"], 10.5, True, name_w), 10.5, True) + 12, y + 17, phone_txt, 8.5, False, P_MUTED)
        kit.y = y + 28
        first = True
        for r in g["rows"]:
            if kit.need(22):
                kit.table_head(cols)
            elif first:
                pass
            first = False
            pg, y = kit.pg, kit.y
            pg.text(O_X, y + 14, r["order_number"], 9, False, P_INK)
            pg.text(D_X, y + 14, _pretty_date(r["order_date"]), 9, False, P_MUTED)
            pg.text(DUE_X, y + 14, _pretty_date(r["due_date"]) if r["due_date"] else "No due date", 9, False, P_MUTED)
            if r["days_late"] > 0:
                pg.text(L_X, y + 14, f"{r['days_late']} day{'s' if r['days_late'] != 1 else ''}", 9, True, P_BAD if r["days_late"] > 30 else P_WARN)
            else:
                pg.text(L_X, y + 14, "–", 9, False, P_MUTED)
            _fit_text(pg, OWED_X, y + 14, _n2(r["remaining_balance"]), 9, True, P_INK, "r", 92)
            if r["amount_paid"]:
                of_txt = f"of {_n2(r['original_amount'])}"
                of_w = (OWED_X - 100) - (L_X + 56)
                if pdf_width(of_txt, 6.5, False) <= of_w:
                    _fit_text(pg, OWED_X - 100, y + 14, of_txt, 8, False, P_MUTED, "r", of_w, 6.5)
            pg.hline(M, R, y + 20, P_LINE, 0.5)
            kit.y = y + 20
        kit.y += 8
    return kit.finish()


# ---- edit history -------------------------------------------------------------------------------
_TYPE_COLOR = {"order": P_BRAND, "payment": P_OK, "debt": P_WARN, "product": "#7a3db8", "customer": "#0e7c86", "business": "#4b5578",
               "category": "#4b5578", "account": P_BAD, "plan": "#9a6a00"}


def _change_text(kind: str, v: Any) -> str:
    if kind == "money":
        return _n2(v)
    if kind == "bool":
        return "Yes" if v in (True, 1, "True", "true", "1") else "No"
    s = str(v if v is not None else "").strip()
    return s if s else "(empty)"


def activity_csv(items: list[dict[str, Any]]) -> bytes:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(["When (Lagos time)", "Area", "What happened", "About", "Summary", "Changes", "Reason", "By"])
    for it in items:
        d, t = _pretty_when(it["created_at"])
        changes = "; ".join(f"{c['label']}: {_change_text(c['kind'], c['from'])} -> {_change_text(c['kind'], c['to'])}" for c in it["changes"])
        w.writerow([f"{d} {t}".strip(), it["type_label"], it["action_label"], _csv_text(it["label"]), _csv_text(it["summary"]), _csv_text(changes),
                    _csv_text(it["reason"]), _csv_text(it["actor"])])
    return out.getvalue().encode("utf-8-sig")


def build_activity_pdf(biz: Any, items: list[dict[str, Any]], chain: dict[str, Any], logo_uri: str = "", start: str = "", end: str = "") -> bytes:
    rng = f"{_pretty_date(start)} – {_pretty_date(end)}" if start and end else (f"From {_pretty_date(start)}" if start else (f"Up to {_pretty_date(end)}" if end else "Everything recorded"))
    kit = _Kit(biz, logo_uri, "Edit history", "Edit history", rng, [f"{len(items):,} entr{'ies' if len(items) != 1 else 'y'}", "Times shown in Lagos time"])
    M, CW, R = kit.M, kit.CW, kit.R
    pg, y = kit.pg, kit.y
    ok = bool(chain.get("ok"))
    bg, fg = (P_OK_BG, P_OK) if ok else (P_BAD_BG, P_BAD)
    pg.rrect(M, y, CW, 44, 9, fill=bg)
    pg.circle(M + 24, y + 22, 11, fill=fg)
    if ok:
        pg.check(M + 24, y + 22, 10, "#ffffff", 1.8)
    else:
        pg.text(M + 24, y + 27, "!", 14, True, "#ffffff", "c")
    head = "History is intact" if ok else "History may have been tampered with"
    body = (f"{chain.get('checked', 0):,} entries were re-checked end to end. Nothing has been altered or removed since it was recorded."
            if ok else "The tamper check failed near " + _pretty_date(str(chain.get("broken_at") or "")) + ". Someone may have changed the database directly.")
    pg.text(M + 46, y + 18, head, 10.5, True, fg)
    pg.text(M + 46, y + 32, pdf_fit(body, 8.5, False, CW - 60), 8.5, False, fg)
    kit.y = y + 44 + 22
    if not items:
        kit.pg.text(M, kit.y + 12, "Nothing was recorded for these filters.", 10, False, P_MUTED)
        return kit.finish()
    last_day = None
    TIME_X, CHIP_X, TXT_X = M + 4, M + 58, M + 128
    TXT_W = R - TXT_X - 92
    for it in items:
        day, clock = _pretty_when(it["created_at"])
        wrapped = pdf_wrap(it["summary"], 9.5, True, TXT_W)[:3] or [""]
        sub = it["label"] if it["label"] and it["label"] not in it["summary"] else ""
        changes = it["changes"][:8]
        h = 12 + len(wrapped) * 12.5 + (11.5 if sub else 0) + (13 if it["reason"] else 0) + len(changes) * 12.5 + 10
        if kit.need(h + (30 if day != last_day else 0)):
            last_day = None
        if day != last_day:
            kit.pg.text(M, kit.y + 12, day.upper(), 8.5, True, P_BRAND, spacing=0.8)
            kit.pg.hline(M + pdf_width(day.upper(), 8.5, True, None, 0.8) + 10, R, kit.y + 9, P_LINE, 0.7)
            kit.y += 24
            last_day = day
        pg, y = kit.pg, kit.y
        pg.text(TIME_X, y + 11, clock, 8.5, False, P_MUTED)
        col = _TYPE_COLOR.get(it["type"], P_MUTED)
        chip = it["type_label"].upper()
        cw_ = pdf_width(chip, 6.5, True, None, 0.5) + 12
        pg.rrect(CHIP_X, y + 2, cw_, 13, 6.5, fill=col, alpha=0.14)
        pg.text(CHIP_X + 6, y + 11.2, chip, 6.5, True, col, spacing=0.5)
        yy = y + 11
        for ln in wrapped:
            pg.text(TXT_X, yy, ln, 9.5, True, P_INK)
            yy += 12.5
        yy -= 1
        if sub:
            pg.text(TXT_X, yy, pdf_fit(sub, 8.5, False, TXT_W), 8.5, False, P_MUTED)
            yy += 11.5
        pg.text(R, y + 11, pdf_fit(it["actor"] or "", 8.5, False, 86), 8.5, False, P_MUTED, "r")
        pg.text(R, y + 22, it["action_label"], 7.5, True, col, "r")
        for c in changes:
            fv, tv = _change_text(c["kind"], c["from"]), _change_text(c["kind"], c["to"])
            lab = pdf_fit(c["label"], 8.5, False, 100)
            pg.text(TXT_X, yy, lab + ":", 8.5, False, P_MUTED)
            vx = TXT_X + 104
            fv_s = pdf_fit(fv, 8.5, False, 90)
            pg.text(vx, yy, fv_s, 8.5, False, P_BAD)
            fw = pdf_width(fv_s, 8.5)
            pg.hline(vx, vx + fw, yy - 2.8, P_BAD, 0.6, alpha=0.7)
            pg.arrow(vx + fw + 7, vx + fw + 19, yy - 3, P_MUTED, 0.8, 2.6)
            pg.text(vx + fw + 25, yy, pdf_fit(tv, 8.5, True, R - 92 - (vx + fw + 25)), 8.5, True, P_OK)
            yy += 12.5
        if it["reason"]:
            pg.text(TXT_X, yy, pdf_fit("Reason: " + it["reason"], 8.5, False, TXT_W + 80, "i"), 8.5, False, P_MUTED, style="i")
            yy += 13
        pg.hline(M, R, y + h - 4, P_LINE, 0.45)
        kit.y = y + h
    return kit.finish()


# ---- sales report ---------------------------------------------------------------------------------
def _nice_max(kobo: int) -> int:
    v = max(kobo, 100) / 100
    exp = 10 ** math.floor(math.log10(v))
    for f in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= f * exp:
            return int(f * exp * 100)
    return int(10 * exp * 100)


def _bar_chart(pg: _PdfPage, x: float, top: float, w: float, h: float, series: list[tuple[str, int]]) -> None:
    n = len(series)
    mx = _nice_max(max((v for _, v in series), default=0))
    left, base = 40.0, top + h - 16
    plot_w, plot_h = w - left, h - 26
    for frac in (0, 0.5, 1):
        gy = base - plot_h * frac
        pg.hline(x + left, x + w, gy, P_LINE if frac else "#c9cee0", 0.6, None if frac == 0 else (2, 2))
        pg.text(x + left - 6, gy + 2.6, _n_short(mx * frac), 7, False, P_MUTED, "r")
    slot = plot_w / max(n, 1)
    bw = max(1.5, min(slot * 0.68, 26))
    for i, (_label, v) in enumerate(series):
        bh = plot_h * v / mx if v else 0
        if bh > 0.2:
            pg.rrect(x + left + i * slot + (slot - bw) / 2, base - bh, bw, max(bh, 1.2), min(2.5, bw / 2), fill=P_BRAND, corners=(1, 1, 0, 0))
    for idx in sorted({0, n // 2, n - 1}):
        if 0 <= idx < n:
            al = "l" if idx == 0 else "r" if idx == n - 1 else "c"
            px = x + left + idx * slot + (0 if al == "l" else slot if al == "r" else slot / 2)
            pg.text(px, base + 11, series[idx][0], 7, False, P_MUTED, al)


def build_report_pdf(b: Any, data: dict[str, Any], logo_uri: str = "", branding: bool = True) -> bytes:
    period = f"{_pretty_date(data['start'])} – {_pretty_date(data['end'])}"
    kit = _Kit(b, logo_uri, f"Sales report {data['start']} to {data['end']}", "Sales report", period, ["Completed orders only"], branding)
    M, CW, R = kit.M, kit.CW, kit.R
    margin = f"{data['profit'] * 100 / data['sales']:.0f}% margin" if data["sales"] else ""
    spent = data.get("expenses", 0)
    net = data.get("net", data["profit"] - spent)
    kit.kpis([("Sales", _n0(data["sales"]), P_BRAND), ("Orders", f"{data['count']:,}", P_INK), ("Est. profit", _n0(data["profit"]), P_OK),
              ("Expenses", _n0(spent), P_BAD if spent else P_INK), ("Net profit", _n0(net), P_OK if net >= 0 else P_BAD)])
    kit.pg.text(M, kit.y - 4, (f"Estimated profit is {margin} of sales. " if margin else "") + f"Average order {_n2(data['avg'])}. Owed to you across all orders today: {_n2(data['debt'])}.", 8.5, False, P_MUTED)
    kit.y += 14

    daily = data.get("daily") or []
    if daily and any(v for _d, v in daily):
        kit.section("Sales by day")
        step = max(1, math.ceil(len(daily) / 48))
        series = []
        for i in range(0, len(daily), step):
            chunk = daily[i : i + step]
            lab = dt.date.fromisoformat(chunk[0][0]).strftime("%d %b").lstrip("0")
            series.append((lab, sum(v for _d, v in chunk)))
        kit.need(150)
        _bar_chart(kit.pg, M, kit.y, CW, 130, series)
        kit.y += 146

    def ranking(heading: str, rows: list[dict[str, Any]], name_key: str, qty_key: str, qty_label: str, money_key: str, money_label: str) -> None:
        kit.section(heading)
        if not rows:
            kit.pg.text(M, kit.y + 10, "Nothing to show for these dates.", 9.5, False, P_MUTED)
            kit.y += 26
            return
        top_value = max(1, max(r[money_key] for r in rows))
        name_w = CW - 210
        cols = [("Name", M + 8, "l"), (qty_label, R - 110, "r"), (money_label, R - 8, "r")]
        kit.table_head(cols)
        for i, r in enumerate(rows, 1):
            if kit.need(32):
                kit.table_head(cols)
            p, yy = kit.pg, kit.y
            p.text(M + 8, yy + 14, f"{i}.", 9, False, P_MUTED)
            p.text(M + 26, yy + 14, pdf_fit(r[name_key], 10, False, name_w - 20), 10, False, P_INK)
            p.text(R - 110, yy + 14, f"{r[qty_key]:,}", 10, False, P_INK, "r")
            p.text(R - 8, yy + 14, _n2(r[money_key]), 10, True, P_INK, "r")
            p.rrect(M + 26, yy + 21, name_w - 20, 3.5, 1.75, fill=P_LINE)
            p.rrect(M + 26, yy + 21, max(3.0, (name_w - 20) * r[money_key] / top_value), 3.5, 1.75, fill=P_BRAND)
            kit.y = yy + 31
        kit.y += 10

    ranking("Best-selling products", data["best"], "name", "quantity", "Qty sold", "sales", "Sales")
    ranking("Top customers", data["top"], "name", "orders", "Orders", "spent", "Spent")

    rows = data["orders"][:MAX_PDF_ORDER_ROWS]
    kit.section("Orders in this period", f"{data['orders_total']:,} order{'s' if data['orders_total'] != 1 else ''}")
    if not rows:
        kit.pg.text(M, kit.y + 10, "No completed orders in these dates.", 9.5, False, P_MUTED)
        kit.y += 24
    else:
        c_order, c_cust = M + 66, M + 170
        c_total, c_paid, c_bal = R - 160, R - 82, R - 8
        cols = [("Date", M + 8, "l"), ("Order", c_order, "l"), ("Customer", c_cust, "l"), ("Total", c_total, "r"), ("Paid", c_paid, "r"), ("Balance", c_bal, "r")]
        kit.table_head(cols)
        for n, o in enumerate(rows):
            if kit.need(22):
                kit.table_head(cols)
            p, yy = kit.pg, kit.y
            if n % 2:
                p.rrect(M, yy, CW, 19, 3, fill="#f8f9fd", layer="bg")
            p.text(M + 8, yy + 13, _pretty_date(o["order_date"]), 8.5, False, P_MUTED)
            p.text(c_order, yy + 13, o["order_number"], 8.5, False, P_INK)
            p.text(c_cust, yy + 13, pdf_fit(o["customer"], 8.5, False, c_total - c_cust - 66), 8.5, False, P_INK)
            p.text(c_total, yy + 13, _n2(o["total"]), 8.5, False, P_INK, "r")
            p.text(c_paid, yy + 13, _n2(o["amount_paid"]), 8.5, False, P_INK, "r")
            p.text(c_bal, yy + 13, _n2(o["balance"]), 8.5, o["balance"] > 0, P_WARN if o["balance"] > 0 else P_INK, "r")
            kit.y = yy + 19
        if data["orders_total"] > len(rows):
            kit.need(30)
            kit.pg.text(M, kit.y + 20, f"Showing the latest {len(rows):,} of {data['orders_total']:,} orders. Download the CSV for the full list.", 8.5, False, P_MUTED)
    return kit.finish()


# --------------------------------------------------------------------------------------
# Expenses: what the business spends. Every add, edit and removal goes into the edit history.
# --------------------------------------------------------------------------------------
EXPENSE_CATEGORIES: tuple[str, ...] = (
    "Stock & supplies", "Transport & delivery", "Rent", "Salaries & wages", "Electricity & fuel", "Data & airtime",
    "Marketing & ads", "Packaging", "Repairs & maintenance", "Taxes & fees", "Other",
)
MAX_EXPENSE_ROWS = 300       # rows shown on screen; exports carry everything in the period
MAX_EXPORT_EXPENSES = 20000


def expense_item(r: sqlite3.Row) -> dict[str, Any]:
    return {"id": r["id"], "amount": kobo_to_number(r["amount"]), "category": r["category"], "description": r["description"],
            "vendor": r["vendor"], "spent_on": r["spent_on"], "created_at": r["created_at"]}


def expense_values(b: dict[str, Any]) -> dict[str, Any]:
    amount = money_to_kobo(b.get("amount"))
    if amount <= 0:
        raise ValueError("Enter how much was spent.")
    category = str(b.get("category") or "").strip()
    if category not in EXPENSE_CATEGORIES:
        raise ValueError("Choose a category from the list.")
    raw = str(b.get("spent_on") or "").strip()
    if raw:
        try:
            day = dt.date.fromisoformat(raw[:10])
        except ValueError:
            raise ValueError("Enter a valid date.")
    else:
        day = dt.date.today()
    if day > dt.date.today() + dt.timedelta(days=1):
        raise ValueError("The date cannot be in the future.")
    if day.year < 2000:
        raise ValueError("Enter a valid date.")
    return {"amount": amount, "category": category, "description": optional_text(b.get("description"), 200).replace("\n", " ").strip(),
            "vendor": optional_text(b.get("vendor"), 120).replace("\n", " ").strip(), "spent_on": day.isoformat()}


def expense_label(v: Any) -> str:
    return (v["description"] or v["category"])[:80]


def expense_report(conn: sqlite3.Connection, bid: str, start: dt.date, end: dt.date, category: str = "", search: str = "",
                   limit: int | None = None) -> dict[str, Any]:
    """Expenses between two dates (money in kobo). `total`/`items` follow the filters; `period_total` and `by_category` do not."""
    a, z = start.isoformat(), end.isoformat()
    where, args = "business_id=? AND spent_on BETWEEN ? AND ?", [bid, a, z]
    if category:
        where += " AND category=?"
        args.append(category)
    if search:
        like = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where += " AND (description LIKE ? ESCAPE '\\' OR vendor LIKE ? ESCAPE '\\' OR category LIKE ? ESCAPE '\\')"
        args += [like, like, like]
    cap = limit if limit is not None else MAX_EXPORT_EXPENSES
    rows = conn.execute(
        f"SELECT * FROM expenses WHERE {where} ORDER BY spent_on DESC, created_at DESC LIMIT ?", (*args, cap + 1)).fetchall()
    truncated = len(rows) > cap
    rows = rows[:cap]
    agg = conn.execute(f"SELECT COALESCE(SUM(amount),0) t, COUNT(*) c FROM expenses WHERE {where}", args).fetchone()
    by_cat = [dict(r) for r in conn.execute(
        "SELECT category, SUM(amount) total, COUNT(*) count FROM expenses WHERE business_id=? AND spent_on BETWEEN ? AND ? GROUP BY category ORDER BY total DESC",
        (bid, a, z))]
    period_total = sum(r["total"] for r in by_cat)
    days = (end - start).days + 1
    prev_end = start - dt.timedelta(days=1)
    prev_start = prev_end - dt.timedelta(days=days - 1)
    prev_total = conn.execute("SELECT COALESCE(SUM(amount),0) FROM expenses WHERE business_id=? AND spent_on BETWEEN ? AND ?",
                              (bid, prev_start.isoformat(), prev_end.isoformat())).fetchone()[0]
    sales = conn.execute(
        "SELECT COALESCE(SUM(total),0) s, COALESCE(SUM(estimated_gross_profit),0) p FROM orders "
        "WHERE business_id=? AND status='completed' AND substr(order_date,1,10) BETWEEN ? AND ?", (bid, a, z)).fetchone()
    return {"start": a, "end": z, "rows": [dict(r) for r in rows], "truncated": truncated, "total": agg["t"], "count": agg["c"],
            "period_total": period_total, "by_category": by_cat, "prev_total": prev_total, "prev_start": prev_start.isoformat(),
            "prev_end": prev_end.isoformat(), "sales": sales["s"], "gross_profit": sales["p"], "net_profit": sales["p"] - period_total}


def expense_total(conn: sqlite3.Connection, bid: str, a: str, z: str) -> int:
    return conn.execute("SELECT COALESCE(SUM(amount),0) FROM expenses WHERE business_id=? AND spent_on BETWEEN ? AND ?", (bid, a, z)).fetchone()[0]


def expenses_csv(data: dict[str, Any]) -> bytes:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(["Date", "Category", "Description", "Paid to", "Amount (NGN)"])
    for r in data["rows"]:
        w.writerow([r["spent_on"], _csv_text(r["category"]), _csv_text(r["description"]), _csv_text(r["vendor"]), f"{(r['amount'] or 0) / 100:.2f}"])
    return out.getvalue().encode("utf-8-sig")


def build_expenses_pdf(b: Any, data: dict[str, Any], logo_uri: str = "", branding: bool = True) -> bytes:
    period = f"{_pretty_date(data['start'])} – {_pretty_date(data['end'])}"
    kit = _Kit(b, logo_uri, f"Expenses {data['start']} to {data['end']}", "Expenses report", period, ["What the business spent"], branding)
    M, CW, R = kit.M, kit.CW, kit.R
    top = data["by_category"][0] if data["by_category"] else None
    net = data["net_profit"]
    kit.kpis([("Total spent", _n0(data["period_total"]), P_BAD if data["period_total"] else P_INK), ("Entries", f"{sum(c['count'] for c in data['by_category']):,}", P_INK),
              ("Biggest cost", top["category"] if top else "None", P_INK), ("Net profit", _n0(net), P_OK if net >= 0 else P_BAD)])
    kit.pg.text(M, kit.y - 4, f"Net profit is estimated profit on completed orders ({_n2(data['gross_profit'])}) minus expenses, for the same dates.", 8.5, False, P_MUTED)
    kit.y += 14

    kit.section("Where the money went")
    if not data["by_category"]:
        kit.pg.text(M, kit.y + 10, "No expenses recorded for these dates.", 9.5, False, P_MUTED)
        kit.y += 26
    else:
        top_value = max(1, data["by_category"][0]["total"])
        total = max(1, data["period_total"])
        name_w = CW - 210
        cols = [("Category", M + 8, "l"), ("Share", R - 110, "r"), ("Spent", R - 8, "r")]
        kit.table_head(cols)
        for r in data["by_category"]:
            if kit.need(32):
                kit.table_head(cols)
            p, yy = kit.pg, kit.y
            p.text(M + 8, yy + 14, pdf_fit(r["category"], 10, False, name_w), 10, False, P_INK)
            p.text(R - 110, yy + 14, f"{r['total'] * 100 / total:.0f}%", 10, False, P_INK, "r")
            p.text(R - 8, yy + 14, _n2(r["total"]), 10, True, P_INK, "r")
            p.rrect(M + 8, yy + 21, name_w, 3.5, 1.75, fill=P_LINE)
            p.rrect(M + 8, yy + 21, max(3.0, name_w * r["total"] / top_value), 3.5, 1.75, fill=P_BRAND)
            kit.y = yy + 31
        kit.y += 10

    rows = data["rows"][:MAX_PDF_ORDER_ROWS]
    kit.section("Every expense", f"{data['count']:,} entr{'ies' if data['count'] != 1 else 'y'}")
    if not rows:
        kit.pg.text(M, kit.y + 10, "Nothing to list.", 9.5, False, P_MUTED)
        kit.y += 24
    else:
        c_cat, c_desc, c_amt = M + 76, M + 196, R - 8
        cols = [("Date", M + 8, "l"), ("Category", c_cat, "l"), ("Details", c_desc, "l"), ("Amount", c_amt, "r")]
        kit.table_head(cols)
        for n, r in enumerate(rows):
            if kit.need(22):
                kit.table_head(cols)
            p, yy = kit.pg, kit.y
            if n % 2:
                p.rrect(M, yy, CW, 19, 3, fill="#f8f9fd", layer="bg")
            detail = r["description"] or ""
            if r["vendor"]:
                detail = (detail + "  ·  " if detail else "") + r["vendor"]
            p.text(M + 8, yy + 13, _pretty_date(r["spent_on"]), 8.5, False, P_MUTED)
            p.text(c_cat, yy + 13, pdf_fit(r["category"], 8.5, False, c_desc - c_cat - 8), 8.5, False, P_INK)
            p.text(c_desc, yy + 13, pdf_fit(detail, 8.5, False, c_amt - c_desc - 90), 8.5, False, P_INK)
            p.text(c_amt, yy + 13, _n2(r["amount"]), 8.5, True, P_INK, "r")
            kit.y = yy + 19
        if data["count"] > len(rows):
            kit.need(30)
            kit.pg.text(M, kit.y + 20, f"Showing the latest {len(rows):,} of {data['count']:,} entries. Download the spreadsheet for the full list.", 8.5, False, P_MUTED)
    return kit.finish()


def backup_zip(conn: sqlite3.Connection, biz: Any) -> bytes:
    """Everything the business has recorded, as spreadsheets in one zip. Money is in naira."""
    bid = biz["id"]
    mny = lambda k: f"{(k or 0) / 100:.2f}"  # noqa: E731
    txt = _csv_text

    def sheet(header: list[str], rows: Iterable[Iterable[Any]]) -> bytes:
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\r\n")
        w.writerow(header)
        for r in rows:
            w.writerow(list(r))
        return out.getvalue().encode("utf-8-sig")

    files: dict[str, bytes] = {}
    files["customers.csv"] = sheet(["Name", "Phone", "Email", "Address", "Notes", "Added"], (
        [txt(r["full_name"]), txt(r["phone"]), txt(r["email"]), txt(r["address"]), txt(r["notes"]), str(r["created_at"])[:10]]
        for r in conn.execute("SELECT * FROM customers WHERE business_id=? ORDER BY full_name", (bid,))))
    files["products.csv"] = sheet(["Name", "Category", "SKU", "Selling price (NGN)", "Cost price (NGN)", "In stock", "Low-stock alert at", "Active", "Description"], (
        [txt(r["name"]), txt(r["category"]), txt(r["sku"]), mny(r["selling_price"]), mny(r["cost_price"]), r["stock_quantity"], r["low_stock_threshold"],
         "yes" if r["active"] else "no", txt(r["description"])]
        for r in conn.execute("SELECT * FROM products WHERE business_id=? ORDER BY name", (bid,))))
    files["orders.csv"] = sheet(["Order number", "Date", "Customer", "Status", "Subtotal (NGN)", "Discount (NGN)", "Correction (NGN)", "Total (NGN)", "Paid (NGN)",
                                "Balance (NGN)", "Payment method", "Estimated profit (NGN)", "Notes"], (
        [txt(r["order_number"]), str(r["order_date"])[:10], txt(r["customer"]), r["status"], mny(r["subtotal"]), mny(r["discount"]), mny(r["adjustment"]),
         mny(r["total"]), mny(r["amount_paid"]), mny(r["balance"]), txt(r["payment_method"]), mny(r["estimated_gross_profit"]), txt(r["notes"])]
        for r in conn.execute(
            "SELECT o.*, COALESCE(c.full_name,'Walk-in customer') customer FROM orders o LEFT JOIN customers c ON c.id=o.customer_id "
            "WHERE o.business_id=? ORDER BY o.order_date DESC, o.created_at DESC", (bid,))))
    files["order-items.csv"] = sheet(["Order number", "Product", "Quantity", "Unit price (NGN)", "Unit cost (NGN)", "Line total (NGN)"], (
        [txt(r["order_number"]), txt(r["product_name"]), r["quantity"], mny(r["unit_price"]), mny(r["unit_cost"]), mny(r["line_total"])]
        for r in conn.execute(
            "SELECT o.order_number, oi.* FROM order_items oi JOIN orders o ON o.id=oi.order_id WHERE oi.business_id=? ORDER BY o.order_date DESC, o.order_number", (bid,))))
    files["payments.csv"] = sheet(["Order number", "Customer", "Date paid", "Amount (NGN)", "Method", "Note"], (
        [txt(r["order_number"]), txt(r["customer"]), str(r["paid_at"])[:10], mny(r["amount"]), txt(r["payment_method"]), txt(r["note"])]
        for r in conn.execute(
            "SELECT p.*, o.order_number, COALESCE(c.full_name,'Walk-in customer') customer FROM payments p JOIN orders o ON o.id=p.order_id "
            "LEFT JOIN customers c ON c.id=p.customer_id WHERE p.business_id=? ORDER BY p.paid_at DESC", (bid,))))
    files["debts.csv"] = sheet(["Order number", "Customer", "Due date", "Original amount (NGN)", "Paid (NGN)", "Still owed (NGN)", "Status"], (
        [txt(r["order_number"]), txt(r["customer"]), r["due_date"] or "", mny(r["original_amount"]), mny(r["amount_paid"]), mny(r["remaining_balance"]), r["status"]]
        for r in conn.execute(
            "SELECT d.*, o.order_number, COALESCE(c.full_name,'Walk-in customer') customer FROM debts d JOIN orders o ON o.id=d.order_id "
            "LEFT JOIN customers c ON c.id=d.customer_id WHERE d.business_id=? ORDER BY d.due_date", (bid,))))
    files["expenses.csv"] = sheet(["Date", "Category", "Description", "Paid to", "Amount (NGN)"], (
        [r["spent_on"], txt(r["category"]), txt(r["description"]), txt(r["vendor"]), mny(r["amount"])]
        for r in conn.execute("SELECT * FROM expenses WHERE business_id=? ORDER BY spent_on DESC", (bid,))))

    def history_rows() -> Iterable[list[Any]]:
        for r in conn.execute("SELECT * FROM audit_log WHERE business_id=? ORDER BY seq", (bid,)):
            try:
                ch = json.loads(r["changes"] or "[]")
            except ValueError:
                ch = []
            parts = []
            for c in ch:
                if c.get("kind") == "money":
                    a, z = mny(c.get("from")), mny(c.get("to"))
                else:
                    a, z = c.get("from"), c.get("to")
                parts.append(f"{c.get('label')}: {a} -> {z}")
            yield [r["seq"], str(r["created_at"]), txt(r["actor"]), AUDIT_TYPE_LABELS.get(r["entity_type"], r["entity_type"]), txt(r["entity_label"]),
                   AUDIT_ACTION_LABELS.get(r["action"], r["action"]), txt(r["summary"]), txt("; ".join(str(p) for p in parts)), txt(r["reason"]), r["entry_hash"]]
    files["edit-history.csv"] = sheet(["No.", "When (UTC)", "Who", "What", "Record", "Action", "Summary", "Changes", "Reason", "Tamper-check code"], history_rows())
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    files["READ-ME.txt"] = (
        f"{biz['name']} - backup made {stamp}\r\n\r\n"
        "Every file opens in Excel or Google Sheets. Money is in naira (NGN). Dates are YYYY-MM-DD.\r\n"
        "customers.csv, products.csv, orders.csv, order-items.csv, payments.csv, debts.csv, expenses.csv hold your records as they are now.\r\n"
        "edit-history.csv is the full edit history: every change, who made it, the old and new values and the reason given.\r\n"
        "Keep this file somewhere safe. Oja Loom cannot restore a backup for you; it is your own copy of your records.\r\n").encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def qr_svg(url: str, label: str = "QR code") -> str:
    """Inline SVG of a QR code for a web page (no image request, works under the page's strict CSP)."""
    try:
        m = qr_matrix(url, "M")
    except ValueError:
        return ""
    n, q = len(m), 2
    size = n + 2 * q
    d: list[str] = []
    for r, row in enumerate(m):
        c = 0
        while c < n:
            if row[c]:
                s = c
                while c < n and row[c]:
                    c += 1
                d.append(f"M{s + q} {r + q}h{c - s}v1h-{c - s}z")
            else:
                c += 1
    return (f'<svg class="qr" viewBox="0 0 {size} {size}" shape-rendering="crispEdges" role="img" aria-label="{html.escape(label, quote=True)}">'
            f'<rect width="{size}" height="{size}" fill="#fff"/><path d="{"".join(d)}" fill="#0f1430"/></svg>')


def friendly_page(title: str, text: str, links: Iterable[tuple[str, str]] = ()) -> str:
    """A plain, readable page for public links that cannot be shown (instead of a raw JSON error)."""
    e = html.escape
    nav = "".join(f"<a href='{e(h, quote=True)}'>{e(t)}</a> " for t, h in links)
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<meta name=robots content='noindex,nofollow'><title>{e(title)}</title></head>"
        "<body style='font:16px/1.5 system-ui,sans-serif;margin:12vh auto;max-width:440px;padding:0 20px;color:#0f1430'>"
        f"<h1 style='font-size:24px'>{e(title)}</h1><p style='color:#656d8a'>{e(text)}</p><p>{nav}</p></body></html>"
    )


RECEIPT_SHARE_JS = r"""
(function(){
  var wa=document.getElementById("wa"),ml=document.getElementById("mail");
  var first=wa||ml;if(!first)return;
  var cache=null;
  var canShare=typeof navigator.share==="function"&&typeof navigator.canShare==="function"&&typeof File==="function";
  function load(){
    if(!cache)cache=fetch(first.dataset.pdf,{credentials:"same-origin"}).then(function(r){if(!r.ok)throw new Error("pdf");return r.blob()});
    return cache;
  }
  if(canShare)load().catch(function(){cache=null});
  function save(blob,name){
    var u=URL.createObjectURL(blob),a=document.createElement("a");
    a.href=u;a.download=name;document.body.appendChild(a);a.click();a.remove();
    setTimeout(function(){URL.revokeObjectURL(u)},8000);
  }
  function note(msg){var n=document.getElementById("wa-note");if(n){n.textContent=msg;n.hidden=false}}
  function open(url){var w=window.open(url,"_blank");if(!w)return false;try{w.opener=null}catch(x){}return true}
  function mailto(b){var a=document.createElement("a");a.href=b.dataset.mailto;document.body.appendChild(a);a.click();a.remove()}
  function fallback(b,blob,channel){
    save(blob,b.dataset.name);
    if(channel==="mail"){mailto(b);note("PDF saved to your downloads. Attach it in the email that just opened.")}
    else if(open(b.dataset.chat))note("PDF saved to your downloads. Attach it in the WhatsApp chat that just opened.");
    else note("PDF saved to your downloads. Open WhatsApp and attach it.");
  }
  function wire(b,channel){
    if(!b)return;
    b.addEventListener("click",function(){
      var d=b.closest("details");if(d)d.open=false;
      b.disabled=true;
      load().then(function(blob){
        var file=new File([blob],b.dataset.name,{type:"application/pdf"});
        if(canShare&&navigator.canShare({files:[file]})){
          return navigator.share({files:[file],title:b.dataset.title,text:b.dataset.text}).catch(function(e){
            if(e&&e.name==="AbortError")return;
            fallback(b,blob,channel);
          });
        }
        fallback(b,blob,channel);
      }).catch(function(){cache=null;if(channel==="mail")mailto(b);else open(b.dataset.link)}).then(function(){b.disabled=false});
    });
  }
  wire(wa,"wa");wire(ml,"mail");
})();
"""


TERMS_UPDATED = "9 October 2026"
_EMAIL_RE = re.compile(r"^[^@\s<>\"']+@[^@\s<>\"']+\.[^@\s<>\"']+$")


def terms_sections() -> list[tuple[str, list[Any]]]:
    """(heading, [paragraph | ("ul", [bullets])]). Plain text: it is escaped when the page is built."""
    op = OPERATOR_NAME or "the operator of this Oja Loom service"
    price = f"₦{PRO_PRICE_NAIRA:,}"
    reach = (f"email {SUPPORT_EMAIL}" if SUPPORT_EMAIL else "use the contact details you were given when you signed up")
    return [
        ("About these Terms", [
            f"Oja Loom is business software for small sellers: orders, stock, customers, debts, receipts, reports and an optional public storefront. It is run by {op}. In these Terms, “we” and “us” mean the operator of this Oja Loom service, and “you” means the person or business that signs up.",
            "By creating an account, or by using Oja Loom, you agree to these Terms. If you do not agree, please do not use Oja Loom. If you sign up for a business, you confirm that you are allowed to agree on its behalf.",
        ]),
        ("Your account", [
            ("ul", [
                "You must be at least 18 years old, or old enough to make binding contracts where you live.",
                "Give true details when you sign up and keep them up to date.",
                "Keep your password private. You are responsible for what happens under your account. If you think someone else has got in, change your password and use “Sign out of all devices” in Settings.",
            ]),
        ]),
        ("Your business data", [
            "The products, customers, orders, payments, notes and images you put into Oja Loom belong to you. We do not sell them.",
            "You allow us to store and process that data only so that Oja Loom can work for you: showing it back to you, producing receipts, PDFs and reports, and showing the public pages you choose to switch on.",
            "You are responsible for the data you enter. That means it is accurate, that you are allowed to hold your customers’ details (name, phone number, address), and that you use them lawfully, including under the Nigeria Data Protection Act 2023 where it applies to you. Tell your customers how you use their details.",
        ]),
        ("What you must not do", [
            ("ul", [
                "Use Oja Loom for anything illegal, fraudulent or misleading, including making receipts or invoices to deceive someone.",
                "Upload content you have no right to use, or content that is unlawful, abusive or harmful.",
                "Try to break into, probe, overload or get around the security or plan limits of Oja Loom, or collect data from it with automated tools.",
                "Pretend to be someone else, or resell access to Oja Loom without our written permission.",
            ]),
        ]),
        ("Records, edit history and receipts", [
            "Oja Loom keeps an edit history of changes to money, stock, customers and settings. Entries cannot be edited or deleted from inside the app, so corrections are added on top of what was there and never erase it. When you correct an amount owed or a payment, you must give a reason, and the old and new figures are kept. This protects you and your customers.",
            "Receipts, invoices, statements and reports are produced from what you entered. They are bookkeeping aids. They are not tax, legal or accounting advice, and you remain responsible for your own tax and regulatory duties.",
            "Oja Loom is not a bank or a payment processor. It does not collect money from your customers or hold it for you. A payment you record is your own note of money you received elsewhere.",
        ]),
        ("Public pages and sharing", [
            "A receipt link is not listed anywhere, but anyone who has the link can open it, so share it with care. Your storefront, if you switch it on, is public. You can switch it off in Settings.",
            "When you send a receipt or message through WhatsApp or another app, you are sharing it through that service, and its own terms apply. We are not connected with WhatsApp.",
        ]),
        ("Plans, trial and payment", [
            ("ul", [
                "Every new account starts with a 14-day free trial of every feature.",
                f"After the trial there is a free plan. It includes up to {FREE_MAX_PRODUCTS} products, {FREE_MAX_ORDERS_PER_MONTH} orders a month, the last {FREE_ACTIVITY_DAYS} days of edit history and reports of up to {FREE_REPORT_DAYS} days.",
                f"Oja Loom Pro costs {price} for every {PRO_PERIOD_DAYS} days and removes those limits and adds PDF downloads. It does not renew by itself: you pay, or enter an activation code, when you want more time. New days are added on top of any days you have left.",
                "You can pay through Paystack, or with an activation code from us. Card and bank details are handled by Paystack. We never see or store them.",
                "Once Pro days have been added they are not refundable, unless the law says otherwise or we charged you by mistake. If we did, we will put it right quickly.",
                "If Pro ends you keep your data. Pro features lock and the free limits apply. We do not delete your records because a plan ended.",
                "We may change prices or limits. We will show a notice in the app at least 14 days before a change, and days you have already paid for are not affected.",
                "Free days from referrals are a courtesy. We may withhold them if the referral scheme is abused, for example by referring yourself.",
            ]),
        ]),
        ("Availability and backups", [
            "We work to keep Oja Loom running, but we cannot promise it will always be available or free of errors. It is provided “as is”.",
            "Keep your own copies of records that matter to you. Spreadsheet and PDF downloads are there for that.",
        ]),
        ("Ending your use", [
            "You can stop using Oja Loom at any time. To have your account deleted, ask us using the contact details below. We may need to keep some records where the law or the security of the service requires it.",
            "We may suspend or close an account that breaks these Terms or puts other people or the service at risk. Where we reasonably can, we will tell you first and give you a chance to export your data.",
        ]),
        ("Our responsibility to you", [
            "Nothing in these Terms limits any right or liability that the law does not allow to be limited, such as liability for fraud, or for death or injury caused by negligence.",
            "Apart from that, and as far as the law allows, we are not responsible for indirect or knock-on losses (for example lost sales, profit or goodwill), for losses caused by figures you entered, for a customer who does not pay, or for outages of services we do not run, such as the internet, WhatsApp or Paystack.",
            "Our total responsibility for any one claim is limited to what you paid us for Oja Loom in the three months before the claim.",
        ]),
        ("Privacy", [
            ("ul", [
                "What we hold: your name, email address and phone number; your business details; the records you enter; and basic technical data such as the IP address recorded in security and edit-history entries.",
                "Cookies: we use one essential cookie to keep you signed in. There are no advertising or tracking cookies.",
                "Passwords are stored only as a salted hash. We cannot read them.",
                "We use your data to run, secure and support Oja Loom and to process payments for Pro. We do not sell personal data.",
                "You can ask us to show you, correct or delete the personal data we hold about you, using the contact details below.",
            ]),
        ]),
        ("Changes to these Terms", [
            "We may update these Terms. If a change matters, we will ask you to accept the new version before you carry on. The version and date are at the bottom of this page.",
        ]),
        ("Law and contact", [
            "These Terms are governed by the laws of the Federal Republic of Nigeria, and the courts of Nigeria can hear any dispute. If you have a complaint, please contact us first so that we can try to put it right.",
            f"Questions about these Terms or your data: {reach}.",
        ]),
    ]


TERMS_CSS = """
:root{--bg:#f3f4f9;--surface:#fff;--line:#e5e8f1;--ink:#0f1430;--ink2:#2a3150;--muted:#626a88;--brand:#2c3a9c;--soft:#e8ebfa;--gold:#f2b01e;--gold-soft:#fff3d3;--side:#151c4a}
@media(prefers-color-scheme:dark){:root{--bg:#0b0f2c;--surface:#131943;--line:#232b5f;--ink:#eceffd;--ink2:#c8cef0;--muted:#98a0cf;--brand:#8f9dff;--soft:#1d2662;--gold-soft:#3a3010}}
*{box-sizing:border-box}
html{font:16px/1.65 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;background:var(--bg);color:var(--ink);-webkit-text-size-adjust:100%}
body{margin:0}
a{color:var(--brand)}
:focus-visible{outline:3px solid var(--gold);outline-offset:2px;border-radius:6px}
.top{background:var(--side);color:#fff}
.top-in{max-width:820px;margin:0 auto;padding:14px 20px;display:flex;align-items:center;justify-content:space-between;gap:12px}
.brand{display:flex;align-items:center;gap:10px;font-weight:800;font-size:18px;letter-spacing:-.03em;color:#fff;text-decoration:none}
.brand svg{width:30px;height:30px}
.back{color:#fff;text-decoration:none;font-weight:700;background:rgba(255,255,255,.14);padding:9px 14px;border-radius:10px;white-space:nowrap}
.back:hover{background:rgba(255,255,255,.24)}
main{max-width:820px;margin:0 auto;padding:34px 20px 70px}
h1{font-size:clamp(28px,5vw,38px);letter-spacing:-.035em;line-height:1.15;margin:0 0 8px}
.meta{color:var(--muted);margin:0 0 26px;font-size:14.5px}
.short{background:var(--gold-soft);border-radius:16px;padding:18px 22px;margin:0 0 28px}
.short h2{margin:0 0 8px;font-size:16px}
.short ul{margin:0;padding-left:20px}
.short li{margin:4px 0}
.toc{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:16px 22px;margin:0 0 34px}
.toc h2{margin:0 0 8px;font-size:15px;color:var(--muted);font-weight:700}
.toc ol{margin:0;padding-left:22px;columns:2;column-gap:32px}
.toc li{margin:3px 0;break-inside:avoid}
section{margin:0 0 30px;scroll-margin-top:16px}
h2{font-size:20px;letter-spacing:-.02em;margin:0 0 10px;display:flex;gap:12px;align-items:baseline}
h2 span{flex:none;width:28px;height:28px;border-radius:50%;background:var(--soft);color:var(--brand);display:inline-grid;place-items:center;font-size:13.5px;font-weight:800;transform:translateY(-2px)}
p{margin:0 0 12px;color:var(--ink2)}
ul{margin:0 0 12px;padding-left:22px;color:var(--ink2)}
li{margin:6px 0}
.foot{border-top:1px solid var(--line);padding-top:20px;color:var(--muted);font-size:14px;display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap}
@media(max-width:640px){.toc ol{columns:1}main{padding-top:26px}.back{padding:8px 12px}}
@media(max-width:420px){.top-in{flex-wrap:wrap;row-gap:10px}.back{font-size:14px}}
@media print{.top,.toc,.back{display:none}html{background:#fff}main{padding:0}}
"""


def terms_html(nonce: str, signed_in: bool) -> str:
    e = html.escape
    back = html.escape(app_link("/#/settings" if signed_in else "/"), quote=True)
    back_text = "← Back to Oja Loom"
    back_home = html.escape(app_link("/"), quote=True)
    toc, body = [], []
    for i, (title, blocks) in enumerate(terms_sections(), 1):
        toc.append(f'<li><a href="#s{i}">{e(title)}</a></li>')
        inner = ""
        for blk in blocks:
            if isinstance(blk, tuple):
                inner += "<ul>" + "".join(f"<li>{e(x)}</li>" for x in blk[1]) + "</ul>"
            else:
                inner += f"<p>{e(blk)}</p>"
        body.append(f'<section id="s{i}"><h2><span>{i}</span>{e(title)}</h2>{inner}</section>')
    price = f"₦{PRO_PRICE_NAIRA:,}"
    short = [
        "Your records are yours. We do not sell them.",
        "Every change to money, stock and customers is written to an edit history that nobody can quietly rewrite.",
        "You are responsible for what you enter and for your own tax duties. Oja Loom is a bookkeeping tool, not an accountant, a bank or a payment processor.",
        f"Pro costs {price} for {PRO_PERIOD_DAYS} days and never renews by itself.",
        "Keep your own backups.",
    ]
    op = e(OPERATOR_NAME or "the operator of this Oja Loom service")
    mail = ""
    if SUPPORT_EMAIL and _EMAIL_RE.match(SUPPORT_EMAIL):
        mail = f' · <a href="mailto:{e(SUPPORT_EMAIL, quote=True)}">{e(SUPPORT_EMAIL)}</a>'
    if SUPPORT_WHATSAPP:
        mail += f' · <a href="https://wa.me/{e(SUPPORT_WHATSAPP, quote=True)}" rel="noopener noreferrer">WhatsApp support</a>'
    mark = ('<svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="9" fill="#f2b01e"/>'
            '<circle cx="16" cy="16" r="6.8" fill="none" stroke="#151c4a" stroke-width="4.6"/></svg>')
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark">'
        '<title>Terms of Service · Oja Loom</title>'
        f'<style nonce="{nonce}">{TERMS_CSS}</style></head><body>'
        f'<header class="top"><div class="top-in"><a class="brand" href="{back_home}">{mark}Oja Loom</a>'
        f'<a class="back" href="{back}">{back_text}</a></div></header>'
        f'<main><h1>Terms of Service</h1><p class="meta">Version {e(TERMS_VERSION)} · Last updated {e(TERMS_UPDATED)} · Run by {op}</p>'
        f'<div class="short"><h2>The short version</h2><ul>{"".join(f"<li>{e(x)}</li>" for x in short)}</ul>'
        '<p style="margin:10px 0 0;font-size:14px">This summary is only a guide. The full Terms below are what count.</p></div>'
        f'<nav class="toc" aria-label="Contents"><h2>Contents</h2><ol>{"".join(toc)}</ol></nav>'
        f'{"".join(body)}'
        f'<div class="foot"><span>Oja Loom Terms of Service, version {e(TERMS_VERSION)}{mail}</span><a href="{back}">{back_text}</a></div>'
        '</main></body></html>'
    )


def user_json(u: Any) -> dict[str, Any]:
    d = dict(u)
    d["terms_ok"] = (d.get("terms_version") or "") == TERMS_VERSION
    return d


class AppError(Exception):
    def __init__(self, message: str, status: int = 400, extra: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.extra = extra or {}


def app_link(path: str = "") -> str:
    """A link into the web app, which lives on its own site (see FRONTEND_URL)."""
    return FRONTEND_URL + (path if path.startswith(("/", "#")) else "/" + path)


# --------------------------------------------------------------------------------------
# WhatsApp Business Cloud API: deliver a PDF straight into a customer's WhatsApp (optional)
# --------------------------------------------------------------------------------------
WA_ERRORS = {
    131026: "WhatsApp could not deliver to that number. It may not be on WhatsApp.",
    131030: "That number is not allowed to receive messages from this WhatsApp sender yet.",
    131056: "Too many messages to that number in a short time. Try again later.",
    130429: "WhatsApp is busy right now. Try again in a minute.",
}


def wa_enabled() -> bool:
    return bool(WA_TOKEN and WA_PHONE_ID)


def wa_multipart(fields: dict[str, str], file_field: str, filename: str, content: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = "----ojaloom" + secrets.token_hex(16)
    out = io.BytesIO()
    for key, value in fields.items():
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{safe}"\r\nContent-Type: {content_type}\r\n\r\n'.encode())
    out.write(content)
    out.write(f"\r\n--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


def wa_call(path: str, json_body: dict[str, Any] | None = None, raw: tuple[bytes, str] | None = None) -> dict[str, Any]:
    url = f"{WA_GRAPH_BASE}/{WA_GRAPH_VERSION}/{WA_PHONE_ID}/{path}"
    data, ctype = (json.dumps(json_body).encode(), "application/json") if json_body is not None else raw  # type: ignore[misc]
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Authorization": "Bearer " + WA_TOKEN, "Content-Type": ctype, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            err = (json.loads(exc.read().decode("utf-8")) or {}).get("error") or {}
        except Exception:
            err = {}
        code = int(err.get("code") or 0)
        # the operator needs the code; the shop owner only needs to know what to do next. Never log the token or the phone number.
        print(f"[whatsapp] send failed: http {exc.code}, code {code}, trace {err.get('fbtrace_id', '-')}", file=sys.stderr)
        raise AppError(WA_ERRORS.get(code, "WhatsApp delivery is not available right now."), 422 if code in WA_ERRORS else 502)
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise AppError("Could not reach WhatsApp. Please try again in a moment.", 502)


def wa_param(value: Any, limit: int = 300) -> str:
    """Template variables may not hold line breaks, tabs or long runs of spaces, and may not be empty."""
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit] or "-"


def wa_send_pdf(to_phone: str, template: str, pdf: bytes, filename: str, params: list[str]) -> str:
    """Upload the PDF to WhatsApp, then send it as the header of an approved template message. Returns the message id."""
    media = wa_call("media", raw=wa_multipart({"messaging_product": "whatsapp", "type": "application/pdf"}, "file", filename, pdf, "application/pdf"))
    media_id = str(media.get("id") or "")
    if not media_id:
        raise AppError("WhatsApp did not accept the PDF.", 502)
    res = wa_call("messages", json_body={
        "messaging_product": "whatsapp", "recipient_type": "individual", "to": to_phone, "type": "template",
        "template": {"name": template, "language": {"code": WA_TEMPLATE_LANG}, "components": [
            {"type": "header", "parameters": [{"type": "document", "document": {"id": media_id, "filename": filename}}]},
            {"type": "body", "parameters": [{"type": "text", "text": wa_param(p)} for p in params]},
        ]},
    })
    msgs = res.get("messages") or []
    return str((msgs[0] or {}).get("id") or "") if msgs else ""


def production_problems() -> list[str]:
    """Settings that must be right before the server may run on the internet."""
    bad: list[str] = []
    if not FRONTEND_URL.startswith("https://"):
        bad.append("OJALOOM_FRONTEND_URL must be the https address of the web app, e.g. https://app.example.com")
    if not PUBLIC_API_URL.startswith("https://"):
        bad.append("OJALOOM_PUBLIC_API_URL must be this server's public https address, e.g. https://api.example.com")
    if not ALLOWED_ORIGINS or any(not o.startswith("https://") for o in ALLOWED_ORIGINS):
        bad.append("OJALOOM_ALLOWED_ORIGINS must list only https origins (normally just the web app's address)")
    if not TRUST_PROXY:
        bad.append("start with --trust-proxy: in production the server sits behind your HTTPS proxy")
    if not SECURE_COOKIES:
        bad.append("start with --secure-cookies so the login cookie is only ever sent over https")
    if PAYSTACK_BASE != "https://api.paystack.co":
        bad.append("OJALOOM_PAYSTACK_BASE must not be changed in production")
    if WA_GRAPH_BASE != "https://graph.facebook.com":
        bad.append("OJALOOM_WA_GRAPH_BASE must not be changed in production")
    host = urllib.parse.urlparse(FRONTEND_URL).hostname or ""
    if host.endswith(".github.io"):
        bad.append("github.io is a public suffix, so browsers will not send the login cookie between it and your API. Use a custom domain, e.g. app.example.com + api.example.com")
    elif PUBLIC_API_URL:
        api_host = urllib.parse.urlparse(PUBLIC_API_URL).hostname or ""
        if ".".join(host.split(".")[-2:]) != ".".join(api_host.split(".")[-2:]):
            bad.append("the web app and the API must share one registrable domain (app.example.com and api.example.com), or the login cookie is not sent")
    return bad


_RECEIPT_TOKEN_RE = re.compile(r"/receipt/[A-Za-z0-9_-]+")
_HOST_RE = re.compile(r"^(?:[A-Za-z0-9.-]+|\[[0-9a-fA-F:]+\])(?::\d{1,5})?$")
BUSINESS_STATUSES = {"pending", "confirmed", "processing", "ready", "completed", "cancelled"}


class OjaHandler(BaseHTTPRequestHandler):
    server_version = "Oja Loom"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = REQUEST_TIMEOUT  # drop slow or stalled connections

    _head = False
    _body_read = True
    _user: Any = None

    # ---- logging -----------------------------------------------------------------------
    def log_message(self, fmt: str, *args: Any) -> None:
        line = _RECEIPT_TOKEN_RE.sub("/receipt/...", fmt % args)  # receipt links are secrets
        sys.stdout.write("[%s] %s - %s\n" % (dt.datetime.now().strftime("%H:%M:%S"), self.address_string(), line))

    # ---- request facts -----------------------------------------------------------------
    def client_ip(self) -> str:
        if TRUST_PROXY:
            forwarded = self.headers.get("X-Forwarded-For", "")
            if forwarded:
                last = forwarded.split(",")[-1].strip()  # the entry our own proxy appended
                if last:
                    return last[:64]
        return self.client_address[0]

    def is_https(self) -> bool:
        if SECURE_COOKIES:
            return True
        return TRUST_PROXY and self.headers.get("X-Forwarded-Proto", "").split(",")[0].strip().lower() == "https"

    def base_url(self) -> str:
        if PUBLIC_API_URL:
            return PUBLIC_API_URL  # never build links out of a Host header a visitor could have faked
        host = self.headers.get("X-Forwarded-Host", "") if TRUST_PROXY else ""
        host = host.split(",")[0].strip() or self.headers.get("Host", "")
        if not _HOST_RE.match(host):
            host = f"127.0.0.1:{DEFAULT_PORT}"
        return f"{'https' if self.is_https() else 'http'}://{host}"

    def check_origin(self) -> None:
        """Browsers always send Origin on cross-site writes; refuse anything that is not us."""
        origin = self.headers.get("Origin")
        if not origin:
            return
        if origin.rstrip("/").lower() in ALLOWED_ORIGINS:
            return  # the web app, on its own address
        allowed = {(self.headers.get("Host") or "").lower()}
        if TRUST_PROXY and self.headers.get("X-Forwarded-Host"):
            allowed.add(self.headers["X-Forwarded-Host"].split(",")[0].strip().lower())
        try:
            netloc = urllib.parse.urlparse(origin).netloc.lower()
        except ValueError:
            netloc = ""
        if origin == "null" or netloc not in allowed:
            raise AppError("This request came from another website and was blocked.", 403)

    def cors_origin(self) -> str:
        """The caller's Origin when it is one of ours (the web app), else an empty string."""
        origin = (self.headers.get("Origin") or "").rstrip("/")
        return origin if origin and origin.lower() in ALLOWED_ORIGINS else ""

    # ---- responses ---------------------------------------------------------------------
    def security_headers(self, nonce: str | None = None) -> None:
        h = self.send_header
        h("X-Content-Type-Options", "nosniff")
        h("X-Frame-Options", "DENY")
        h("Referrer-Policy", "no-referrer")
        h("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        h("Cross-Origin-Opener-Policy", "same-origin")
        h("Cross-Origin-Resource-Policy", "same-site")  # the web app is another origin but the same site (app.example.com / api.example.com)
        h("Vary", "Origin")
        allowed = self.cors_origin()
        if allowed:
            h("Access-Control-Allow-Origin", allowed)
            h("Access-Control-Allow-Credentials", "true")
            h("Access-Control-Expose-Headers", "Content-Disposition")
        if nonce:
            csp = (
                f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
                "style-src-attr 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
                "form-action 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'"
            )
        else:
            csp = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        h("Content-Security-Policy", csp)
        if self.is_https():
            h("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    def send_bytes(
        self,
        data: bytes,
        status: int = 200,
        content_type: str = "application/octet-stream",
        headers: dict[str, str] | None = None,
        nonce: str | None = None,
        cache: str = "no-store",
    ) -> None:
        self.send_response(status)
        self.security_headers(nonce)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        if self.close_connection:
            self.send_header("Connection", "close")
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        if not self._head and status != 204:
            self.wfile.write(data)

    def send_html(self, text: str, status: int = 200, nonce: str | None = None, headers: dict[str, str] | None = None) -> None:
        self.send_bytes(text.encode("utf-8"), status, "text/html; charset=utf-8", headers, nonce)

    def send_json(self, obj: Any, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.send_bytes(
            json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            status,
            "application/json; charset=utf-8",
            headers,
        )

    def send_error_json(self, message: str, status: int, extra: dict[str, Any] | None = None) -> None:
        try:
            pending = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            pending = 1
        if pending > 0 and not self._body_read:
            self.close_connection = True  # unread body would corrupt the next request on this socket
        self.send_json({"error": message, **(extra or {})}, status)

    def json_body(self, limit: int = MAX_BODY) -> dict[str, Any]:
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            self.close_connection = True
            raise AppError("Chunked uploads are not supported.", 411)
        try:
            size = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            raise AppError("Invalid request size.", 400)
        if size < 0 or size > limit:
            raise AppError("Request is too large.", 413)
        self._body_read = True
        if size == 0:
            return {}
        raw = self.rfile.read(size)
        try:
            obj = json.loads(raw.decode("utf-8"))
        except Exception:
            raise AppError("Invalid JSON request.", 400)
        if not isinstance(obj, dict):
            raise AppError("JSON body must be an object.", 400)
        return obj

    # ---- sessions ----------------------------------------------------------------------
    def cookies(self) -> http.cookies.SimpleCookie:
        c = http.cookies.SimpleCookie()
        with contextlib.suppress(Exception):
            c.load(self.headers.get("Cookie", ""))
        return c

    def session(self) -> tuple[sqlite3.Row | None, sqlite3.Row | None]:
        token = self.cookies().get("ojaloom_session")
        if not token or not token.value or len(token.value) > 200:
            return None, None
        token_hash = hashlib.sha256(token.value.encode()).hexdigest()
        with db_connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE token_hash=? AND expires_at>?", (token_hash, iso_now())).fetchone()
            if not row:
                return None, None
            user = conn.execute("SELECT id,email,owner_name,created_at,terms_version,terms_accepted_at FROM users WHERE id=?", (row["user_id"],)).fetchone()
            return row, user

    def require_auth(self, write: bool = False) -> tuple[sqlite3.Row, sqlite3.Row, sqlite3.Row]:
        if write:
            self.check_origin()
        sess, user = self.session()
        if not sess or not user:
            raise AppError("Please log in to continue.", 401)
        if write:
            supplied = self.headers.get("X-CSRF-Token", "")
            if not supplied or not hmac.compare_digest(supplied, sess["csrf_token"]):
                raise AppError("Your session security token is missing or expired. Refresh the page and try again.", 403)
        with db_connect() as conn:
            biz = user_business(conn, user["id"])
            if not biz:
                raise AppError("No business is attached to this account.", 403)
        self._user = user
        return sess, user, biz

    def issue_session(self, user_id: str) -> tuple[str, str]:
        raw = secrets.token_urlsafe(36)
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        csrf = secrets.token_urlsafe(24)
        expires = utcnow() + dt.timedelta(days=SESSION_DAYS)
        with db_connect() as conn:
            conn.execute(
                "INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES(?,?,?,?,?)",
                (token_hash, user_id, csrf, expires.isoformat(timespec="seconds"), iso_now()),
            )
            conn.execute(  # keep only the newest sessions per user
                """DELETE FROM sessions WHERE user_id=? AND token_hash NOT IN
                   (SELECT token_hash FROM sessions WHERE user_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?)""",
                (user_id, user_id, MAX_SESSIONS_PER_USER),
            )
            if secrets.randbelow(25) == 0:
                conn.execute("DELETE FROM sessions WHERE expires_at < ?", (iso_now(),))
        return raw, csrf

    def drop_current_session(self) -> None:
        """Forget the session that came with this request (used on login/signup/logout)."""
        token = self.cookies().get("ojaloom_session")
        if token and token.value:
            with db_connect() as conn:
                conn.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.value.encode()).hexdigest(),))

    def cookie_header(self, raw_token: str, clear: bool = False) -> str:
        parts = [f"ojaloom_session={'deleted' if clear else raw_token}", "Path=/", "HttpOnly", "SameSite=Strict"]
        if clear:
            parts += ["Max-Age=0", "Expires=Thu, 01 Jan 1970 00:00:00 GMT"]
        else:
            parts.append(f"Max-Age={SESSION_DAYS * 86400}")
        if self.is_https():
            parts.append("Secure")
        return "; ".join(parts)

    # ---- dispatch ----------------------------------------------------------------------
    def dispatch(self, fn) -> None:
        self._body_read = False
        try:
            fn()
        except AppError as e:
            self.send_error_json(str(e), e.status, e.extra)
        except PermissionError as e:
            self.send_error_json(str(e), 403)
        except ValueError as e:
            self.send_error_json(str(e), 400)
        except sqlite3.IntegrityError as e:
            msg = "That value is already in use or conflicts with existing data."
            if "products.business_id, products.sku" in str(e):
                msg = "That SKU is already used by another product."
            elif "FOREIGN KEY" in str(e).upper():
                msg = "This record is still used elsewhere and cannot be changed that way."
            self.send_error_json(msg, 409)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except Exception:
            traceback.print_exc()
            self.send_error_json("Something went wrong on the server.", 500)

    def do_OPTIONS(self) -> None:
        if self.headers.get("Origin") and not self.cors_origin():
            self.send_response(403)  # a website we do not know is asking for permission: no CORS headers, so the browser says no
            self.security_headers()
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(204)
        self.security_headers()
        self.send_header("Allow", "GET, HEAD, POST, PUT, DELETE, OPTIONS")
        if self.cors_origin():
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, PUT, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-CSRF-Token, Accept")
            self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        self.dispatch(self.route_get)

    def do_HEAD(self) -> None:
        self._head = True
        self.dispatch(self.route_get)

    def do_POST(self) -> None:
        self.dispatch(lambda: self.route_write("POST"))

    def do_PUT(self) -> None:
        self.dispatch(lambda: self.route_write("PUT"))

    def do_DELETE(self) -> None:
        self.dispatch(lambda: self.route_write("DELETE"))

    # ---- GET routes --------------------------------------------------------------------
    def boot_payload(self) -> dict[str, Any]:
        """What the web app needs before anybody logs in."""
        return {"categories": list(DEFAULT_CATEGORIES), "minPassword": MIN_PASSWORD_LENGTH, "version": APP_VERSION,
                "referral": {"referred": REFERRED_BONUS_DAYS, "referrer": REFERRER_BONUS_DAYS, "max": MAX_REWARDED_REFERRALS},
                "share": {"whatsapp_direct": wa_enabled()}}

    def route_get(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        if path in ("/", "/index.html"):
            return self.send_bytes(b"", 302, "text/plain", {"Location": FRONTEND_URL + "/"})  # the web app lives on its own site
        if path == "/api/boot":
            return self.send_json(self.boot_payload())
        if path == "/terms":
            nonce = secrets.token_urlsafe(16)
            return self.send_html(terms_html(nonce, bool(self.session()[0])), nonce=nonce)
        if path == "/health":
            return self.send_json({"ok": True, "app": APP_NAME, "version": APP_VERSION})
        if path == "/favicon.ico":
            return self.send_bytes(b"", 204, "image/x-icon", cache="public, max-age=86400")
        if path == "/api/me":
            sess, user = self.session()
            if not sess or not user:
                return self.send_json({"user": None})
            with db_connect() as conn:
                biz = user_business(conn, user["id"])
                if not biz:
                    raise AppError("Business not found.", 404)
                return self.send_json({"user": user_json(user), "business": self.biz_json(biz), "csrf": sess["csrf_token"],
                                       "rewards": pending_rewards(conn, biz["id"])})
        if path == "/api/referral/check":
            return self.referral_check(qs)
        if path == "/api/referrals":
            _, _, biz = self.require_auth()
            return self.referrals_data(biz)
        if path == "/api/dashboard":
            _, user, biz = self.require_auth()
            return self.send_json(self.dashboard_data(user["id"], biz["id"]))
        if path == "/api/business":
            _, _, biz = self.require_auth()
            return self.send_json({"business": self.biz_json(biz)})
        if path == "/api/categories":
            _, _, biz = self.require_auth()
            with db_connect() as conn:
                return self.send_json({"items": categories_payload(conn, biz["id"]), "max": MAX_CUSTOM_CATEGORIES})
        if path == "/api/products":
            _, _, biz = self.require_auth()
            return self.send_json(self.products_data(biz["id"], qs))
        if path == "/api/customers":
            _, _, biz = self.require_auth()
            return self.send_json(self.customers_data(biz["id"], qs))
        if path == "/api/orders":
            _, _, biz = self.require_auth()
            return self.send_json(self.orders_data(biz["id"], qs))
        m = re.fullmatch(r"/api/orders/([^/]+)", path)
        if m:
            _, _, biz = self.require_auth()
            with db_connect() as conn:
                row = conn.execute("SELECT * FROM orders WHERE id=? AND business_id=?", (m.group(1), biz["id"])).fetchone()
                if not row:
                    raise AppError("Order not found.", 404)
                return self.send_json({"order": order_payload(conn, row, True)})
        if path == "/api/debts":
            _, _, biz = self.require_auth()
            return self.send_json(self.debts_data(biz["id"]))
        if path == "/api/receipts":
            _, _, biz = self.require_auth()
            return self.send_json(self.receipts_data(biz["id"]))
        if path == "/api/reports":
            _, _, biz = self.require_auth()
            return self.send_json(self.reports_data(biz, qs))
        if path == "/api/reports/export":
            _, user, biz = self.require_auth()
            return self.report_export(user, biz, qs)
        if path == "/api/activity":
            _, _, biz = self.require_auth()
            return self.send_json(self.activity_data(biz, qs))
        if path == "/api/activity/export":
            _, user, biz = self.require_auth()
            return self.activity_export(user, biz, qs)
        if path == "/api/plan":
            _, _, biz = self.require_auth()
            return self.send_json(self.plan_data(biz))
        if path == "/api/debts/export":
            _, user, biz = self.require_auth()
            return self.debts_export(user, biz, qs)
        m = re.fullmatch(r"/api/customers/([^/]+)/statement", path)
        if m:
            _, user, biz = self.require_auth()
            return self.customer_statement(user, biz, m.group(1))
        if path == "/api/expenses":
            _, _, biz = self.require_auth()
            return self.send_json(self.expenses_data(biz, qs))
        if path == "/api/expenses/export":
            _, user, biz = self.require_auth()
            return self.expenses_export(user, biz, qs)
        if path == "/api/backup":
            _, user, biz = self.require_auth()
            return self.backup_download(user, biz)
        if path == "/billing/return":
            return self.billing_return(qs)
        m = re.fullmatch(r"/media/product/(prd_[a-f0-9]{32})", path)
        if m:
            return self.serve_product_image(m.group(1))
        m = re.fullmatch(r"/media/logo/([a-z0-9-]+)", path)
        if m:
            return self.serve_logo(m.group(1))
        m = re.fullmatch(r"/store/([a-zA-Z0-9-]+)", path)
        if m:
            nonce = secrets.token_urlsafe(16)
            return self.send_html(self.storefront_html(m.group(1), qs, nonce), nonce=nonce)
        m = re.fullmatch(r"/receipt/([A-Za-z0-9_-]+)", path)
        if m:
            return self.receipt_page(m.group(1))
        m = re.fullmatch(r"/receipt/([A-Za-z0-9_-]+)/pdf", path)
        if m:
            return self.receipt_pdf_response(m.group(1), qs)
        if path.startswith("/api/") or path.startswith("/media/"):
            raise AppError("Not found.", 404)
        self.send_html(
            "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Page not found</title><body style='font:16px system-ui;margin:12vh auto;max-width:420px;padding:0 20px'>"
            f"<h1>Page not found</h1><p>That page does not exist.</p><p><a href='{html.escape(app_link('/'), quote=True)}'>Go to Oja Loom</a></p>",
            404,
        )

    def serve_product_image(self, pid: str) -> None:
        with db_connect() as conn:
            row = conn.execute(
                """SELECT p.image_data, p.active, p.business_id, b.storefront_enabled
                   FROM products p JOIN businesses b ON b.id=p.business_id WHERE p.id=?""",
                (pid,),
            ).fetchone()
        if not row or not row["image_data"]:
            raise AppError("Image not found.", 404)
        allowed = bool(row["active"] and row["storefront_enabled"])  # public storefront items
        if not allowed:
            sess, user = self.session()
            if sess and user:
                with db_connect() as conn:
                    allowed = bool(
                        conn.execute(
                            "SELECT 1 FROM business_members WHERE user_id=? AND business_id=?", (user["id"], row["business_id"])
                        ).fetchone()
                    )
        decoded = decode_image(row["image_data"]) if allowed else None
        if not decoded:
            raise AppError("Image not found.", 404)
        self.send_bytes(decoded[1], 200, decoded[0], cache="private, max-age=86400")

    def serve_logo(self, slug: str) -> None:
        with db_connect() as conn:
            row = conn.execute("SELECT logo_data FROM businesses WHERE slug=?", (slug,)).fetchone()
        decoded = decode_image(row["logo_data"]) if row and row["logo_data"] else None
        if not decoded:
            raise AppError("Image not found.", 404)
        self.send_bytes(decoded[1], 200, decoded[0], cache="private, max-age=86400")

    # ---- write routes ------------------------------------------------------------------
    def route_write(self, method: str) -> None:
        path = urllib.parse.urlparse(self.path).path
        if method == "POST" and path == "/webhooks/paystack":
            return self.paystack_webhook()  # authenticated by Paystack's signature, not by a login
        public = method == "POST" and path in ("/api/signup", "/api/login", "/api/logout")
        auth = None
        if public:
            self.check_origin()
        else:
            auth = self.require_auth(True)  # before the body is read: strangers cannot make us buffer 8 MB
        limit = MAX_AUTH_BODY if (public or path.startswith("/api/account/")) else MAX_BODY
        body = self.json_body(limit)
        if public:
            if path == "/api/signup":
                return self.signup(body)
            if path == "/api/login":
                return self.login(body)
            self.drop_current_session()
            return self.send_json({"ok": True}, headers={"Set-Cookie": self.cookie_header("", True)})
        sess, user, biz = auth  # type: ignore[misc]
        if method == "POST" and path == "/api/account/password":
            return self.change_password(sess, user, body)
        if method == "POST" and path == "/api/account/terms":
            return self.accept_terms(user, biz)
        if method == "POST" and path == "/api/account/logout-all":
            with db_connect() as conn:
                conn.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
            return self.send_json({"ok": True}, headers={"Set-Cookie": self.cookie_header("", True)})
        if method == "PUT" and path == "/api/business":
            return self.update_business(user["id"], biz["id"], body)
        if method == "POST" and path == "/api/referrals/seen":
            with db_connect() as conn:
                conn.execute("UPDATE referrals SET reward_seen=1 WHERE referrer_business_id=? AND status='rewarded'", (biz["id"],))
            return self.send_json({"ok": True})
        if method == "POST" and path == "/api/categories":
            return self.create_category(biz, body)
        m = re.fullmatch(r"/api/categories/([^/]+)", path)
        if m and method == "DELETE":
            return self.delete_category(biz, m.group(1))
        if path == "/api/products" and method == "POST":
            return self.create_product(biz, body)
        m = re.fullmatch(r"/api/products/([^/]+)", path)
        if m and method in ("PUT", "DELETE"):
            return self.product_item(biz, m.group(1), body, method)
        if path == "/api/customers" and method == "POST":
            return self.create_customer(biz, body)
        m = re.fullmatch(r"/api/customers/([^/]+)", path)
        if m and method in ("PUT", "DELETE"):
            return self.customer_item(biz, m.group(1), body, method)
        if path == "/api/orders" and method == "POST":
            return self.create_order(biz, body)
        m = re.fullmatch(r"/api/orders/([^/]+)", path)
        if m and method in ("PUT", "DELETE"):
            return self.order_item(biz, m.group(1), body, method)
        m = re.fullmatch(r"/api/orders/([^/]+)/payments", path)
        if m and method == "POST":
            return self.add_payment(biz, m.group(1), body)
        m = re.fullmatch(r"/api/debts/([^/]+)", path)
        if m and method == "PUT":
            return self.debt_edit(biz, m.group(1), body)
        m = re.fullmatch(r"/api/payments/([^/]+)", path)
        if m and method in ("PUT", "DELETE"):
            return self.payment_item(biz, m.group(1), body, method)
        if method == "POST" and path == "/api/plan/redeem":
            return self.plan_redeem(user, biz, body)
        if method == "POST" and path == "/api/plan/checkout":
            return self.plan_checkout(user, biz)
        if method == "POST" and path == "/api/share/whatsapp":
            return self.share_whatsapp(user, biz, body)
        if method == "POST" and path == "/api/expenses":
            return self.create_expense(biz, body)
        m = re.fullmatch(r"/api/expenses/(exp_[a-f0-9]{32})", path)
        if m and method in ("PUT", "DELETE"):
            return self.expense_route(biz, m.group(1), body, method)
        m = re.fullmatch(r"/api/products/(prd_[a-f0-9]{32})/stock", path)
        if m and method == "POST":
            return self.adjust_stock(biz, m.group(1), body)
        raise AppError("API route not found.", 404)

    # ---- accounts ----------------------------------------------------------------------
    def biz_json(self, b: sqlite3.Row) -> dict[str, Any]:
        keys = b.keys()
        has_logo = bool(b["has_logo"]) if "has_logo" in keys else bool(b["logo_data"])
        return {
            "id": b["id"], "name": b["name"], "slug": b["slug"], "owner_name": b["owner_name"], "phone": b["phone"],
            "email": b["email"], "category": b["category"], "description": b["description"], "address": b["address"],
            "has_logo": has_logo, "logo_url": f"/media/logo/{b['slug']}?v={urllib.parse.quote(b['updated_at'])}" if has_logo else "",
            "currency": b["currency"], "plan": b["plan"], "subscription_status": b["subscription_status"],
            "trial_start": b["trial_start"], "trial_end": b["trial_end"],
            "allow_negative_inventory": bool(b["allow_negative_inventory"]),
            "receipt_message": b["receipt_message"], "storefront_enabled": bool(b["storefront_enabled"]),
            "pro_until": b["pro_until"], "access": plan_state(b),
        }

    def signup(self, b: dict[str, Any]) -> None:
        if not rate_limit(f"signup:{self.client_ip()}", 10, 3600):
            raise AppError("Too many sign-ups from this network. Please try again later.", 429)
        email = validate_email(str(b.get("email") or ""))
        password = str(b.get("password") or "")
        validate_password(password, email)
        owner = require_text(b.get("owner_name"), "Your name", 120)
        business_name = require_text(b.get("business_name"), "Business name", 160)
        category = optional_text(b.get("category"), 120)
        phone = normalize_ng_phone(require_text(b.get("phone"), "Phone number", 40))
        if str(b.get("accept_terms") or "").lower() not in ("1", "true", "on", "yes"):
            raise ValueError("Please read and accept the Terms of Service to create your account.")
        ref_code = normalize_referral_code(b.get("referral_code"))
        referrer = None
        if ref_code:
            with db_connect() as conn:
                referrer = find_referrer(conn, ref_code)
            if not referrer:
                raise ValueError("That referral code is not valid. Check it, or leave the box empty.")
            if normalize_ng_phone(referrer["phone"]) == phone or (referrer["email"] or "").lower() == email:
                raise ValueError("You cannot use your own referral code.")
        salt, digest, iters = hash_password(password)
        uid = new_id("usr_")
        bid = new_id("biz_")
        now = iso_now()
        trial_start = utcnow()
        trial_end = trial_start + dt.timedelta(days=14 + (REFERRED_BONUS_DAYS if referrer else 0))
        with DB_LOCK, db_connect() as conn, transaction(conn, True):
            if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
                raise AppError("An account already exists with that email.", 409)
            base = slugify(business_name)
            slug = base
            n = 2
            while conn.execute("SELECT 1 FROM businesses WHERE slug=?", (slug,)).fetchone():
                slug = f"{base}-{n}"
                n += 1
            conn.execute(
                "INSERT INTO users(id,email,owner_name,password_salt,password_hash,password_iter,created_at,updated_at,terms_version,terms_accepted_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (uid, email, owner, salt, digest, iters, now, now, TERMS_VERSION, now),
            )
            conn.execute(
                """INSERT INTO businesses(id,name,slug,owner_name,phone,email,category,trial_start,trial_end,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (bid, business_name, slug, owner, phone, email, category,
                 trial_start.isoformat(timespec="seconds"), trial_end.isoformat(timespec="seconds"), now, now),
            )
            conn.execute("INSERT INTO business_members(business_id,user_id,role,created_at) VALUES(?,?,?,?)", (bid, uid, "owner", now))
            referral_code_for(conn, bid)
            audit(conn, bid, {"id": uid, "owner_name": owner, "email": email}, "account", uid, email, "terms",
                  f"Accepted the Terms of Service (version {TERMS_VERSION}) when signing up", [], ip=self.client_ip())
            if referrer:
                conn.execute(
                    "INSERT INTO referrals(id,referrer_business_id,referred_business_id,code,status,referred_bonus_days,created_at) VALUES(?,?,?,?,?,?,?)",
                    (new_id("ref_"), referrer["id"], bid, ref_code, "joined", REFERRED_BONUS_DAYS, now),
                )
            conn.execute(
                "INSERT INTO subscriptions(id,business_id,plan,status,trial_start,trial_end,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (new_id("sub_"), bid, "starter", "trialing",
                 trial_start.isoformat(timespec="seconds"), trial_end.isoformat(timespec="seconds"), now, now),
            )
        self.drop_current_session()
        raw, csrf = self.issue_session(uid)
        with db_connect() as conn:
            user = conn.execute("SELECT id,email,owner_name,created_at,terms_version,terms_accepted_at FROM users WHERE id=?", (uid,)).fetchone()
            biz = conn.execute(f"SELECT {BIZ_COLS} FROM businesses WHERE id=?", (bid,)).fetchone()
        out: dict[str, Any] = {"user": user_json(user), "business": self.biz_json(biz), "csrf": csrf}
        if referrer:
            out["referral"] = {"referrer": referrer["name"], "bonus_days": REFERRED_BONUS_DAYS}
        self.send_json(out, 201, {"Set-Cookie": self.cookie_header(raw)})

    def login(self, b: dict[str, Any]) -> None:
        ip = self.client_ip()
        if not rate_limit(f"login-ip:{ip}", 30, 600):
            raise AppError("Too many attempts from this network. Wait a few minutes and try again.", 429)
        email = validate_email(str(b.get("email") or ""))
        password = str(b.get("password") or "")
        if len(password) > 200:
            raise AppError("Email or password is incorrect.", 401)
        pair_key, acct_key = f"login-fail:{email}:{ip}", f"login-fail-acct:{email}"
        if not (rate_limit(pair_key, 8, 900, record=False) and rate_limit(acct_key, 40, 900, record=False)):
            raise AppError("Too many failed attempts. Try again in about 15 minutes.", 429)
        with db_connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            ok = False
            if row:
                ok = verify_password(password, row["password_salt"], row["password_hash"], row["password_iter"])
            else:
                burn_password_check(password)
            if not ok:
                rate_record(pair_key)
                rate_record(acct_key)
                raise AppError("Email or password is incorrect.", 401)
            if row["password_iter"] != PASSWORD_ITERATIONS:  # quietly upgrade old hashes
                salt, digest, iters = hash_password(password)
                conn.execute(
                    "UPDATE users SET password_salt=?,password_hash=?,password_iter=?,updated_at=? WHERE id=?",
                    (salt, digest, iters, iso_now(), row["id"]),
                )
            user = conn.execute("SELECT id,email,owner_name,created_at,terms_version,terms_accepted_at FROM users WHERE id=?", (row["id"],)).fetchone()
            biz = user_business(conn, row["id"])
            rewards = pending_rewards(conn, biz["id"])
        rate_clear(pair_key)
        self.drop_current_session()
        raw, csrf = self.issue_session(row["id"])
        self.send_json({"user": user_json(user), "business": self.biz_json(biz), "csrf": csrf, "rewards": rewards}, headers={"Set-Cookie": self.cookie_header(raw)})

    def accept_terms(self, user: sqlite3.Row, biz: sqlite3.Row) -> None:
        with DB_LOCK, db_connect() as conn, transaction(conn, True):
            old = conn.execute("SELECT terms_version FROM users WHERE id=?", (user["id"],)).fetchone()["terms_version"] or ""
            if old != TERMS_VERSION:
                now = iso_now()
                conn.execute("UPDATE users SET terms_version=?, terms_accepted_at=?, updated_at=? WHERE id=?", (TERMS_VERSION, now, now, user["id"]))
                audit(conn, biz["id"], user, "account", user["id"], user["email"], "terms",
                      f"Accepted the Terms of Service (version {TERMS_VERSION})",
                      [audit_change("terms_version", "Terms version", old or "none", TERMS_VERSION, "text")], ip=self.client_ip())
            fresh = conn.execute("SELECT id,email,owner_name,created_at,terms_version,terms_accepted_at FROM users WHERE id=?", (user["id"],)).fetchone()
        self.send_json({"user": user_json(fresh)})

    def change_password(self, sess: sqlite3.Row, user: sqlite3.Row, body: dict[str, Any]) -> None:
        if not rate_limit(f"pw:{user['id']}", 8, 900):
            raise AppError("Too many attempts. Try again in a few minutes.", 429)
        current = str(body.get("current_password") or "")
        new = str(body.get("new_password") or "")
        validate_password(new, user["email"])
        with db_connect() as conn:
            u = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
            if not verify_password(current, u["password_salt"], u["password_hash"], u["password_iter"]):
                raise ValueError("Current password is incorrect.")
            if current == new:
                raise ValueError("Choose a new password that is different from the current one.")
            salt, digest, iters = hash_password(new)
            with transaction(conn, True):
                conn.execute(
                    "UPDATE users SET password_salt=?,password_hash=?,password_iter=?,updated_at=? WHERE id=?",
                    (salt, digest, iters, iso_now(), user["id"]),
                )
                conn.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (user["id"], sess["token_hash"]))
                bz = user_business(conn, user["id"])
                if bz:
                    audit(conn, bz["id"], user, "account", user["id"], user["email"], "security", "Password changed; other devices signed out", ip=self.client_ip())
        self.send_json({"ok": True})

    def update_business(self, user_id: str, bid: str, b: dict[str, Any]) -> None:
        name = require_text(b.get("name"), "Business name", 160)
        email = optional_text(b.get("email"), 200)
        if email:
            email = validate_email(email)
        with db_connect() as conn:
            assert_member(conn, user_id, bid)
            old = conn.execute("SELECT * FROM businesses WHERE id=?", (bid,)).fetchone()
            logo = clean_image(b.get("logo_data")) if "logo_data" in b else old["logo_data"]
            conn.execute(
                """UPDATE businesses SET name=?,owner_name=?,phone=?,email=?,category=?,description=?,address=?,logo_data=?,
                   receipt_message=?,storefront_enabled=?,allow_negative_inventory=?,updated_at=? WHERE id=?""",
                (
                    name, optional_text(b.get("owner_name"), 120), normalize_ng_phone(str(b.get("phone") or "")), email,
                    optional_text(b.get("category"), 120), optional_text(b.get("description"), 2500),
                    optional_text(b.get("address"), 500), logo,
                    optional_text(b.get("receipt_message"), 500) or "Thank you for your business.",
                    1 if to_bool(b.get("storefront_enabled")) else 0, 1 if to_bool(b.get("allow_negative_inventory")) else 0,
                    iso_now(), bid,
                ),
            )
            biz = conn.execute(f"SELECT {BIZ_COLS} FROM businesses WHERE id=?", (bid,)).fetchone()
            changes = audit_diff(old, dict(biz), [
                ("name", "Business name", "text"), ("owner_name", "Owner", "text"), ("phone", "Phone", "text"), ("email", "Email", "text"),
                ("category", "Business type", "text"), ("description", "About", "text"), ("address", "Address", "text"),
                ("receipt_message", "Receipt message", "text"), ("storefront_enabled", "Storefront on", "bool"),
                ("allow_negative_inventory", "Selling below zero stock", "bool"),
            ])
            if changes:
                audit(conn, bid, self._user, "business", bid, name, "update", "Changed business settings", changes, ip=self.client_ip())
        self.send_json({"business": self.biz_json(biz)})

    # ---- report downloads ----------------------------------------------------------------
    def report_export(self, user: sqlite3.Row, biz: sqlite3.Row, qs: dict[str, list[str]]) -> None:
        fmt = (qs.get("format", ["pdf"])[0] or "pdf").lower()
        if fmt not in ("pdf", "csv"):
            raise AppError("Choose PDF or CSV.", 400)
        pro_gate(biz, "report_export")
        if not rate_limit(f"export:{user['id']}", 20, 60):
            raise AppError("Please wait a moment before downloading again.", 429)
        end = parse_date(qs.get("end", [None])[0], dt.date.today())
        start = parse_date(qs.get("start", [None])[0], end - dt.timedelta(days=30))
        if start > end:
            start, end = end, start
        if (end - start).days > 3660:
            raise ValueError("Choose a period of 10 years or less.")
        with db_connect() as conn:
            data = report_export_data(conn, biz["id"], start, end)
            logo = ""
            if biz["has_logo"]:
                row = conn.execute("SELECT logo_data FROM businesses WHERE id=?", (biz["id"],)).fetchone()
                logo = row["logo_data"] if row else ""
        stem = f"ojaloom-sales-{start.isoformat()}_to_{end.isoformat()}"
        if fmt == "csv":
            return self.send_bytes(report_csv(data), 200, "text/csv; charset=utf-8", {"Content-Disposition": f'attachment; filename="{stem}.csv"'})
        self.send_bytes(build_report_pdf(biz, data, logo), 200, "application/pdf", {"Content-Disposition": f'attachment; filename="{stem}.pdf"'})

    # ---- referrals ---------------------------------------------------------------------
    # ---- expenses -----------------------------------------------------------------------
    @staticmethod
    def _expense_range(qs: dict[str, list[str]], biz: sqlite3.Row) -> tuple[dt.date, dt.date]:
        today = dt.date.today()
        end = parse_date(qs.get("end", [None])[0], today)
        start = parse_date(qs.get("start", [None])[0], today.replace(day=1))
        if start > end:
            start, end = end, start
        if (end - start).days > 3660:
            raise ValueError("Choose a period of 10 years or less.")
        if (end - start).days > FREE_REPORT_DAYS:
            pro_gate(biz, "long_reports")
        return start, end

    def expenses_data(self, biz: sqlite3.Row, qs: dict[str, list[str]]) -> dict[str, Any]:
        start, end = self._expense_range(qs, biz)
        category = (qs.get("category", [""])[0] or "").strip()
        if category and category not in EXPENSE_CATEGORIES:
            category = ""
        search = " ".join((qs.get("search", [""])[0] or "").split())[:80]
        with db_connect() as conn:
            d = expense_report(conn, biz["id"], start, end, category, search, MAX_EXPENSE_ROWS)
        k = kobo_to_number
        return {
            "start": d["start"], "end": d["end"], "items": [expense_item(r) for r in d["rows"]], "truncated": d["truncated"],
            "total": k(d["total"]), "count": d["count"], "period_total": k(d["period_total"]), "prev_total": k(d["prev_total"]),
            "by_category": [{"category": c["category"], "total": k(c["total"]), "count": c["count"]} for c in d["by_category"]],
            "sales": k(d["sales"]), "gross_profit": k(d["gross_profit"]), "net_profit": k(d["net_profit"]),
            "categories": list(EXPENSE_CATEGORIES),
        }

    def create_expense(self, biz: sqlite3.Row, b: dict[str, Any]) -> None:
        v = expense_values(b)
        with DB_LOCK, db_connect() as conn, transaction(conn, True):
            eid, now = new_id("exp_"), iso_now()
            conn.execute(
                "INSERT INTO expenses(id,business_id,amount,category,description,vendor,spent_on,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (eid, biz["id"], v["amount"], v["category"], v["description"], v["vendor"], v["spent_on"], now, now))
            audit(conn, biz["id"], self._user, "expense", eid, expense_label(v), "create",
                  f"Recorded a {naira_text(v['amount'])} expense: {v['category']}", [
                      audit_change("amount", "Amount", 0, v["amount"], "money"), audit_change("category", "Category", "", v["category"], "text"),
                      audit_change("description", "Details", "", v["description"], "text"), audit_change("spent_on", "Date", "", v["spent_on"], "date")],
                  ip=self.client_ip())
            row = conn.execute("SELECT * FROM expenses WHERE id=?", (eid,)).fetchone()
        self.send_json({"expense": expense_item(row)}, 201)

    def expense_route(self, biz: sqlite3.Row, eid: str, b: dict[str, Any], method: str) -> None:
        """Correct (PUT) or remove (DELETE) an expense. A reason is required; the old values stay in the edit history."""
        with DB_LOCK, db_connect() as conn, transaction(conn, True):
            old = conn.execute("SELECT * FROM expenses WHERE id=? AND business_id=?", (eid, biz["id"])).fetchone()
            if not old:
                raise AppError("Expense not found.", 404)
            if method == "DELETE":
                reason = self._reason(b)
                conn.execute("DELETE FROM expenses WHERE id=?", (eid,))
                audit(conn, biz["id"], self._user, "expense", eid, expense_label(old), "delete",
                      f"Removed a {naira_text(old['amount'])} expense: {old['category']}", [
                          audit_change("amount", "Amount", old["amount"], 0, "money"), audit_change("category", "Category", old["category"], "", "text"),
                          audit_change("description", "Details", old["description"], "", "text"), audit_change("spent_on", "Date", old["spent_on"], "", "date")],
                      reason=reason, ip=self.client_ip())
                return self.send_json({"ok": True})
            v = expense_values(b)
            changes = audit_diff(old, v, [("amount", "Amount", "money"), ("category", "Category", "text"), ("description", "Details", "text"),
                                          ("vendor", "Paid to", "text"), ("spent_on", "Date", "date")])
            if changes:
                reason = self._reason(b)
                conn.execute("UPDATE expenses SET amount=?, category=?, description=?, vendor=?, spent_on=?, updated_at=? WHERE id=?",
                             (v["amount"], v["category"], v["description"], v["vendor"], v["spent_on"], iso_now(), eid))
                audit(conn, biz["id"], self._user, "expense", eid, expense_label(v), "adjust",
                      f"Corrected a {naira_text(v['amount'])} expense: {v['category']}", changes, reason=reason, ip=self.client_ip())
            row = conn.execute("SELECT * FROM expenses WHERE id=?", (eid,)).fetchone()
        self.send_json({"expense": expense_item(row)})

    def expenses_export(self, user: sqlite3.Row, biz: sqlite3.Row, qs: dict[str, list[str]]) -> None:
        fmt = (qs.get("format", ["pdf"])[0] or "pdf").lower()
        if fmt not in ("pdf", "csv"):
            raise AppError("Choose PDF or CSV.", 400)
        pro_gate(biz, "expense_export")
        if not rate_limit(f"export:{user['id']}", 20, 60):
            raise AppError("Please wait a moment before downloading again.", 429)
        start, end = self._expense_range(qs, biz)
        with db_connect() as conn:
            data = expense_report(conn, biz["id"], start, end)
            logo = ""
            if biz["has_logo"]:
                row = conn.execute("SELECT logo_data FROM businesses WHERE id=?", (biz["id"],)).fetchone()
                logo = row["logo_data"] if row else ""
        stem = f"ojaloom-expenses-{start.isoformat()}_to_{end.isoformat()}"
        if fmt == "csv":
            return self.send_bytes(expenses_csv(data), 200, "text/csv; charset=utf-8", {"Content-Disposition": f'attachment; filename="{stem}.csv"'})
        self.send_bytes(build_expenses_pdf(biz, data, logo), 200, "application/pdf", {"Content-Disposition": f'attachment; filename="{stem}.pdf"'})

    def backup_download(self, user: sqlite3.Row, biz: sqlite3.Row) -> None:
        if not rate_limit(f"backup:{user['id']}", 6, 3600):
            raise AppError("You have downloaded several backups already. Try again in a little while.", 429)
        with DB_LOCK, db_connect() as conn, transaction(conn, True):
            data = backup_zip(conn, biz)
            audit(conn, biz["id"], self._user, "account", user["id"], user["email"], "security", "Downloaded a backup of all records", ip=self.client_ip())
        stem = f"ojaloom-backup-{dt.date.today().isoformat()}"
        self.send_bytes(data, 200, "application/zip", {"Content-Disposition": f'attachment; filename="{stem}.zip"'})

    # ---- stock adjustments ----------------------------------------------------------------
    def adjust_stock(self, biz: sqlite3.Row, pid: str, b: dict[str, Any]) -> None:
        """Add, remove or recount stock. A reason is required and the old and new numbers go into the edit history."""
        mode = str(b.get("mode") or "add")
        if mode not in ("add", "remove", "set"):
            raise ValueError("Choose whether stock came in, went out, or was counted.")
        qty = parse_int(b.get("quantity"), "Quantity", 0, MAX_QTY, 0)
        if mode != "set" and qty <= 0:
            raise ValueError("Enter how many units.")
        reason = self._reason(b)
        with DB_LOCK, db_connect() as conn, transaction(conn, True):
            old = conn.execute("SELECT * FROM products WHERE id=? AND business_id=?", (pid, biz["id"])).fetchone()
            if not old:
                raise AppError("Product not found.", 404)
            cur = old["stock_quantity"]
            new = cur + qty if mode == "add" else cur - qty if mode == "remove" else qty
            if new < 0 and not biz["allow_negative_inventory"]:
                raise ValueError(f"Only {cur} in stock, so you cannot remove {qty}.")
            if new > MAX_QTY:
                raise ValueError("That is more stock than Oja Loom can hold.")
            if new != cur:
                conn.execute("UPDATE products SET stock_quantity=?, updated_at=? WHERE id=? AND business_id=?", (new, iso_now(), pid, biz["id"]))
                verb = "Added" if mode == "add" else "Removed" if mode == "remove" else "Recounted"
                audit(conn, biz["id"], self._user, "product", pid, old["name"], "adjust",
                      f"{verb} stock for {old['name']}: {cur} to {new}", [audit_change("stock_quantity", "Stock", cur, new, "num")],
                      reason=reason, ip=self.client_ip())
            row = conn.execute(f"SELECT {PRODUCT_COLS} FROM products WHERE id=?", (pid,)).fetchone()
        self.send_json({"product": row_to_product(row)})

    def referral_check(self, qs: dict[str, list[str]]) -> None:
        """Public: lets the sign-up form confirm a code and show who invited the visitor."""
        if not rate_limit(f"refcheck:{self.client_ip()}", 40, 600):
            raise AppError("Too many lookups. Try again in a few minutes.", 429)
        code = normalize_referral_code((qs.get("code") or [""])[0])
        with db_connect() as conn:
            row = find_referrer(conn, code)
        if not row:
            return self.send_json({"valid": False})
        self.send_json({"valid": True, "code": code, "business": row["name"], "bonus_days": REFERRED_BONUS_DAYS})

    def referrals_data(self, biz: sqlite3.Row) -> None:
        with DB_LOCK, db_connect() as conn:
            code = referral_code_for(conn, biz["id"])
            summary = referral_summary(conn, biz["id"])
            fresh = conn.execute("SELECT trial_end,subscription_status FROM businesses WHERE id=?", (biz["id"],)).fetchone()
        self.send_json({"code": code, **summary, "trial_end": fresh["trial_end"], "subscription_status": fresh["subscription_status"]})

    # ---- categories --------------------------------------------------------------------
    def create_category(self, biz: sqlite3.Row, b: dict[str, Any]) -> None:
        with DB_LOCK, db_connect() as conn, transaction(conn, True):
            name = canonical_category(conn, biz["id"], b.get("name"))
            if not name:
                raise ValueError("Enter a category name.")
            items = categories_payload(conn, biz["id"])
        self.send_json({"name": name, "items": items}, 201)

    def delete_category(self, biz: sqlite3.Row, cid: str) -> None:
        with DB_LOCK, db_connect() as conn:
            row = conn.execute("SELECT id,name FROM product_categories WHERE id=? AND business_id=?", (cid, biz["id"])).fetchone()
            if not row:
                raise AppError("Category not found.", 404)
            n = conn.execute(
                "SELECT COUNT(*) FROM products WHERE business_id=? AND category=? COLLATE NOCASE", (biz["id"], row["name"])
            ).fetchone()[0]
            if n:
                raise AppError(f"{n} product{'s' if n != 1 else ''} still {'use' if n != 1 else 'uses'} \"{row['name']}\". Move {'them' if n != 1 else 'it'} to another category first.", 409)
            conn.execute("DELETE FROM product_categories WHERE id=?", (cid,))
            items = categories_payload(conn, biz["id"])
        self.send_json({"ok": True, "items": items})

    # ---- products ----------------------------------------------------------------------
    def products_data(self, bid: str, qs: dict[str, list[str]]) -> dict[str, Any]:
        search = (qs.get("search", [""])[0] or "").strip()[:100]
        active = qs.get("active", [""])[0]
        category = (qs.get("category", [""])[0] or "").strip()[:60]
        stock = qs.get("stock", [""])[0]
        try:
            limit = min(max(int(qs.get("limit", ["200"])[0]), 1), 500)
        except ValueError:
            limit = 200
        sql = f"SELECT {PRODUCT_COLS} FROM products WHERE business_id=?"
        args: list[Any] = [bid]
        if search:
            like = f"%{search}%"
            sql += " AND (name LIKE ? OR category LIKE ? OR sku LIKE ?)"
            args += [like, like, like]
        if active in ("0", "1"):
            sql += " AND active=?"
            args.append(int(active))
        if category == "__none__":
            sql += " AND category=''"
        elif category:
            sql += " AND category=? COLLATE NOCASE"
            args.append(category)
        if stock == "out":
            sql += " AND stock_quantity<=0"
        elif stock == "low":
            sql += " AND stock_quantity>0 AND stock_quantity<=low_stock_threshold"
        elif stock == "in":
            sql += " AND stock_quantity>low_stock_threshold"
        sql += " ORDER BY active DESC, name COLLATE NOCASE LIMIT ?"
        args.append(limit)
        with db_connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        return {"items": [row_to_product(r) for r in rows]}

    def product_values(self, conn: sqlite3.Connection, biz: sqlite3.Row, b: dict[str, Any]) -> dict[str, Any]:
        allow_negative = bool(biz["allow_negative_inventory"])
        return {
            "name": require_text(b.get("name"), "Product name", 180),
            "description": optional_text(b.get("description"), 2500),
            "selling_price": money_to_kobo(b.get("selling_price")),
            "cost_price": money_to_kobo(b.get("cost_price")),
            "stock": parse_int(b.get("stock_quantity"), "Stock quantity", -MAX_QTY if allow_negative else 0, MAX_QTY, 0),
            "threshold": parse_int(b.get("low_stock_threshold"), "Low-stock alert", 0, MAX_QTY, LOW_STOCK_DEFAULT),
            "category": canonical_category(conn, biz["id"], b.get("category")),
            "sku": optional_text(b.get("sku"), 100),
            "active": 1 if to_bool(b.get("active"), True) else 0,
        }

    def create_product(self, biz: sqlite3.Row, b: dict[str, Any]) -> None:
        with DB_LOCK, db_connect() as conn, transaction(conn, True):
            if not plan_state(biz)["pro"]:
                count = conn.execute("SELECT COUNT(*) FROM products WHERE business_id=?", (biz["id"],)).fetchone()[0]
                if count >= FREE_MAX_PRODUCTS:
                    raise AppError(
                        f"The free plan holds up to {FREE_MAX_PRODUCTS} products. Oja Loom Pro (\u20a6{PRO_PRICE_NAIRA:,} a month) removes the limit.",
                        402, {"upgrade": "unlimited"},
                    )
            v = self.product_values(conn, biz, b)
            image = clean_image(b.get("image_data"))
            pid, now = new_id("prd_"), iso_now()
            conn.execute(
                """INSERT INTO products(id,business_id,name,description,image_data,selling_price,cost_price,stock_quantity,
                   low_stock_threshold,category,sku,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pid, biz["id"], v["name"], v["description"], image, v["selling_price"], v["cost_price"], v["stock"],
                 v["threshold"], v["category"], v["sku"], v["active"], now, now),
            )
            audit(conn, biz["id"], self._user, "product", pid, v["name"], "create", f"Added product {v['name']}", [
                audit_change("selling_price", "Selling price", 0, v["selling_price"], "money"),
                audit_change("cost_price", "Cost price", 0, v["cost_price"], "money"),
                audit_change("stock_quantity", "Stock", 0, v["stock"], "num"),
            ], ip=self.client_ip())
            row = conn.execute(f"SELECT {PRODUCT_COLS} FROM products WHERE id=?", (pid,)).fetchone()
        self.send_json({"product": row_to_product(row)}, 201)

    def product_item(self, biz: sqlite3.Row, pid: str, b: dict[str, Any], method: str) -> None:
        with DB_LOCK, db_connect() as conn:
            old = conn.execute("SELECT * FROM products WHERE id=? AND business_id=?", (pid, biz["id"])).fetchone()
            if not old:
                raise AppError("Product not found.", 404)
            if method == "DELETE":
                try:
                    conn.execute("DELETE FROM products WHERE id=? AND business_id=?", (pid, biz["id"]))
                except sqlite3.IntegrityError:
                    raise AppError("This product is on existing orders, so it cannot be deleted. Set it to Inactive instead.", 409)
                audit(conn, biz["id"], self._user, "product", pid, old["name"], "delete", f"Deleted product {old['name']}", [
                    audit_change("selling_price", "Selling price", old["selling_price"], 0, "money"),
                    audit_change("stock_quantity", "Stock", old["stock_quantity"], 0, "num"),
                ], ip=self.client_ip())
                return self.send_json({"ok": True})
            with transaction(conn, True):
                v = self.product_values(conn, biz, b)
                image = clean_image(b.get("image_data")) if "image_data" in b else old["image_data"]
                conn.execute(
                    """UPDATE products SET name=?,description=?,image_data=?,selling_price=?,cost_price=?,stock_quantity=?,
                       low_stock_threshold=?,category=?,sku=?,active=?,updated_at=? WHERE id=? AND business_id=?""",
                    (v["name"], v["description"], image, v["selling_price"], v["cost_price"], v["stock"], v["threshold"],
                     v["category"], v["sku"], v["active"], iso_now(), pid, biz["id"]),
                )
                changes = audit_diff(old, {"name": v["name"], "selling_price": v["selling_price"], "cost_price": v["cost_price"],
                                           "stock_quantity": v["stock"], "low_stock_threshold": v["threshold"], "category": v["category"],
                                           "sku": v["sku"], "active": v["active"], "description": v["description"]}, [
                    ("name", "Name", "text"), ("selling_price", "Selling price", "money"), ("cost_price", "Cost price", "money"),
                    ("stock_quantity", "Stock", "num"), ("low_stock_threshold", "Low-stock alert", "num"), ("category", "Category", "text"),
                    ("sku", "SKU", "text"), ("active", "Active", "bool"), ("description", "Description", "text"),
                ])
                if changes:
                    audit(conn, biz["id"], self._user, "product", pid, v["name"], "update", f"Edited product {v['name']}", changes, ip=self.client_ip())
            row = conn.execute(f"SELECT {PRODUCT_COLS} FROM products WHERE id=?", (pid,)).fetchone()
        self.send_json({"product": row_to_product(row)})

    def customers_data(self,bid:str,qs:dict[str,list[str]])->dict[str,Any]:
        search=(qs.get("search",[""])[0] or "").strip()
        try:limit=min(max(int(qs.get("limit",["200"])[0]),1),500)
        except:limit=200
        sql="""SELECT c.*, (SELECT COUNT(*) FROM orders o WHERE o.customer_id=c.id) total_orders,
        (SELECT COALESCE(SUM(o.total),0) FROM orders o WHERE o.customer_id=c.id AND o.status='completed') total_spent,
        (SELECT COALESCE(SUM(d.remaining_balance),0) FROM debts d WHERE d.customer_id=c.id AND d.status<>'paid') outstanding_debt
        FROM customers c WHERE c.business_id=?""";args:[Any]=[bid]
        if search:
            sql+=" AND (c.full_name LIKE ? OR c.phone LIKE ?)";like=f"%{search}%";args += [like,like]
        sql+=" ORDER BY c.created_at DESC LIMIT ?";args.append(limit)
        with db_connect() as conn:rows=conn.execute(sql,args).fetchall()
        return {"items":[{"id":r["id"],"full_name":r["full_name"],"phone":r["phone"],"email":r["email"],"address":r["address"],"notes":r["notes"],"created_at":r["created_at"],"total_orders":r["total_orders"],"total_spent":kobo_to_number(r["total_spent"]),"outstanding_debt":kobo_to_number(r["outstanding_debt"])} for r in rows]}

    # ---- helpers shared by the handlers below --------------------------------------------
    @staticmethod
    def _reason(b: dict[str, Any], required: bool = True) -> str:
        reason = " ".join(str(b.get("reason") or "").split())[:300]
        if required and len(reason) < 3:
            raise ValueError("Please give a reason (at least 3 letters). It is saved in your edit history.")
        return reason

    @staticmethod
    def _pay_stamp(raw: Any, fallback: str) -> str:
        """A payment date typed as YYYY-MM-DD. Keeps the stored time when the day has not changed."""
        s = str(raw or "").strip()
        if not s:
            return fallback
        try:
            day = dt.date.fromisoformat(s[:10])
        except ValueError:
            raise ValueError("Enter a valid payment date.")
        if day > dt.date.today() + dt.timedelta(days=1):
            raise ValueError("A payment date cannot be in the future.")
        if str(fallback)[:10] == day.isoformat():
            return fallback
        return f"{day.isoformat()}T12:00:00+00:00"

    @staticmethod
    def _links(order_id: str, customer_id: Any) -> str:
        """Ids an entry is related to, so the history of an order or a customer also shows its payments and debts."""
        return " ".join(x for x in (order_id, customer_id or "") if x)

    def _who(self, conn: sqlite3.Connection, customer_id: Any) -> str:
        if not customer_id:
            return ""
        r = conn.execute("SELECT full_name FROM customers WHERE id=?", (customer_id,)).fetchone()
        return r["full_name"] if r else ""

    # ---- customers --------------------------------------------------------------------------
    def create_customer(self, biz: sqlite3.Row, b: dict[str, Any]) -> None:
        cid, now = new_id("cus_"), iso_now()
        name = require_text(b.get("full_name"), "Customer name", 180)
        phone = normalize_ng_phone(require_text(b.get("phone"), "Phone", 40))
        email, address, notes = optional_text(b.get("email"), 200), optional_text(b.get("address"), 500), optional_text(b.get("notes"), 2000)
        with DB_LOCK, db_connect() as conn, transaction(conn, True):
            conn.execute(
                "INSERT INTO customers(id,business_id,full_name,phone,email,address,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (cid, biz["id"], name, phone, email, address, notes, now, now),
            )
            audit(conn, biz["id"], self._user, "customer", cid, name, "create", f"Added customer {name}", [
                audit_change("full_name", "Name", "", name, "text"), audit_change("phone", "Phone", "", phone, "text")], ip=self.client_ip())
        self.send_json({"id": cid}, 201)

    def customer_item(self, biz: sqlite3.Row, cid: str, b: dict[str, Any], method: str) -> None:
        with DB_LOCK, db_connect() as conn, transaction(conn, True):
            row = conn.execute("SELECT * FROM customers WHERE id=? AND business_id=?", (cid, biz["id"])).fetchone()
            if not row:
                raise AppError("Customer not found.", 404)
            if method == "DELETE":
                conn.execute("DELETE FROM customers WHERE id=? AND business_id=?", (cid, biz["id"]))
                audit(conn, biz["id"], self._user, "customer", cid, row["full_name"], "delete", f"Deleted customer {row['full_name']}", [
                    audit_change("full_name", "Name", row["full_name"], "", "text"), audit_change("phone", "Phone", row["phone"], "", "text")],
                    ip=self.client_ip())
                return self.send_json({"ok": True})
            new = {
                "full_name": require_text(b.get("full_name"), "Customer name", 180),
                "phone": normalize_ng_phone(require_text(b.get("phone"), "Phone", 40)),
                "email": optional_text(b.get("email"), 200), "address": optional_text(b.get("address"), 500), "notes": optional_text(b.get("notes"), 2000),
            }
            conn.execute(
                "UPDATE customers SET full_name=?,phone=?,email=?,address=?,notes=?,updated_at=? WHERE id=? AND business_id=?",
                (new["full_name"], new["phone"], new["email"], new["address"], new["notes"], iso_now(), cid, biz["id"]),
            )
            changes = audit_diff(row, new, [("full_name", "Name", "text"), ("phone", "Phone", "text"), ("email", "Email", "text"),
                                            ("address", "Address", "text"), ("notes", "Notes", "text")])
            if changes:
                audit(conn, biz["id"], self._user, "customer", cid, new["full_name"], "update", f"Edited customer {new['full_name']}", changes,
                      ip=self.client_ip())
        self.send_json({"ok": True})

    # ---- orders -----------------------------------------------------------------------------
    def orders_data(self, bid: str, qs: dict[str, list[str]]) -> dict[str, Any]:
        search = (qs.get("search", [""])[0] or "").strip()
        sql = "SELECT o.* FROM orders o LEFT JOIN customers c ON c.id=o.customer_id WHERE o.business_id=?"
        args: list[Any] = [bid]
        if search:
            sql += " AND (o.order_number LIKE ? OR c.full_name LIKE ? OR c.phone LIKE ?)"
            like = f"%{search}%"
            args += [like, like, like]
        status = (qs.get("status", [""])[0] or "").strip().lower()
        if status in BUSINESS_STATUSES:
            sql += " AND o.status=?"
            args.append(status)
        sql += " ORDER BY o.order_date DESC,o.created_at DESC LIMIT 300"
        with db_connect() as conn:
            rows = conn.execute(sql, args).fetchall()
            return {"items": [order_payload(conn, r, False) for r in rows]}

    def create_order(self, biz: sqlite3.Row, b: dict[str, Any]) -> None:
        oid, now = new_id("ord_"), iso_now()
        customer_id = b.get("customer_id") or None
        status = str(b.get("status") or "pending").lower()
        if status not in BUSINESS_STATUSES:
            raise ValueError("Invalid order status.")
        with DB_LOCK, db_connect() as conn, transaction(conn, True):
            if not plan_state(biz)["pro"]:
                made = conn.execute("SELECT COUNT(*) FROM orders WHERE business_id=? AND substr(created_at,1,7)=?", (biz["id"], now[:7])).fetchone()[0]
                if made >= FREE_MAX_ORDERS_PER_MONTH:
                    raise AppError(
                        f"The free plan holds up to {FREE_MAX_ORDERS_PER_MONTH} new orders a month. Oja Loom Pro (₦{PRO_PRICE_NAIRA:,} a month) removes the limit.",
                        402, {"upgrade": "unlimited"})
            if customer_id and not conn.execute("SELECT 1 FROM customers WHERE id=? AND business_id=?", (customer_id, biz["id"])).fetchone():
                raise ValueError("Selected customer does not belong to this business.")
            items, subtotal, gross = parse_order_items(conn, biz["id"], b.get("items"))
            discount = money_to_kobo(b.get("discount"))
            if discount > subtotal:
                raise ValueError("Discount cannot exceed the subtotal.")
            total, profit = subtotal - discount, gross - discount
            method = require_text(b.get("payment_method") or "Bank Transfer", "Payment method", 50)
            date = require_text(b.get("order_date") or today_iso(), "Order date", 40)
            number = next_order_number(conn, biz["id"])
            conn.execute(
                """INSERT INTO orders(id,business_id,customer_id,order_number,subtotal,discount,total,amount_paid,balance,estimated_gross_profit,payment_method,status,notes,order_date,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (oid, biz["id"], customer_id, number, subtotal, discount, total, 0, total, profit, method, status, optional_text(b.get("notes"), 2000), date, now, now),
            )
            for i in items:
                conn.execute(
                    "INSERT INTO order_items(id,order_id,business_id,product_id,product_name,quantity,unit_price,unit_cost,line_total,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (new_id("itm_"), oid, biz["id"], i["product_id"], i["product_name"], i["quantity"], i["unit_price"], i["unit_cost"], i["line_total"], now),
                )
            initial = money_to_kobo(b.get("initial_payment"))
            if initial > total:
                raise ValueError("Initial payment cannot exceed the order total.")
            pid = ""
            if initial > 0:
                pid = new_id("pay_")
                conn.execute(
                    "INSERT INTO payments(id,business_id,order_id,customer_id,amount,payment_method,note,paid_at,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (pid, biz["id"], oid, customer_id, initial, method, "Initial payment", now, now),
                )
            if status == "completed":
                apply_inventory(conn, oid)
                qualify_referral(conn, biz["id"], total)
            sync_order_financials(conn, oid)
            set_debt_due_date(conn, oid, b.get("due_date"))
            create_receipt_if_missing(conn, oid, biz["id"])
            who = self._who(conn, customer_id)
            audit(conn, biz["id"], self._user, "order", oid, number, "create", f"Created order {number}" + (f" for {who}" if who else "") + f" ({naira_text(total)})", [
                audit_change("customer", "Customer", "", who or "Walk-in customer", "text"),
                audit_change("items", "Items", [], order_item_lines(items), "list"),
                audit_change("total", "Total", 0, total, "money"),
                audit_change("status", "Status", "", status.title(), "text"),
            ], ref_id=customer_id or "", ip=self.client_ip())
            if pid:
                audit(conn, biz["id"], self._user, "payment", pid, number, "create", f"Recorded {naira_text(initial)} payment on {number}" + (f" from {who}" if who else ""), [
                    audit_change("amount", "Amount", 0, initial, "money"), audit_change("payment_method", "Method", "", method, "text"),
                    audit_change("balance", "Balance left", 0, total - initial, "money")], ref_id=self._links(oid, customer_id), ip=self.client_ip())
            row = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
            payload = order_payload(conn, row, True)
        self.send_json({"order": payload}, 201)

    def order_item(self, biz: sqlite3.Row, oid: str, b: dict[str, Any], method: str) -> None:
        with DB_LOCK, db_connect() as conn, transaction(conn, True):
            old = conn.execute("SELECT * FROM orders WHERE id=? AND business_id=?", (oid, biz["id"])).fetchone()
            if not old:
                raise AppError("Order not found.", 404)
            old_items = conn.execute("SELECT * FROM order_items WHERE order_id=? ORDER BY created_at", (oid,)).fetchall()
            old_debt = conn.execute("SELECT due_date FROM debts WHERE order_id=?", (oid,)).fetchone()
            old_who = self._who(conn, old["customer_id"])
            if method == "DELETE":
                if old["amount_paid"] > 0:
                    raise ValueError("An order with recorded payments cannot be deleted. Void its payments first, then delete it.")
                restore_inventory(conn, oid)
                conn.execute("DELETE FROM orders WHERE id=? AND business_id=?", (oid, biz["id"]))
                audit(conn, biz["id"], self._user, "order", oid, old["order_number"], "delete",
                      f"Deleted order {old['order_number']}" + (f" for {old_who}" if old_who else "") + f" ({naira_text(old['total'])})", [
                    audit_change("items", "Items", order_item_lines(old_items), [], "list"),
                    audit_change("total", "Total", old["total"], 0, "money")], reason=self._reason(b, False), ref_id=old["customer_id"] or "", ip=self.client_ip())
                return self.send_json({"ok": True})
            customer_id = b.get("customer_id") or None
            if customer_id and not conn.execute("SELECT 1 FROM customers WHERE id=? AND business_id=?", (customer_id, biz["id"])).fetchone():
                raise ValueError("Selected customer does not belong to this business.")
            status = str(b.get("status") or old["status"]).lower()
            if status not in BUSINESS_STATUSES:
                raise ValueError("Invalid order status.")
            if status == "cancelled" and old["amount_paid"] > 0:
                raise ValueError("A paid order cannot be cancelled until its payments are voided. Void the payments first, then cancel it.")
            restore_inventory(conn, oid)
            items, subtotal, gross = parse_order_items(conn, biz["id"], b.get("items"))
            discount = money_to_kobo(b.get("discount"))
            if discount > subtotal:
                raise ValueError("Discount cannot exceed subtotal.")
            adjustment = int(old["adjustment"] or 0)  # corrections made to what a customer owes are kept
            total = subtotal - discount + adjustment
            if total < 0:
                raise ValueError("The order total cannot be below zero.")
            if old["amount_paid"] > total:
                raise ValueError("The new total cannot be lower than payments already recorded.")
            now = iso_now()
            conn.execute("DELETE FROM order_items WHERE order_id=?", (oid,))
            for i in items:
                conn.execute(
                    "INSERT INTO order_items(id,order_id,business_id,product_id,product_name,quantity,unit_price,unit_cost,line_total,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (new_id("itm_"), oid, biz["id"], i["product_id"], i["product_name"], i["quantity"], i["unit_price"], i["unit_cost"], i["line_total"], now),
                )
            pay_method = require_text(b.get("payment_method") or old["payment_method"], "Payment method", 50)
            date = require_text(b.get("order_date") or old["order_date"], "Order date", 40)
            notes = optional_text(b.get("notes"), 2000)
            conn.execute(
                "UPDATE orders SET customer_id=?,subtotal=?,discount=?,total=?,estimated_gross_profit=?,payment_method=?,status=?,notes=?,order_date=?,updated_at=? WHERE id=?",
                (customer_id, subtotal, discount, total, gross - discount + adjustment, pay_method, status, notes, date, now, oid),
            )
            conn.execute("UPDATE payments SET customer_id=? WHERE order_id=?", (customer_id, oid))
            if status == "completed":
                apply_inventory(conn, oid)
                qualify_referral(conn, biz["id"], total)
            sync_order_financials(conn, oid)
            if "due_date" in b:
                set_debt_due_date(conn, oid, b.get("due_date"))
            create_receipt_if_missing(conn, oid, biz["id"])
            new_who = self._who(conn, customer_id)
            new_debt = conn.execute("SELECT due_date FROM debts WHERE order_id=?", (oid,)).fetchone()
            changes = audit_diff(old, {"discount": discount, "total": total, "status": status.title(), "payment_method": pay_method,
                                       "order_date": str(date)[:10], "notes": notes}, [
                ("discount", "Discount", "money"), ("total", "Total", "money"), ("payment_method", "Payment method", "text"), ("notes", "Notes", "text")])
            if old["status"] != status:
                changes.insert(0, audit_change("status", "Status", str(old["status"]).title(), status.title(), "text"))
            if (old["customer_id"] or "") != (customer_id or ""):
                changes.append(audit_change("customer", "Customer", old_who or "Walk-in customer", new_who or "Walk-in customer", "text"))
            if str(old["order_date"])[:10] != str(date)[:10]:
                changes.append(audit_change("order_date", "Order date", str(old["order_date"])[:10], str(date)[:10], "date"))
            before, after = order_item_lines(old_items), order_item_lines(items)
            if before != after:
                changes.append(audit_change("items", "Items", before, after, "list"))
            d_old, d_new = (old_debt["due_date"] if old_debt else "") or "", (new_debt["due_date"] if new_debt else "") or ""
            if d_old != d_new:
                changes.append(audit_change("due_date", "Due date", d_old, d_new, "date"))
            if changes:
                only_status = len(changes) == 1 and changes[0]["key"] == "status"
                audit(conn, biz["id"], self._user, "order", oid, old["order_number"], "status" if only_status else "update",
                      (f"Order {old['order_number']} marked {status}" if only_status else f"Edited order {old['order_number']}"), changes,
                      ref_id=customer_id or "", ip=self.client_ip())
            row = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
            payload = order_payload(conn, row, True)
        self.send_json({"order": payload})

    # ---- payments ---------------------------------------------------------------------------
    def add_payment(self, biz: sqlite3.Row, oid: str, b: dict[str, Any]) -> None:
        amount = money_to_kobo(b.get("amount"))
        if amount <= 0:
            raise ValueError("Payment amount must be greater than zero.")
        with DB_LOCK, db_connect() as conn, transaction(conn, True):
            order = conn.execute("SELECT * FROM orders WHERE id=? AND business_id=?", (oid, biz["id"])).fetchone()
            if not order:
                raise AppError("Order not found.", 404)
            if order["status"] == "cancelled":
                raise ValueError("Cannot add payment to a cancelled order.")
            if amount > order["balance"]:
                raise ValueError("Payment cannot exceed the remaining balance.")
            now, pid = iso_now(), new_id("pay_")
            method = require_text(b.get("payment_method") or order["payment_method"], "Payment method", 50)
            paid_at = self._pay_stamp(b.get("paid_at"), now)
            conn.execute(
                "INSERT INTO payments(id,business_id,order_id,customer_id,amount,payment_method,note,paid_at,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (pid, biz["id"], oid, order["customer_id"], amount, method, optional_text(b.get("note"), 500), paid_at, now),
            )
            order = sync_order_financials(conn, oid)
            who = self._who(conn, order["customer_id"])
            audit(conn, biz["id"], self._user, "payment", pid, order["order_number"], "create",
                  f"Recorded {naira_text(amount)} payment on {order['order_number']}" + (f" from {who}" if who else ""), [
                audit_change("amount", "Amount", 0, amount, "money"), audit_change("payment_method", "Method", "", method, "text"),
                audit_change("balance", "Balance left", 0, order["balance"], "money")], ref_id=self._links(oid, order["customer_id"]), ip=self.client_ip())
            payload = order_payload(conn, order, True)
        self.send_json({"order": payload}, 201)

    def payment_item(self, biz: sqlite3.Row, pid: str, b: dict[str, Any], method: str) -> None:
        """Correct (PUT) or void (DELETE) a recorded payment. A reason is required; the old values stay in the edit history."""
        reason = self._reason(b)
        with DB_LOCK, db_connect() as conn, transaction(conn, True):
            pay = conn.execute("SELECT * FROM payments WHERE id=? AND business_id=?", (pid, biz["id"])).fetchone()
            if not pay:
                raise AppError("Payment not found.", 404)
            order = conn.execute("SELECT * FROM orders WHERE id=?", (pay["order_id"],)).fetchone()
            if order["status"] == "cancelled":
                raise ValueError("This order is cancelled, so its payments are locked.")
            who = self._who(conn, order["customer_id"])
            links = self._links(order["id"], order["customer_id"])
            if method == "DELETE":
                conn.execute("DELETE FROM payments WHERE id=?", (pid,))
                fresh = sync_order_financials(conn, order["id"])
                audit(conn, biz["id"], self._user, "payment", pid, order["order_number"], "void",
                      f"Voided {naira_text(pay['amount'])} payment on {order['order_number']}" + (f" from {who}" if who else ""), [
                    audit_change("amount", "Amount", pay["amount"], 0, "money"), audit_change("payment_method", "Method", pay["payment_method"], "", "text"),
                    audit_change("balance", "Balance left", order["balance"], fresh["balance"], "money")], reason=reason, ref_id=links, ip=self.client_ip())
                return self.send_json({"order": order_payload(conn, fresh, True)})
            amount = money_to_kobo(b.get("amount"))
            if amount <= 0:
                raise ValueError("Payment amount must be greater than zero.")
            others = conn.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE order_id=? AND id<>?", (order["id"], pid)).fetchone()[0]
            if others + amount > order["total"]:
                raise ValueError(f"That would make payments add up to more than the order total ({naira_text(order['total'])}).")
            pay_method = require_text(b.get("payment_method") or pay["payment_method"], "Payment method", 50)
            note = optional_text(b.get("note"), 500) if "note" in b else pay["note"]
            paid_at = self._pay_stamp(b.get("paid_at"), pay["paid_at"])
            conn.execute("UPDATE payments SET amount=?, payment_method=?, note=?, paid_at=? WHERE id=?", (amount, pay_method, note, paid_at, pid))
            fresh = sync_order_financials(conn, order["id"])
            changes = audit_diff(pay, {"amount": amount, "payment_method": pay_method, "note": note}, [
                ("amount", "Amount", "money"), ("payment_method", "Method", "text"), ("note", "Note", "text")])
            if str(pay["paid_at"])[:10] != str(paid_at)[:10]:
                changes.append(audit_change("paid_at", "Date paid", str(pay["paid_at"])[:10], str(paid_at)[:10], "date"))
            if order["balance"] != fresh["balance"]:
                changes.append(audit_change("balance", "Balance left", order["balance"], fresh["balance"], "money"))
            if changes:
                audit(conn, biz["id"], self._user, "payment", pid, order["order_number"], "adjust",
                      f"Corrected a payment on {order['order_number']}" + (f" from {who}" if who else ""), changes, reason=reason, ref_id=links, ip=self.client_ip())
            return self.send_json({"order": order_payload(conn, fresh, True)})

    # ---- debts ------------------------------------------------------------------------------
    def debts_data(self, bid: str) -> dict[str, Any]:
        today = dt.date.today()
        with db_connect() as conn:
            rows = conn.execute(
                """SELECT d.*, o.order_number, substr(o.order_date,1,10) order_date, c.full_name customer_name, c.phone customer_phone, c.email customer_email
                   FROM debts d JOIN orders o ON o.id=d.order_id LEFT JOIN customers c ON c.id=d.customer_id
                   WHERE d.business_id=? AND d.status<>'paid' AND d.remaining_balance>0 AND o.status<>'cancelled'
                   ORDER BY d.created_at DESC""", (bid,)).fetchall()
        items: list[dict[str, Any]] = []
        for r in rows:
            late = 0
            if r["due_date"]:
                with contextlib.suppress(ValueError):
                    late = (today - dt.date.fromisoformat(str(r["due_date"])[:10])).days
            status = "overdue" if late > 0 else ("partially_paid" if r["amount_paid"] > 0 else "outstanding")
            items.append({
                "id": r["id"], "order_id": r["order_id"], "order_number": r["order_number"], "order_date": r["order_date"],
                "customer_id": r["customer_id"], "customer_name": r["customer_name"], "customer_phone": r["customer_phone"], "customer_email": r["customer_email"],
                "original_amount": kobo_to_number(r["original_amount"]), "amount_paid": kobo_to_number(r["amount_paid"]),
                "remaining_balance": kobo_to_number(r["remaining_balance"]), "due_date": r["due_date"], "status": status,
                "days_overdue": max(late, 0), "_owed": r["remaining_balance"],
            })
        items.sort(key=lambda x: (0 if x["status"] == "overdue" else 1, -x["days_overdue"], x["customer_name"] or ""))
        total = sum(x["_owed"] for x in items)
        overdue = sum(x["_owed"] for x in items if x["status"] == "overdue")
        for x in items:
            del x["_owed"]
        return {
            "total_outstanding": kobo_to_number(total), "overdue_total": kobo_to_number(overdue), "overdue_count": sum(1 for x in items if x["status"] == "overdue"),
            "customers_owing": len({x["customer_id"] for x in items if x["customer_id"]}), "items": items,
        }

    def debt_edit(self, biz: sqlite3.Row, did: str, b: dict[str, Any]) -> None:
        """Fix how much a customer owes (or the due date). The change is applied to the order as a correction and written to the edit history."""
        with DB_LOCK, db_connect() as conn, transaction(conn, True):
            debt = conn.execute("SELECT * FROM debts WHERE id=? AND business_id=?", (did, biz["id"])).fetchone()
            if not debt:
                raise AppError("Debt not found.", 404)
            order = conn.execute("SELECT * FROM orders WHERE id=?", (debt["order_id"],)).fetchone()
            if order["status"] == "cancelled":
                raise ValueError("This order is cancelled, so its debt is locked.")
            who = self._who(conn, order["customer_id"])
            changes: list[dict[str, Any]] = []
            reason, action = "", "update"
            if "remaining_balance" in b and str(b.get("remaining_balance")).strip() != "":
                new_owed = money_to_kobo(b.get("remaining_balance"))
                old_owed = int(order["balance"])
                delta = new_owed - old_owed
                if delta != 0:
                    reason = self._reason(b)
                    new_total, adjustment = order["total"] + delta, int(order["adjustment"] or 0) + delta
                    conn.execute(
                        "UPDATE orders SET total=?, adjustment=?, estimated_gross_profit=estimated_gross_profit+?, updated_at=? WHERE id=?",
                        (new_total, adjustment, delta, iso_now(), order["id"]),
                    )
                    changes = [audit_change("remaining_balance", "Amount owed", old_owed, new_owed, "money"),
                               audit_change("total", "Order total", order["total"], new_total, "money")]
                    action = "adjust"
            if "due_date" in b:
                set_debt_due_date(conn, order["id"], b.get("due_date"))
            fresh = sync_order_financials(conn, order["id"])
            now_debt = conn.execute("SELECT * FROM debts WHERE id=?", (did,)).fetchone()
            if "due_date" in b and (debt["due_date"] or "") != (now_debt["due_date"] or ""):
                changes.append(audit_change("due_date", "Due date", debt["due_date"] or "", now_debt["due_date"] or "", "date"))
            if changes:
                if action == "adjust":
                    summary = (f"Changed amount owed on {order['order_number']}" + (f" ({who})" if who else "")
                               + f": {naira_text(changes[0]['from'])} to {naira_text(changes[0]['to'])}")
                else:
                    summary = f"Changed due date on {order['order_number']}" + (f" ({who})" if who else "")
                audit(conn, biz["id"], self._user, "debt", did, order["order_number"], action, summary, changes, reason=reason,
                      ref_id=self._links(order["id"], order["customer_id"]), ip=self.client_ip())
            self.send_json({"order": order_payload(conn, fresh, True), "debt": dict(now_debt)})

    # ---- edit history -----------------------------------------------------------------------
    def activity_data(self, biz: sqlite3.Row, qs: dict[str, list[str]]) -> dict[str, Any]:
        limited = not plan_state(biz)["pro"]
        where, args, tw, ta = audit_filters(biz["id"], qs, FREE_ACTIVITY_DAYS if limited else None)
        try:
            limit = max(1, min(int((qs.get("limit", ["40"])[0] or "40")), 200))
        except ValueError:
            limit = 40
        before = (qs.get("before", [""])[0] or "").strip()
        extra, eargs = ("", []) if not before.isdigit() else (" AND seq<?", [int(before)])
        with db_connect() as conn:
            rows = conn.execute(f"SELECT * FROM audit_log WHERE {where}{tw}{extra} ORDER BY seq DESC LIMIT ?", args + ta + eargs + [limit + 1]).fetchall()
            counts = {r["entity_type"]: r["n"] for r in conn.execute(f"SELECT entity_type, COUNT(*) n FROM audit_log WHERE {where} GROUP BY entity_type", args)}
            chain = audit_verify(conn, biz["id"]) if (qs.get("verify", [""])[0] or "") else None
        more = len(rows) > limit
        rows = rows[:limit]
        out: dict[str, Any] = {
            "items": [audit_item(r) for r in rows], "more": more, "next": rows[-1]["seq"] if (more and rows) else 0,
            "counts": counts, "limited": limited, "limit_days": FREE_ACTIVITY_DAYS,
        }
        if chain is not None:
            out["chain"] = chain
        return out

    def activity_export(self, user: sqlite3.Row, biz: sqlite3.Row, qs: dict[str, list[str]]) -> None:
        pro_gate(biz, "activity_export")
        fmt = (qs.get("format", ["pdf"])[0] or "pdf").lower()
        if fmt not in ("pdf", "csv"):
            raise AppError("Choose PDF or CSV.", 400)
        if not rate_limit(f"export:{user['id']}", 20, 60):
            raise AppError("Please wait a moment before downloading again.", 429)
        where, args, tw, ta = audit_filters(biz["id"], qs, None)
        with db_connect() as conn:
            rows = conn.execute(f"SELECT * FROM audit_log WHERE {where}{tw} ORDER BY seq DESC LIMIT 5000", args + ta).fetchall()
            chain = audit_verify(conn, biz["id"])
            logo = conn.execute("SELECT logo_data FROM businesses WHERE id=?", (biz["id"],)).fetchone()["logo_data"] if biz["has_logo"] else ""
        items = [audit_item(r) for r in rows]
        stem = f"ojaloom-edit-history-{today_iso()}"
        if fmt == "csv":
            return self.send_bytes(activity_csv(items), 200, "text/csv; charset=utf-8", {"Content-Disposition": f'attachment; filename="{stem}.csv"'})
        start, end = (qs.get("start", [""])[0] or "")[:10], (qs.get("end", [""])[0] or "")[:10]
        self.send_bytes(build_activity_pdf(biz, items, chain, logo, start, end), 200, "application/pdf", {"Content-Disposition": f'attachment; filename="{stem}.pdf"'})

    # ---- customer statement -----------------------------------------------------------------
    def customer_statement(self, user: sqlite3.Row, biz: sqlite3.Row, cid: str) -> None:
        pro_gate(biz, "statement_pdf")
        if not rate_limit(f"export:{user['id']}", 20, 60):
            raise AppError("Please wait a moment before downloading again.", 429)
        pdf, cust, _owing = self.statement_pdf(biz, cid)
        stem = re.sub(r"[^A-Za-z0-9_-]+", "-", cust["full_name"]).strip("-")[:40] or "customer"
        self.send_bytes(pdf, 200, "application/pdf", {"Content-Disposition": f'attachment; filename="statement-{stem}.pdf"'})

    def statement_pdf(self, biz: sqlite3.Row, cid: str) -> tuple[bytes, sqlite3.Row, int]:
        """The customer's statement of account as a PDF, plus the customer and what they still owe (kobo)."""
        with db_connect() as conn:
            cust = conn.execute("SELECT * FROM customers WHERE id=? AND business_id=?", (cid, biz["id"])).fetchone()
            if not cust:
                raise AppError("Customer not found.", 404)
            orders = conn.execute(
                """SELECT o.*, d.due_date debt_due FROM orders o LEFT JOIN debts d ON d.order_id=o.id
                   WHERE o.business_id=? AND o.customer_id=? AND o.status<>'cancelled' ORDER BY o.order_date, o.created_at""", (biz["id"], cid)).fetchall()
            blocks = []
            for o in orders:
                blocks.append({
                    "order": o, "due_date": o["debt_due"],
                    "items": conn.execute("SELECT product_name, quantity FROM order_items WHERE order_id=? ORDER BY created_at", (o["id"],)).fetchall(),
                    "payments": conn.execute("SELECT amount, payment_method, paid_at FROM payments WHERE order_id=? ORDER BY paid_at, created_at", (o["id"],)).fetchall(),
                })
            logo = conn.execute("SELECT logo_data FROM businesses WHERE id=?", (biz["id"],)).fetchone()["logo_data"] if biz["has_logo"] else ""
            owing = conn.execute("SELECT COALESCE(SUM(remaining_balance),0) FROM debts WHERE business_id=? AND customer_id=? AND status<>'paid'", (biz["id"], cid)).fetchone()[0]
        return build_statement_pdf(biz, dict(cust), blocks, logo, self.base_url()), cust, int(owing or 0)

    # ---- send a PDF straight into WhatsApp ------------------------------------------------
    def share_whatsapp(self, user: sqlite3.Row, biz: sqlite3.Row, body: dict[str, Any]) -> None:
        """Deliver a receipt or a statement into the customer's WhatsApp from the server's WhatsApp Business number.
        The server builds the PDF and looks up the phone number itself, so a caller can never choose the file or the number:
        this cannot be used as a general-purpose message relay."""
        if not wa_enabled():
            raise AppError("Sending straight to WhatsApp is not switched on for this server.", 503)
        pro_gate(biz, "pdf_receipt")
        doc, ref = str(body.get("doc") or ""), str(body.get("ref") or "")[:80]
        if doc not in ("receipt", "statement") or not ref:
            raise AppError("Choose a receipt or a statement to send.", 400)
        if not (rate_limit(f"wasend:{biz['id']}", 40, 3600) and rate_limit(f"wasend-user:{user['id']}", 20, 600)):
            raise AppError("That is a lot of PDFs in a short time. Please wait a few minutes and try again.", 429)
        shop = biz["name"]
        if doc == "receipt":
            b, o, c, items = self.receipt_record(ref)
            if b["id"] != biz["id"]:
                raise AppError("Receipt not found.", 404)  # somebody else's receipt: look exactly like a missing one
            who, raw_phone = (c["full_name"] if c else ""), (c["phone"] if c else "")
            pays, due = self.receipt_extras(o)
            logo = ""
            if b["has_logo"]:
                with db_connect() as conn:
                    row = conn.execute("SELECT logo_data FROM businesses WHERE id=?", (b["id"],)).fetchone()
                logo = row["logo_data"] if row else ""
            pdf = build_receipt_pdf(b, o, c, items, pays, logo, f"{self.base_url()}/receipt/{ref}", "receipt", due, plan_state(b)["state"] != "pro")
            filename = re.sub(r"[^A-Za-z0-9_-]", "_", o["order_number"]) + ".pdf"
            if o["status"] == "cancelled":
                summary = "This receipt has been cancelled."
            elif o["balance"] > 0:
                summary = f"Total {naira_text(o['total'])}, balance due {naira_text(o['balance'])}."
            else:
                summary = f"Total {naira_text(o['total'])}, paid in full."
            template = WA_TEMPLATE_RECEIPT
            first = ((who or "").split() or ["there"])[0]
            params = [first, o["order_number"], shop, summary]
        else:
            pdf, cust, owing = self.statement_pdf(biz, ref)
            who, raw_phone = cust["full_name"], cust["phone"]
            stem = re.sub(r"[^A-Za-z0-9_-]+", "-", who).strip("-")[:40] or "customer"
            filename = f"statement-{stem}.pdf"
            summary = f"Balance owing: {naira_text(owing)}." if owing > 0 else "Nothing is owing."
            template = WA_TEMPLATE_STATEMENT
            first = ((who or "").split() or ["there"])[0]
            params = [first, shop, summary]
        phone = normalize_ng_phone(raw_phone)
        if not re.fullmatch(r"\d{10,15}", phone):
            raise AppError("This customer has no valid WhatsApp number on file. Add one to the customer first.", 422)
        cutoff = (utcnow() - dt.timedelta(hours=24)).isoformat(timespec="seconds")
        with db_connect() as conn:
            sent_today = conn.execute("SELECT COUNT(*) FROM outbound_messages WHERE business_id=? AND to_phone=? AND status='sent' AND created_at>?",
                                      (biz["id"], phone, cutoff)).fetchone()[0]
        if sent_today >= WA_DAILY_LIMIT_PER_CUSTOMER:
            raise AppError(f"This customer has already been sent {WA_DAILY_LIMIT_PER_CUSTOMER} PDFs today. Try again tomorrow.", 429)
        try:
            provider_id = wa_send_pdf(phone, template, pdf, filename, params)
        except AppError as exc:
            self.log_outbound(biz, user, doc, ref, phone, "failed", error=str(exc))
            raise
        self.log_outbound(biz, user, doc, ref, phone, "sent", provider_id=provider_id)
        self.send_json({"ok": True})

    def log_outbound(self, biz: sqlite3.Row, user: sqlite3.Row, doc: str, ref: str, phone: str, status: str, provider_id: str = "", error: str = "") -> None:
        with db_connect() as conn:
            conn.execute(
                "INSERT INTO outbound_messages(id,business_id,user_id,channel,doc,ref,to_phone,status,provider_id,error,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (new_id("msg_"), biz["id"], user["id"], "whatsapp", doc, ref, phone, status, provider_id, error[:200], iso_now()),
            )

    # ---- plan / billing -----------------------------------------------------------------
    def plan_data(self, biz: sqlite3.Row) -> dict[str, Any]:
        with db_connect() as conn:
            rows = conn.execute(
                "SELECT provider,reference,amount,days,paid_at FROM billing_payments WHERE business_id=? AND status='paid' ORDER BY paid_at DESC LIMIT 20",
                (biz["id"],),
            ).fetchall()
        history = [
            {"provider": r["provider"], "reference": (r["reference"][:8] + "\u2026") if r["provider"] == "code" else r["reference"],
             "amount": kobo_to_number(r["amount"]), "days": r["days"], "paid_at": r["paid_at"]}
            for r in rows
        ]
        return {"plan": plan_state(biz), "pay_note": PAY_NOTE, "online": bool(PAYSTACK_SECRET), "history": history}

    def plan_redeem(self, user: sqlite3.Row, biz: sqlite3.Row, body: dict[str, Any]) -> None:
        if not (rate_limit(f"redeem:{biz['id']}", 8, 900) and rate_limit(f"redeem-ip:{self.client_ip()}", 30, 3600)):
            raise AppError("Too many tries. Wait a few minutes and try again.", 429)
        with DB_LOCK, db_connect() as conn, transaction(conn, True):
            days, until = redeem_billing_code(conn, biz["id"], user, body.get("code"))
            fresh = conn.execute(f"SELECT {BIZ_COLS} FROM businesses WHERE id=?", (biz["id"],)).fetchone()
        self.send_json({"ok": True, "days": days, "until": until, "business": self.biz_json(fresh)})

    def plan_checkout(self, user: sqlite3.Row, biz: sqlite3.Row) -> None:
        if not PAYSTACK_SECRET:
            raise AppError("Online payment is not set up on this server. Use an activation code instead.", 503)
        if not rate_limit(f"checkout:{biz['id']}", 10, 3600):
            raise AppError("Too many attempts. Try again in a little while.", 429)
        ref, amount = "OJA" + secrets.token_hex(10).upper(), PRO_PRICE_NAIRA * 100
        with db_connect() as conn:
            conn.execute(
                "INSERT INTO billing_payments(id,business_id,provider,reference,amount,days,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (new_id("bil_"), biz["id"], "paystack", ref, amount, PRO_PERIOD_DAYS, "pending", iso_now()),
            )
        res = paystack_call("POST", "/transaction/initialize", {
            "email": user["email"], "amount": amount, "currency": "NGN", "reference": ref,
            "callback_url": self.base_url() + "/billing/return", "metadata": {"business_id": biz["id"]},
        })
        url = (res.get("data") or {}).get("authorization_url")
        if not res.get("status") or not url:
            raise AppError(str(res.get("message") or "The payment provider could not start the payment."), 502)
        self.send_json({"url": url})

    def billing_return(self, qs: dict[str, list[str]]) -> None:
        """Paystack sends the shopper back here. Cookies are not sent on that cross-site hop, so confirm the payment
        by its reference and then bounce to the app with a page of our own (same-site, so the login cookie works)."""
        ref = ((qs.get("reference") or qs.get("trxref") or [""])[0] or "")[:64]
        ok = False
        if re.fullmatch(r"[A-Za-z0-9_-]{6,64}", ref) and rate_limit(f"billret:{self.client_ip()}", 30, 600):
            try:
                ok = paystack_finalize(ref)
            except AppError:
                ok = False
        target = app_link("/#/billing?paid=1" if ok else "/#/billing?paid=0")
        self.send_html(
            "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<meta http-equiv=refresh content='0;url={html.escape(target, quote=True)}'><title>Payment</title>"
            "<body style='font:16px system-ui;margin:12vh auto;max-width:420px;padding:0 20px'>"
            f"<p>{'Payment received. Opening Oja Loom' if ok else 'Checking your payment'}\u2026</p><p><a href='{html.escape(target, quote=True)}'>Continue to Oja Loom</a></p>"
        )

    def paystack_webhook(self) -> None:
        try:
            size = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            raise AppError("Invalid request size.", 400)
        if size <= 0 or size > 65536:
            raise AppError("Request is too large.", 413)
        raw = self.rfile.read(size)
        self._body_read = True
        sig = self.headers.get("X-Paystack-Signature", "")
        if not PAYSTACK_SECRET or not sig or not hmac.compare_digest(hmac.new(PAYSTACK_SECRET.encode(), raw, hashlib.sha512).hexdigest(), sig):
            raise AppError("Bad signature.", 401)
        try:
            event = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise AppError("Invalid JSON request.", 400)
        if isinstance(event, dict) and event.get("event") == "charge.success":
            ref = str((event.get("data") or {}).get("reference") or "")[:64]
            if re.fullmatch(r"[A-Za-z0-9_-]{6,64}", ref):
                paystack_finalize(ref)
        self.send_json({"ok": True})

    def debts_export(self, user: sqlite3.Row, biz: sqlite3.Row, qs: dict[str, list[str]]) -> None:
        pro_gate(biz, "debts_pdf")
        fmt = (qs.get("format", ["pdf"])[0] or "pdf").lower()
        if fmt not in ("pdf", "csv"):
            raise AppError("Choose PDF or CSV.", 400)
        if not rate_limit(f"export:{user['id']}", 20, 60):
            raise AppError("Please wait a moment before downloading again.", 429)
        with db_connect() as conn:
            data = debts_report_data(conn, biz["id"])
            logo = conn.execute("SELECT logo_data FROM businesses WHERE id=?", (biz["id"],)).fetchone()["logo_data"] if biz["has_logo"] else ""
        stem = f"ojaloom-debts-{today_iso()}"
        if fmt == "csv":
            return self.send_bytes(debts_csv(data), 200, "text/csv; charset=utf-8", {"Content-Disposition": f'attachment; filename="{stem}.csv"'})
        self.send_bytes(build_debts_pdf(biz, data, logo), 200, "application/pdf", {"Content-Disposition": f'attachment; filename="{stem}.pdf"'})

    def dashboard_data(self,user_id:str,bid:str)->dict[str,Any]:
        today=dt.date.today();week_start=today-dt.timedelta(days=today.weekday());month_start=today.replace(day=1);start14=today-dt.timedelta(days=13)
        with db_connect() as conn:
            def scalar(sql,args=()):return conn.execute(sql,args).fetchone()[0] or 0
            today_sales=scalar("SELECT SUM(total) FROM orders WHERE business_id=? AND status='completed' AND substr(order_date,1,10)=?",(bid,today.isoformat()))
            month_sales=scalar("SELECT SUM(total) FROM orders WHERE business_id=? AND status='completed' AND substr(order_date,1,10)>=?",(bid,month_start.isoformat()))
            month_profit=scalar("SELECT SUM(estimated_gross_profit) FROM orders WHERE business_id=? AND status='completed' AND substr(order_date,1,10)>=?",(bid,month_start.isoformat()))
            month_exp=scalar("SELECT SUM(amount) FROM expenses WHERE business_id=? AND spent_on>=?",(bid,month_start.isoformat()))
            out_debt=scalar("SELECT SUM(remaining_balance) FROM debts WHERE business_id=? AND status<>'paid'",(bid,))
            overdue=conn.execute("SELECT COUNT(*),COALESCE(SUM(remaining_balance),0) FROM debts WHERE business_id=? AND status<>'paid' AND due_date IS NOT NULL AND due_date<?",(bid,today.isoformat())).fetchone()
            today_orders=scalar("SELECT COUNT(*) FROM orders WHERE business_id=? AND substr(order_date,1,10)=?",(bid,today.isoformat()))
            pending=scalar("SELECT COUNT(*) FROM orders WHERE business_id=? AND status IN ('pending','confirmed','processing','ready')",(bid,))
            cust=scalar("SELECT COUNT(*) FROM customers WHERE business_id=?",(bid,));low=scalar("SELECT COUNT(*) FROM products WHERE business_id=? AND active=1 AND stock_quantity>0 AND stock_quantity<=low_stock_threshold",(bid,));out=scalar("SELECT COUNT(*) FROM products WHERE business_id=? AND active=1 AND stock_quantity<=0",(bid,))
            raw=conn.execute("SELECT substr(order_date,1,10) d,SUM(total) t FROM orders WHERE business_id=? AND status='completed' AND substr(order_date,1,10)>=? GROUP BY d",(bid,start14.isoformat())).fetchall();by={r["d"]:r["t"] for r in raw};bars=[]
            for i in range(14):d=start14+dt.timedelta(days=i);bars.append({"date":d.strftime("%d %b"),"total":kobo_to_number(by.get(d.isoformat(),0))})
        return {"today_sales":kobo_to_number(today_sales),"month_sales":kobo_to_number(month_sales),"month_profit":kobo_to_number(month_profit),"month_expenses":kobo_to_number(month_exp),"month_net":kobo_to_number(month_profit-month_exp),"outstanding_debt":kobo_to_number(out_debt),"overdue_count":overdue[0],"overdue_total":kobo_to_number(overdue[1]),"today_orders":today_orders,"pending_orders":pending,"total_customers":cust,"low_stock":low,"out_of_stock":out,"sales_by_day":bars}

    def receipts_data(self,bid:str)->dict[str,Any]:
        with db_connect() as conn:rows=conn.execute("""SELECT r.*,o.order_number,o.order_date,o.total,o.amount_paid,o.balance,c.full_name customer_name,c.phone customer_phone,c.email customer_email FROM receipts r JOIN orders o ON o.id=r.order_id LEFT JOIN customers c ON c.id=o.customer_id WHERE r.business_id=? ORDER BY o.created_at DESC LIMIT 300""",(bid,)).fetchall()
        return {"items":[{"id":r["id"],"public_token":r["public_token"],"order_number":r["order_number"],"order_date":r["order_date"],"customer_name":r["customer_name"],"customer_phone":r["customer_phone"],"customer_email":r["customer_email"],"total":kobo_to_number(r["total"]),"amount_paid":kobo_to_number(r["amount_paid"]),"balance":kobo_to_number(r["balance"])} for r in rows]}

    def reports_data(self,biz:sqlite3.Row,qs:dict[str,list[str]])->dict[str,Any]:
        bid=biz["id"];end=parse_date(qs.get("end",[None])[0],dt.date.today());start=parse_date(qs.get("start",[None])[0],end-dt.timedelta(days=30))
        if start>end:start,end=end,start
        if (end-start).days>FREE_REPORT_DAYS:pro_gate(biz,"long_reports")
        with db_connect() as conn:
            row=conn.execute("SELECT COALESCE(SUM(total),0) sales,COUNT(*) cnt,COALESCE(SUM(estimated_gross_profit),0) profit FROM orders WHERE business_id=? AND status='completed' AND substr(order_date,1,10) BETWEEN ? AND ?",(bid,start.isoformat(),end.isoformat())).fetchone();best=conn.execute("""SELECT oi.product_name name,SUM(oi.quantity) quantity,SUM(oi.line_total) sales FROM order_items oi JOIN orders o ON o.id=oi.order_id WHERE oi.business_id=? AND o.status='completed' AND substr(o.order_date,1,10) BETWEEN ? AND ? GROUP BY oi.product_id,oi.product_name ORDER BY quantity DESC LIMIT 5""",(bid,start.isoformat(),end.isoformat())).fetchall();top=conn.execute("""SELECT c.full_name name,COUNT(o.id) orders,SUM(o.total) spent FROM orders o JOIN customers c ON c.id=o.customer_id WHERE o.business_id=? AND o.status='completed' AND substr(o.order_date,1,10) BETWEEN ? AND ? GROUP BY c.id,c.full_name ORDER BY spent DESC LIMIT 5""",(bid,start.isoformat(),end.isoformat())).fetchall();debt=conn.execute("SELECT COALESCE(SUM(remaining_balance),0) FROM debts WHERE business_id=? AND status<>'paid'",(bid,)).fetchone()[0];exp_total=expense_total(conn,bid,start.isoformat(),end.isoformat())
        return {"start":start.isoformat(),"end":end.isoformat(),"total_sales":kobo_to_number(row["sales"]),"order_count":row["cnt"],"average_order_value":kobo_to_number(int(row["sales"]/row["cnt"]) if row["cnt"] else 0),"estimated_gross_profit":kobo_to_number(row["profit"]),"expenses_total":kobo_to_number(exp_total),"net_profit":kobo_to_number(row["profit"]-exp_total),"outstanding_debt":kobo_to_number(debt),"best_sellers":[{"name":r["name"],"quantity":r["quantity"],"sales":kobo_to_number(r["sales"])} for r in best],"top_customers":[{"name":r["name"],"orders":r["orders"],"spent":kobo_to_number(r["spent"])} for r in top]}


    # ---- public pages ------------------------------------------------------------------
    def storefront_html(self, slug: str, qs: dict[str, list[str]], nonce: str) -> str:
        with db_connect() as conn:
            b = conn.execute(f"SELECT {BIZ_COLS} FROM businesses WHERE slug=? AND storefront_enabled=1", (slug,)).fetchone()
            if not b:
                return (
                    "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
                    "<title>Store not found</title><body style='font:16px system-ui;margin:12vh auto;max-width:420px;padding:0 20px'>"
                    "<h1>Store not found</h1><p>This store link is not available.</p>"
                )
            products = conn.execute(f"SELECT {PRODUCT_COLS} FROM products WHERE business_id=? AND active=1 ORDER BY name COLLATE NOCASE", (b["id"],)).fetchall()
        phone = normalize_ng_phone(b["phone"])
        counts: dict[str, int] = {}
        label_for: dict[str, str] = {}
        for p in products:
            label = p["category"] or "Other"
            label_for.setdefault(label.casefold(), label)
            counts[label.casefold()] = counts.get(label.casefold(), 0) + 1
        wanted = (qs.get("category", [""])[0] or "").strip().casefold()
        if wanted not in counts:
            wanted = ""
        e = html.escape
        cards = []
        for p in products:
            label = p["category"] or "Other"
            if wanted and label.casefold() != wanted:
                continue
            available = p["stock_quantity"] > 0 or bool(b["allow_negative_inventory"])
            price = f"\u20a6{p['selling_price'] / 100:,.2f}"
            if p["has_image"]:
                pic = f'<img class="pic" loading="lazy" src="/media/product/{p["id"]}?v={urllib.parse.quote(p["updated_at"])}" alt="{e(p["name"], quote=True)}">'
            else:
                pic = f'<div class="ph" aria-hidden="true">{e((p["name"] or "?")[:1].upper())}</div>'
            order = ""
            if available and phone:
                msg = urllib.parse.quote(f"Hello {b['name']}, I want to order {p['name']} for {price}. Is it available?")
                order = f'<a class="btn" href="https://wa.me/{phone}?text={msg}" target="_blank" rel="noopener noreferrer">Order on WhatsApp</a>'
            tag = '<span class="tag">Available</span>' if available else '<span class="tag out">Out of stock</span>'
            desc = f'<div class="desc">{e(p["description"])}</div>' if p["description"] else ""
            cards.append(
                f'<article class="item">{pic}<div class="body"><div class="cat">{e(label)}</div>'
                f'<div class="name">{e(p["name"])}</div>{desc}<div class="foot"><span class="price">{price}</span>{tag}</div></div>{order}</article>'
            )
        chips = ""
        if len(counts) > 1:
            base = f"/store/{urllib.parse.quote(slug)}"
            parts = [f'<a class="chip" href="{base}"{" aria-current=true" if not wanted else ""}>All ({len(products)})</a>']
            for key in sorted(counts, key=lambda k: (k == "other", k)):
                lab = label_for[key]
                parts.append(
                    f'<a class="chip" href="{base}?category={urllib.parse.quote(lab)}"{" aria-current=true" if key == wanted else ""}>{e(lab)} ({counts[key]})</a>'
                )
            chips = f'<nav class="chips" aria-label="Categories">{"".join(parts)}</nav>'
        logo = (
            f'<img class="logo" src="/media/logo/{e(b["slug"])}?v={urllib.parse.quote(b["updated_at"])}" alt="">'
            if b["has_logo"]
            else f'<div class="logo" aria-hidden="true">{e((b["name"] or "O")[:1].upper())}</div>'
        )
        contact = " \u2022 ".join(x for x in [public_phone(b["phone"]), b["address"]] if x)
        about_html = f'<div class="sub">{e(b["description"])}</div>' if b["description"] else ""
        contact_html = f'<div class="contact">{e(contact)}</div>' if contact else ""
        grid = "".join(cards) if cards else '<div class="empty">No products are available right now.</div>'
        owner_bar = (
            f'<div class="ownerbar"><a href="{html.escape(app_link("/#/storefront"), quote=True)}">\u2190 Back to Oja Loom</a><span>This is how customers see your store</span></div>'
            if self.is_member(b["id"]) else ""
        )
        powered = "" if plan_state(b)["state"] == "pro" else '<p class="powered">Storefront powered by Oja Loom</p>'
        return (
            f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark">'
            f'<title>{e(b["name"])}</title><style nonce="{nonce}">{STORE_CSS}</style></head><body>{owner_bar}'
            f'<header class="hero"><div class="hero-in">{logo}<div><h1>{e(b["name"])}</h1>'
            f'{about_html}{contact_html}</div></div></header>'
            f'<main class="wrap">{chips}<section class="grid">{grid}</section>'
            f'{powered}</main></body></html>'
        )

    def is_member(self, business_id: str) -> bool:
        """True when the visitor is signed in to Oja Loom as someone who runs this business (they get 'Back to Oja Loom' links)."""
        sess, user = self.session()
        if not (sess and user):
            return False
        with db_connect() as conn:
            return bool(conn.execute("SELECT 1 FROM business_members WHERE user_id=? AND business_id=?", (user["id"], business_id)).fetchone())

    def receipt_record(self, token: str) -> tuple[sqlite3.Row, sqlite3.Row, sqlite3.Row | None, list[sqlite3.Row]]:
        with db_connect() as conn:
            r = conn.execute("SELECT * FROM receipts WHERE public_token=?", (token,)).fetchone()
            if not r:
                raise AppError("Receipt not found.", 404)
            o = conn.execute("SELECT * FROM orders WHERE id=?", (r["order_id"],)).fetchone()
            b = conn.execute(f"SELECT {BIZ_COLS} FROM businesses WHERE id=?", (r["business_id"],)).fetchone()
            c = conn.execute("SELECT * FROM customers WHERE id=?", (o["customer_id"],)).fetchone() if o["customer_id"] else None
            items = conn.execute("SELECT * FROM order_items WHERE order_id=? ORDER BY created_at", (o["id"],)).fetchall()
            return b, o, c, items

    def receipt_extras(self, o: sqlite3.Row) -> tuple[list[sqlite3.Row], str | None]:
        with db_connect() as conn:
            pays = conn.execute("SELECT amount,payment_method,paid_at,note FROM payments WHERE order_id=? ORDER BY paid_at, created_at", (o["id"],)).fetchall()
            debt = conn.execute("SELECT due_date FROM debts WHERE order_id=?", (o["id"],)).fetchone()
        return pays, (debt["due_date"] if debt else None)

    def receipt_page(self, token: str) -> None:
        nonce = secrets.token_urlsafe(16)
        try:
            page = self.receipt_html(token, nonce)
        except AppError as e:
            return self.send_html(friendly_page("Receipt not found", "This receipt link is not valid. Ask the seller to send it again.", [("Go to Oja Loom", app_link("/"))]), e.status)
        self.send_html(page, nonce=nonce, headers={"X-Robots-Tag": "noindex, nofollow"})

    def receipt_html(self, token: str, nonce: str) -> str:
        b, o, c, items = self.receipt_record(token)
        pays, due = self.receipt_extras(o)
        ps = plan_state(b)
        owner = self.is_member(b["id"])
        e = html.escape
        n2 = lambda kobo: f"\u20a6{int(kobo or 0) / 100:,.2f}"  # noqa: E731
        url = f"{self.base_url()}/receipt/{token}"
        phone = normalize_ng_phone(c["phone"] if c else "")
        share = urllib.parse.quote(f"Receipt {o['order_number']} from {b['name']}. Total {n2(o['total'])}. {url}")
        wa = f"https://wa.me/{phone}?text={share}" if phone else f"https://wa.me/?text={share}"
        cancelled = o["status"] == "cancelled"
        if cancelled:
            pill, pill_cls, mark, mark_col = "Cancelled", "bad", "CANCELLED", "#c0352b"
        elif o["balance"] <= 0:
            pill, pill_cls, mark, mark_col = "Paid in full", "ok", "PAID", "#157a4b"
        elif o["amount_paid"] > 0:
            pill, pill_cls, mark, mark_col = "Part paid", "warn", "", ""
        else:
            pill, pill_cls, mark, mark_col = "Unpaid", "warn", "", ""
        logo = (f'<span class="tile"><img src="/media/logo/{e(b["slug"])}?v={urllib.parse.quote(b["updated_at"])}" alt=""></span>' if b["has_logo"]
                else f'<span class="tile" aria-hidden="true">{e((b["name"] or "O").strip()[:1].upper())}</span>')
        contact = "<br>".join(x for x in [e(public_phone(b["phone"])), e(b["address"])] if x)
        rows = "".join(
            f'<tr><td class="idx">{i}</td><td>{e(it["product_name"])}</td><td class="n">{it["quantity"]:,}</td>'
            f'<td class="n">{n2(it["unit_price"])}</td><td class="n"><strong>{n2(it["line_total"])}</strong></td></tr>'
            for i, it in enumerate(items, 1)
        )
        adj = int(o["adjustment"] or 0) if "adjustment" in o.keys() else 0
        sums = f'<div><span class="muted">Subtotal</span><span>{n2(o["subtotal"])}</span></div>'
        if o["discount"]:
            sums += f'<div><span class="muted">Discount</span><span>\u2212 {n2(o["discount"])}</span></div>'
        if adj:
            sign = "+" if adj > 0 else "\u2212"
            sums += f'<div><span class="muted">Correction</span><span>{sign} {n2(abs(adj))}</span></div>'
        sums += f'<div class="grand"><span>Total</span><span>{n2(o["total"])}</span></div>'
        sums += f'<div class="paid"><span class="muted">Amount paid</span><span>{n2(o["amount_paid"])}</span></div>'
        if cancelled:
            sums += '<div class="balbox bad"><span>Cancelled</span></div>'
        elif o["balance"] <= 0:
            sums += '<div class="balbox ok"><span>\u2713 Paid in full</span></div>'
        else:
            sums += f'<div class="balbox warn"><span>Balance due</span><b>{n2(o["balance"])}</b></div>'
        words_amt = o["amount_paid"] or o["total"]
        words_cap = "Amount paid in words" if o["amount_paid"] else "Total in words"
        qr = qr_svg(url, "QR code that opens this receipt online")
        qr_html = (f'<div class="qrbox"><a href="{e(url, quote=True)}" aria-label="Open this receipt online">{qr}</a><div><div class="cap">View online</div>'
                   f'<p>Scan with your phone camera to open this receipt online, share it or print it.</p></div></div>') if qr else ""
        pay_html = ""
        if pays:
            running, prow = int(o["total"] or 0), ""
            for p in pays:
                running -= int(p["amount"])
                note = p["note"] or "\u2013"
                prow += (f'<tr><td>{e(_pretty_date(p["paid_at"]))}</td><td>{e(p["payment_method"])}</td><td class="muted">{e(note)}</td>'
                         f'<td class="n"><strong style="color:#157a4b">{n2(p["amount"])}</strong></td><td class="n">{n2(max(0, running))}</td></tr>')
            pay_html = (f'<h2>Payments received</h2><div class="scroll" style="margin-top:10px"><table><thead><tr><th>Date</th><th>Method</th><th>Note</th>'
                        f'<th class="n">Paid</th><th class="n">Balance after</th></tr></thead><tbody>{prow}</tbody></table></div>')
        notes_html = f'<h2>Notes</h2><p class="notes">{e(o["notes"])}</p>' if (o["notes"] or "").strip() else ""
        # buttons
        bar = ""
        if owner:
            bar += f'<a class="btn back" href="{e(app_link("/#/orders/" + o["id"]), quote=True)}">\u2190 Back to Oja Loom</a>'
        bar += '<span class="grow"></span><button class="btn" id="print" type="button">Print</button>'
        if ps["pro"]:
            bar += (f'<details class="menu"><summary class="btn">Download PDF \u25be</summary><div class="pop">'
                    f'<a href="/receipt/{token}/pdf?kind=receipt">Receipt<small>A4, with QR code and payment history</small></a>'
                    f'<a href="/receipt/{token}/pdf?kind=invoice">Invoice<small>A4, with due date and amount due</small></a>'
                    f'<a href="/receipt/{token}/pdf?kind=thermal">Till slip<small>80 mm roll printer</small></a></div></details>')
        elif owner:
            bar += f'<a class="btn lock" href="{e(app_link("/#/billing"))}">\U0001f512 PDF \u00b7 Pro</a>'
        first = ((c["full_name"] or "").split() or [""])[0] if c else ""
        say = (f"Hello{(' ' + first) if first else ''}, thank you for your business. Here is your receipt {o['order_number']} from {b['name']}. Total {n2(o['total'])}, "
               + (f"balance due {n2(o['balance'])}." if (o["balance"] > 0 and not cancelled) else "paid in full."))
        chat_url = f"https://wa.me/{phone}?text={urllib.parse.quote(say)}" if phone else f"https://wa.me/?text={urllib.parse.quote(say)}"
        mail_to = (c["email"] if c and c["email"] else "").strip()
        mail_subject = f"Receipt {o['order_number']} from {b['name']}"
        mail_body = f"{say}\n\nView it online: {url}"
        mailto = "mailto:" + urllib.parse.quote(mail_to, safe="@") + "?subject=" + urllib.parse.quote(mail_subject) + "&body=" + urllib.parse.quote(mail_body)
        if ps["pro"]:
            # the PDF file itself is handed to WhatsApp or to the mail app, never just a link
            common = (f'data-pdf="/receipt/{token}/pdf?kind=receipt" data-name="{e(o["order_number"], quote=True)}.pdf" '
                      f'data-title="{e("Receipt " + o["order_number"], quote=True)}" data-text="{e(say, quote=True)}"')
            bar += ('<details class="menu"><summary class="btn primary">Send PDF \u25be</summary><div class="pop">'
                    f'<button type="button" id="wa" {common} data-chat="{e(chat_url, quote=True)}" data-link="{e(wa, quote=True)}">WhatsApp<small>Put the PDF in a WhatsApp chat</small></button>'
                    f'<button type="button" id="mail" {common} data-mailto="{e(mailto, quote=True)}">Email<small>Attach the PDF to an email</small></button></div></details>')
        else:
            bar += ('<details class="menu"><summary class="btn primary">Send \u25be</summary><div class="pop">'
                    f'<a href="{e(wa, quote=True)}" target="_blank" rel="noopener noreferrer">WhatsApp<small>Send a link to this receipt</small></a>'
                    f'<a href="{e(mailto, quote=True)}">Email<small>Send a link to this receipt</small></a></div></details>')

        foot = "" if ps["state"] == "pro" else '<div class="foot">Receipt made with Oja Loom</div>'
        mark_attr = f' data-mark="{mark}" style="--mark:{mark_col}"' if mark else ""
        due_row = f'<div><span class="muted">Due date</span><strong>{e(_pretty_date(due))}</strong></div>' if (due and o["balance"] > 0 and not cancelled) else ""
        return (
            f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">'
            f'<meta name="color-scheme" content="light dark"><title>Receipt {e(o["order_number"])} \u00b7 {e(b["name"])}</title>'
            f'<style nonce="{nonce}">{RECEIPT_CSS}</style></head><body>'
            f'<div class="bar">{bar}</div>'
            f'<article class="slip"{mark_attr}><header class="band"><div class="who">{logo}<div><h1>{e(b["name"])}</h1>'
            f'<div class="sub">{contact}</div></div></div><div class="kind"><div class="lbl">Receipt</div><div class="no">{e(o["order_number"])}</div>'
            f'<div class="dt">{e(_pretty_date(o["order_date"]))}</div></div></header>'
            f'<div class="body"><div class="meta"><div class="who2"><div class="cap">Billed to</div><strong>{e(c["full_name"] if c else "Walk-in customer")}</strong>'
            f'<div class="muted">{e(public_phone(c["phone"]) if c else "")}</div></div>'
            f'<div class="facts"><div><span class="muted">Issue date</span><strong>{e(_pretty_date(o["order_date"]))}</strong></div>{due_row}'
            f'<div><span class="muted">Payment method</span><strong>{e(o["payment_method"])}</strong></div>'
            f'<div class="pillrow"><span class="pill {pill_cls}">{pill}</span></div></div></div>'
            f'<div class="scroll"><table><thead><tr><th>#</th><th>Item</th><th class="n">Qty</th><th class="n">Unit price</th><th class="n">Amount</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>'
            f'<div class="sums"><div>{qr_html}<div class="words"><div class="cap">{words_cap}</div><em>{e(naira_words(words_amt))}</em></div></div>'
            f'<div class="totals">{sums}</div></div>'
            f'{pay_html}{notes_html}<div class="thanks">{e(b["receipt_message"] or "Thank you for your business.")}</div></div></article>'
            f'{foot}'
            f'<p class="wanote" id="wa-note" role="status" hidden></p>'
            f'<script nonce="{nonce}">document.getElementById("print").addEventListener("click",function(){{window.print()}})</script>'
            f'<script nonce="{nonce}">{RECEIPT_SHARE_JS}</script>'
            f'</body></html>'
        )

    def receipt_pdf_response(self, token: str, qs: dict[str, list[str]]) -> None:
        if not rate_limit(f"rcpdf:{self.client_ip()}", 60, 600):
            raise AppError("Too many downloads. Please wait a few minutes and try again.", 429)
        try:
            b, o, c, items = self.receipt_record(token)
        except AppError as e:
            return self.send_html(friendly_page("Receipt not found", "This receipt link is not valid.", [("Go to Oja Loom", app_link("/"))]), e.status)
        ps = plan_state(b)
        back = [("Back to the receipt", f"/receipt/{token}")]
        if not ps["pro"]:
            if self.is_member(b["id"]):
                return self.send_html(friendly_page("PDF receipts are part of Oja Loom Pro", f"Upgrade for \u20a6{PRO_PRICE_NAIRA:,} a month to download branded PDF receipts, invoices and till slips.",
                                                    [("See Oja Loom Pro", app_link("/#/billing"))] + back), 402)
            return self.send_html(friendly_page("PDF not available", "The seller has not turned on PDF downloads. You can still print this receipt from the receipt page.", back), 402)
        kind = (qs.get("kind", ["receipt"])[0] or "receipt").lower()
        if kind not in ("receipt", "invoice", "thermal"):
            kind = "receipt"
        pays, due = self.receipt_extras(o)
        logo = ""
        if b["has_logo"]:
            with db_connect() as conn:
                row = conn.execute("SELECT logo_data FROM businesses WHERE id=?", (b["id"],)).fetchone()
            logo = row["logo_data"] if row else ""
        data = build_receipt_pdf(b, o, c, items, pays, logo, f"{self.base_url()}/receipt/{token}", kind, due, ps["state"] != "pro")
        stem = re.sub(r"[^A-Za-z0-9_-]", "_", o["order_number"]) + {"receipt": "", "invoice": "-invoice", "thermal": "-slip"}[kind]
        disp = "inline" if qs.get("view", [""])[0] else "attachment"
        self.send_bytes(data, 200, "application/pdf", {"Content-Disposition": f'{disp}; filename="{stem}.pdf"', "X-Robots-Tag": "noindex"})


def default_data_dir() -> str:
    """New installs use ojaloom_data. A server that already has an ojahq_data folder keeps using it, so the rename loses nothing."""
    if not Path("ojaloom_data").exists() and Path("ojahq_data").exists():
        return "ojahq_data"
    return "ojaloom_data"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the self-contained Oja Loom business management server.")
    p.add_argument("--host", default=env("HOST", DEFAULT_HOST), help="Bind address (default: 127.0.0.1; use 0.0.0.0 for LAN/server)")
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", env("PORT", str(DEFAULT_PORT)))), help="HTTP port")
    p.add_argument("--data-dir", default=env("DATA_DIR", default_data_dir()), help="Directory for the SQLite database")
    p.add_argument("--no-browser", action="store_true", help="Do not open a browser automatically")
    p.add_argument("--init-only", action="store_true", help="Create/upgrade the database and exit")
    p.add_argument("--reset-password", metavar="EMAIL", help="Reset an account password from the server console and exit")
    p.add_argument("--enforce-paywall", action="store_true", default=PAYWALL_ENFORCED,
                   help="Lock Pro features for shops whose free trial has ended (or set OJALOOM_ENFORCE_PAYWALL=1)")
    p.add_argument("--make-codes", type=int, metavar="N", help="Print N one-use activation codes for Oja Loom Pro and exit")
    p.add_argument("--code-days", type=int, default=PRO_PERIOD_DAYS, help="Pro days each generated code is worth (default 30)")
    p.add_argument("--operator-name", default=OPERATOR_NAME, help="Name of whoever runs this Oja Loom (shown in the Terms of Service)")
    p.add_argument("--support-email", default=SUPPORT_EMAIL, help="Contact email shown in the Terms of Service")
    p.add_argument("--grant-pro", metavar="EMAIL", help="Give the shop owned by this account free Pro days and exit")
    p.add_argument("--days", type=int, default=PRO_PERIOD_DAYS, help="How many days --grant-pro adds (default 30)")
    p.add_argument(
        "--trust-proxy",
        action="store_true",
        default=env("TRUST_PROXY") in ("1", "true", "yes"),
        help="Trust X-Forwarded-For / X-Forwarded-Proto from a reverse proxy you control",
    )
    p.add_argument(
        "--secure-cookies",
        action="store_true",
        default=env("SECURE_COOKIES") in ("1", "true", "yes"),
        help="Always mark the session cookie Secure (use when the site is served over HTTPS)",
    )
    return p.parse_args()


def main() -> None:
    global DATA_DIR, DB_PATH, TRUST_PROXY, SECURE_COOKIES, PAYWALL_ENFORCED, OPERATOR_NAME, SUPPORT_EMAIL
    args = parse_args()
    OPERATOR_NAME = (args.operator_name or "").strip()[:120]
    SUPPORT_EMAIL = (args.support_email or "").strip()[:120]
    PAYWALL_ENFORCED = bool(args.enforce_paywall)
    TRUST_PROXY = bool(args.trust_proxy)
    SECURE_COOKIES = bool(args.secure_cookies)
    DATA_DIR = Path(args.data_dir).expanduser().resolve()
    DB_PATH = DATA_DIR / "ojaloom.db"
    if not DB_PATH.exists() and (DATA_DIR / "ojahq.db").exists():
        DB_PATH = DATA_DIR / "ojahq.db"          # database created before the rename
    init_db()
    cleanup_sessions()
    if args.reset_password:
        email = validate_email(args.reset_password)
        with db_connect() as conn:
            user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if not user:
                print("No account exists with that email.", file=sys.stderr)
                raise SystemExit(2)
            first = getpass.getpass("New password: ")
            second = getpass.getpass("Confirm password: ")
            if first != second:
                print("Passwords do not match.", file=sys.stderr)
                raise SystemExit(2)
            try:
                validate_password(first, email)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                raise SystemExit(2)
            salt, digest, iters = hash_password(first)
            with transaction(conn, True):
                conn.execute(
                    "UPDATE users SET password_salt=?,password_hash=?,password_iter=?,updated_at=? WHERE id=?",
                    (salt, digest, iters, iso_now(), user["id"]),
                )
                conn.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        print(f"Password reset for {email}. Existing sessions were signed out.")
        return
    if args.make_codes:
        n = max(1, min(args.make_codes, 500))
        with db_connect() as conn, transaction(conn, True):
            codes = make_billing_codes(conn, n, max(1, args.code_days))
        print(f"{n} activation code(s), each worth {max(1, args.code_days)} days of Oja Loom Pro (one use each):")
        for c in codes:
            print("  " + c)
        return
    if args.grant_pro:
        email = validate_email(args.grant_pro)
        with db_connect() as conn, transaction(conn, True):
            user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            biz = user_business(conn, user["id"]) if user else None
            if not biz:
                print("No shop exists for that email.", file=sys.stderr)
                raise SystemExit(2)
            until = grant_pro(conn, biz["id"], max(1, args.days))
            audit(conn, biz["id"], None, "plan", biz["id"], "Oja Loom Pro", "grant", f"Oja Loom Pro granted for {max(1, args.days)} days by the server operator",
                  [audit_change("pro_until", "Pro until", "", until[:10], "date")])
        print(f"{biz['name']} now has Oja Loom Pro until {until[:10]}.")
        return
    if args.init_only:
        print(f"Oja Loom database ready: {DB_PATH}")
        return
    problems = production_problems()
    if ENVIRONMENT == "production" and problems:
        print("Oja Loom will not start in production while these are wrong:", file=sys.stderr)
        for p in problems:
            print("  - " + p, file=sys.stderr)
        raise SystemExit(2)
    server = ThreadingHTTPServer((args.host, args.port), OjaHandler)
    server.daemon_threads = True
    display_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    url = f"http://{display_host}:{args.port}"
    print("\n" + "=" * 64)
    print(f" {APP_NAME} {APP_VERSION}")
    print("=" * 64)
    print(f" Local URL : {url}")
    if args.host in ("0.0.0.0", "::"):
        print(f" Network   : listening on all interfaces, port {args.port}")
        print(" Reminder  : put Oja Loom behind HTTPS before exposing it to the internet")
    print(f" Database  : {DB_PATH}")
    print(f" Proxy     : {'trusting X-Forwarded-* headers' if TRUST_PROXY else 'direct connections only'}")
    print(f" Mode      : {ENVIRONMENT}")
    print(f" Web app   : {FRONTEND_URL}   (allowed origins: {', '.join(sorted(ALLOWED_ORIGINS)) or 'none'})")
    if PUBLIC_API_URL:
        print(f" API url   : {PUBLIC_API_URL}")
    pay_mode = "not set up (activation codes only)" if not PAYSTACK_SECRET else ("TEST keys" if PAYSTACK_SECRET.startswith("sk_test_") else "LIVE keys" if PAYSTACK_SECRET.startswith("sk_live_") else "key format not recognised")
    print(f" Paystack  : {pay_mode}")
    print(f" WhatsApp  : {'PDFs go straight into WhatsApp (Cloud API)' if wa_enabled() else 'share sheet only (Cloud API not configured)'}; support chat +{SUPPORT_WHATSAPP or '-'}")
    if problems:
        print(" WARNING   : not production-ready:")
        for p in problems:
            print("             - " + p)
    print(f" Paywall   : {'ON (Pro features lock when a trial ends)' if PAYWALL_ENFORCED else 'off (everyone has every feature)'}")
    print(" Health    : /health")
    print(" Stop      : Ctrl+C")
    print("=" * 64 + "\n")
    if not args.no_browser and args.host in ("127.0.0.1", "localhost", "0.0.0.0"):
        threading.Timer(0.8, lambda: webbrowser.open(FRONTEND_URL)).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nStopping Oja Loom...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
