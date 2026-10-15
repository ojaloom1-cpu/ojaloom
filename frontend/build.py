#!/usr/bin/env python3
"""Assemble the static web app into dist/ (this is what GitHub Pages publishes).

Settings come from environment variables, so no values are baked into the source:
    API_BASE            https address of the API server, e.g. https://api.example.com     (required)
    SUPPORT_WHATSAPP    support chat number in international format (default 2347074235945)
    FRONTEND_DOMAIN     custom domain for GitHub Pages, e.g. app.example.com             (optional, writes CNAME)

Local development:
    API_BASE=http://127.0.0.1:8000 python build.py && python -m http.server 5173 --directory dist --bind 127.0.0.1

Nothing here is secret. Everything in dist/ is public, by design.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent


def die(msg: str) -> None:
    print(f"build.py: {msg}", file=sys.stderr)
    raise SystemExit(2)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:10]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(HERE / "dist"), help="output folder (default: ./dist)")
    args = ap.parse_args()

    api = os.environ.get("API_BASE", "").strip().rstrip("/")
    if not api:
        die("API_BASE is required, e.g. API_BASE=https://api.example.com")
    u = urlparse(api)
    local = u.hostname in ("localhost", "127.0.0.1")
    if u.scheme not in ("https", "http") or not u.hostname or u.path or u.query or u.fragment or u.username:
        die("API_BASE must look like https://api.example.com (no path, no query)")
    if u.scheme == "http" and not local:
        die("API_BASE must be https. Plain http is only allowed for localhost development")
    origin = f"{u.scheme}://{u.netloc}"

    support = re.sub(r"\D+", "", os.environ.get("SUPPORT_WHATSAPP") or "2347074235945")   # CI passes unset variables as ""
    domain = os.environ.get("FRONTEND_DOMAIN", "").strip().lower()
    if domain and not re.fullmatch(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?", domain):
        die("FRONTEND_DOMAIN must be a bare domain name such as app.example.com")

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    config = out / "config.js"
    config.write_text(
        "window.OJALOOM_CONFIG=Object.freeze(" + json.dumps({"apiBase": api, "supportWhatsapp": support}, separators=(",", ":")) + ");\n",
        encoding="utf-8",
    )
    shutil.copy(HERE / "app.css", out / "app.css")
    shutil.copy(HERE / "app.js", out / "app.js")

    page = (HERE / "index.html").read_text(encoding="utf-8")
    for key, value in {"__API_ORIGIN__": origin, "__CSS_HASH__": digest(out / "app.css"),
                       "__JS_HASH__": digest(out / "app.js"), "__CFG_HASH__": digest(config)}.items():
        if key not in page:
            die(f"index.html lost its {key} placeholder")
        page = page.replace(key, value)
    (out / "index.html").write_text(page, encoding="utf-8")

    (out / ".nojekyll").write_text("", encoding="utf-8")
    if domain:
        (out / "CNAME").write_text(domain + "\n", encoding="utf-8")
    print(f"built {out}  api={origin}  support=+{support}  domain={domain or '-'}")


if __name__ == "__main__":
    main()
