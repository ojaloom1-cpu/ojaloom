#!/usr/bin/env python3
"""End-to-end tests for the split backend. Standard library only:  python3 tests/test_backend.py

The real server runs as a subprocess. Paystack and Meta's WhatsApp Graph API are replaced by small local mock servers,
so these tests prove OUR side of both protocols (what we send, what we verify) without any network or real keys.
"""
import hashlib
import hmac
import http.client
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "backend" / "ojaloom_server.py"
FRONTEND = "http://127.0.0.1:5173"
PAYSTACK_KEY = "sk_test_unittest_key"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ------------------------------------------------------------------------------------------------ mock servers
class Mock:
    """A tiny HTTP server that records every request and answers from `routes`."""

    def __init__(self):
        self.calls: list[dict] = []
        self.verify: dict[str, dict] = {}          # reference -> Paystack "data" object to return
        self.graph_error: dict | None = None       # when set, the Graph API answers with this error
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _read(self) -> bytes:
                n = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(n) if n else b""

            def _send(self, obj, code=200):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                outer.calls.append({"method": "GET", "path": self.path, "auth": self.headers.get("Authorization")})
                m = re.fullmatch(r"/transaction/verify/(.+)", self.path)
                if m:
                    return self._send({"status": True, "data": outer.verify.get(m.group(1), {"status": "abandoned"})})
                self._send({"status": False}, 404)

            def do_POST(self):
                raw = self._read()
                outer.calls.append({"method": "POST", "path": self.path, "auth": self.headers.get("Authorization"),
                                    "ctype": self.headers.get("Content-Type", ""), "raw": raw})
                if self.path == "/transaction/initialize":
                    ref = json.loads(raw)["reference"]
                    return self._send({"status": True, "message": "ok", "data": {"authorization_url": "https://checkout.paystack.test/" + ref, "reference": ref}})
                if self.path.endswith("/media"):
                    if outer.graph_error:
                        return self._send(outer.graph_error, 400)
                    return self._send({"id": "MEDIA123"})
                if self.path.endswith("/messages"):
                    if outer.graph_error:
                        return self._send(outer.graph_error, 400)
                    return self._send({"messaging_product": "whatsapp", "messages": [{"id": "wamid.TEST"}]})
                self._send({}, 404)

        self.port = free_port()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.port}"

    def stop(self):
        self.httpd.shutdown()


# ------------------------------------------------------------------------------------------------ a client that behaves like the browser
class Client:
    def __init__(self, port: int, origin: str | None = FRONTEND):
        self.port, self.origin, self.cookie, self.csrf = port, origin, "", ""

    def req(self, method: str, path: str, body=None, *, origin="default", csrf=True, headers=None, raw: bytes | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Accept": "application/json"}
        o = self.origin if origin == "default" else origin
        if o:
            h["Origin"] = o
        if self.cookie:
            h["Cookie"] = self.cookie
        if csrf and self.csrf and method != "GET":
            h["X-CSRF-Token"] = self.csrf
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        conn.request(method, path, body=data, headers=h)
        res = conn.getresponse()
        payload = res.read()
        for k, v in res.getheaders():
            if k.lower() == "set-cookie":
                self.cookie = v.split(";", 1)[0]
        ctype = res.getheader("Content-Type", "")
        parsed = json.loads(payload) if "json" in ctype and payload else payload
        conn.close()
        return res.status, {k.lower(): v for k, v in res.getheaders()}, parsed

    def signup(self, email: str, shop: str):
        s, _, d = self.req("POST", "/api/signup", {"email": email, "password": "correct horse battery 42", "owner_name": "Test Owner",
                           "business_name": shop, "category": "Fashion & Clothing", "phone": "08030000000", "accept_terms": "1"})
        assert s in (200, 201), (s, d)
        self.csrf = d.get("csrf") or self.req("GET", "/api/me")[2]["csrf"]
        return d


def start_server(env_extra: dict, *flags: str):
    data = tempfile.mkdtemp(prefix="oj_test_")
    port = free_port()
    env = {**os.environ, "OJALOOM_ENV": "development", "OJALOOM_FRONTEND_URL": FRONTEND, **env_extra}
    for k in list(env):
        if k.startswith("OJALOOM_") and k not in env_extra and k not in ("OJALOOM_ENV", "OJALOOM_FRONTEND_URL"):
            del env[k]
    proc = subprocess.Popen([sys.executable, str(SERVER), "--port", str(port), "--no-browser", "--data-dir", data, *flags],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(60):
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            c.request("GET", "/health")
            if c.getresponse().status == 200:
                return proc, port, data
        except OSError:
            time.sleep(0.15)
        if proc.poll() is not None:
            raise RuntimeError("server exited early:\n" + proc.stdout.read())
    proc.kill()
    raise RuntimeError("server did not start")


def stop_server(proc, data):
    proc.terminate()
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        proc.kill()
    shutil.rmtree(data, ignore_errors=True)


def db_rows(data: str, sql: str, args=()):
    conn = sqlite3.connect(os.path.join(data, "ojaloom.db"))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


# ------------------------------------------------------------------------------------------------ the tests
class FullStack(unittest.TestCase):
    """Server configured like production: API base, Paystack + WhatsApp Cloud API pointed at mocks."""

    @classmethod
    def setUpClass(cls):
        cls.mock = Mock()
        cls.proc, cls.port, cls.data = start_server({
            "OJALOOM_PAYSTACK_SECRET": PAYSTACK_KEY, "OJALOOM_PAYSTACK_BASE": cls.mock.url,
            "OJALOOM_WA_TOKEN": "wa_token_unittest", "OJALOOM_WA_PHONE_ID": "1234567890",
            "OJALOOM_WA_GRAPH_BASE": cls.mock.url, "OJALOOM_PUBLIC_API_URL": "https://api.example.test",
        })
        cls.api = Client(cls.port)
        cls.api.signup("owner@example.test", "Ada Fabrics")
        _, _, p = cls.api.req("POST", "/api/products", {"name": "Ankara 6 yards", "selling_price": 5000, "cost_price": 3000, "stock_quantity": 50})
        _, _, c = cls.api.req("POST", "/api/customers", {"full_name": "Chioma Obi", "phone": "0803 123 4567", "email": "chioma@example.test"})
        cls.customer_id = c["id"]
        s, _, o = cls.api.req("POST", "/api/orders", {"customer_id": cls.customer_id, "items": [{"product_id": p["product"]["id"], "quantity": 3}],
                              "status": "pending", "payment_method": "Cash", "initial_payment": 5000})
        assert s in (200, 201), (s, o)
        cls.order_id = o.get("id") or o["order"]["id"]
        _, _, rc = cls.api.req("GET", "/api/receipts")
        cls.token = rc["items"][0]["public_token"]
        cls.receipts = rc

    @classmethod
    def tearDownClass(cls):
        stop_server(cls.proc, cls.data)
        cls.mock.stop()

    # ---- basics ----------------------------------------------------------------------------
    def test_boot_is_public_and_tells_the_app_about_direct_whatsapp(self):
        s, h, d = Client(self.port).req("GET", "/api/boot")
        self.assertEqual(s, 200)
        self.assertTrue(d["share"]["whatsapp_direct"])
        self.assertGreater(len(d["categories"]), 5)
        self.assertEqual(h["access-control-allow-origin"], FRONTEND)
        self.assertEqual(h["access-control-allow-credentials"], "true")

    def test_cors_only_for_our_frontend(self):
        s, h, _ = Client(self.port).req("OPTIONS", "/api/login", origin="https://evil.example", headers={"Access-Control-Request-Method": "POST"})
        self.assertEqual(s, 403)
        self.assertNotIn("access-control-allow-origin", h)
        s, h, _ = Client(self.port).req("GET", "/api/boot", origin="https://evil.example")
        self.assertNotIn("access-control-allow-origin", h, "a stranger's website must never be allowed to read responses")
        s, h, _ = Client(self.port).req("OPTIONS", "/api/login", headers={"Access-Control-Request-Method": "POST"})
        self.assertEqual(s, 204)
        self.assertIn("x-csrf-token", h["access-control-allow-headers"].lower())

    def test_session_cookie_is_httponly_samesite_strict(self):
        c = Client(self.port)
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("POST", "/api/signup", body=json.dumps({"email": "cookie@example.test", "password": "correct horse battery 42", "owner_name": "C",
                     "business_name": "Cookie Shop", "category": "Fashion & Clothing", "phone": "08030000001", "accept_terms": "1"}),
                     headers={"Content-Type": "application/json", "Origin": FRONTEND})
        res = conn.getresponse(); res.read()
        cookie = res.getheader("Set-Cookie") or ""
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertNotIn("Domain=", cookie, "host-only cookie: never shared with sibling subdomains")
        del c

    def test_writes_need_csrf_and_a_trusted_origin(self):
        body = {"full_name": "Nobody", "phone": "08031112222"}
        s, _, _ = self.api.req("POST", "/api/customers", body, csrf=False)
        self.assertEqual(s, 403, "no CSRF token")
        s, _, _ = self.api.req("POST", "/api/customers", body, origin="https://evil.example")
        self.assertEqual(s, 403, "wrong origin")
        s, _, _ = self.api.req("POST", "/api/customers", body)
        self.assertEqual(s, 201)

    # ---- data the Send menu relies on --------------------------------------------------------
    def test_lists_carry_customer_email_for_the_send_menu(self):
        self.assertEqual(self.receipts["items"][0]["customer_email"], "chioma@example.test")
        _, _, debts = self.api.req("GET", "/api/debts")
        item = debts["items"][0]
        self.assertEqual(item["customer_email"], "chioma@example.test")
        self.assertEqual(item["customer_phone"], "2348031234567")

    def test_public_pages_link_back_to_the_frontend_and_offer_both_send_options(self):
        s, h, page = Client(self.port, None).req("GET", f"/receipt/{self.token}")
        html = page.decode()
        self.assertEqual(s, 200)
        self.assertIn('id="wa"', html)
        self.assertIn('id="mail"', html)
        self.assertIn("mailto:chioma%40example.test", html.replace("chioma@example.test", "chioma%40example.test"))
        self.assertNotIn('href="/#/', html, "links to the web app must be absolute now")
        s, _, terms = Client(self.port, None).req("GET", "/terms")
        t = terms.decode()
        self.assertIn("https://wa.me/2347074235945", t, "support WhatsApp is on the Terms page")
        self.assertIn(f'href="{FRONTEND}/"', t)
        s, h, _ = Client(self.port, None).req("GET", "/receipt/nope-nope-nope")
        self.assertEqual(s, 404)

    # ---- Paystack ----------------------------------------------------------------------------
    def _start_checkout(self):
        self.mock.calls.clear()
        s, _, d = self.api.req("POST", "/api/plan/checkout", {})
        self.assertEqual(s, 200, d)
        ref = d["url"].rsplit("/", 1)[1]
        return ref, d

    def test_paystack_checkout_initialises_with_secret_and_api_callback(self):
        ref, d = self._start_checkout()
        init = next(c for c in self.mock.calls if c["path"] == "/transaction/initialize")
        self.assertEqual(init["auth"], "Bearer " + PAYSTACK_KEY)
        sent = json.loads(init["raw"])
        self.assertEqual(sent["callback_url"], "https://api.example.test/billing/return", "callback must be the configured API address, not a Host header")
        self.assertEqual(sent["currency"], "NGN")
        self.assertEqual(sent["email"], "owner@example.test")
        self.assertEqual(db_rows(self.data, "SELECT status FROM billing_payments WHERE reference=?", (ref,))[0]["status"], "pending")
        self.assertTrue(d["url"].startswith("https://checkout.paystack.test/"))

    def _webhook(self, event: dict, key=PAYSTACK_KEY, sig=None):
        raw = json.dumps(event).encode()
        signature = sig if sig is not None else hmac.new(key.encode(), raw, hashlib.sha512).hexdigest()
        return Client(self.port, None).req("POST", "/webhooks/paystack", raw=raw, headers={"X-Paystack-Signature": signature, "Content-Type": "application/json"})

    def test_paystack_webhook_rejects_bad_or_missing_signature(self):
        ref, _ = self._start_checkout()
        self.mock.verify[ref] = {"status": "success", "amount": 0, "currency": "NGN"}
        event = {"event": "charge.success", "data": {"reference": ref}}
        self.assertEqual(self._webhook(event, sig="0" * 128)[0], 401)
        self.assertEqual(self._webhook(event, key="sk_test_someone_else")[0], 401)
        s, _, _ = Client(self.port, None).req("POST", "/webhooks/paystack", raw=json.dumps(event).encode())
        self.assertEqual(s, 401)
        self.assertEqual(db_rows(self.data, "SELECT status FROM billing_payments WHERE reference=?", (ref,))[0]["status"], "pending")

    def test_paystack_payment_is_confirmed_with_paystack_and_granted_once(self):
        ref, _ = self._start_checkout()
        row = db_rows(self.data, "SELECT amount, business_id FROM billing_payments WHERE reference=?", (ref,))[0]
        self.mock.verify[ref] = {"status": "success", "amount": row["amount"], "currency": "NGN", "reference": ref}
        before = db_rows(self.data, "SELECT pro_until FROM businesses WHERE id=?", (row["business_id"],))[0]["pro_until"]
        self.mock.calls.clear()
        self.assertEqual(self._webhook({"event": "charge.success", "data": {"reference": ref}})[0], 200)
        self.assertTrue(any(c["path"] == "/transaction/verify/" + ref for c in self.mock.calls), "must verify with Paystack, not trust the webhook body")
        self.assertEqual(db_rows(self.data, "SELECT status FROM billing_payments WHERE reference=?", (ref,))[0]["status"], "paid")
        after = db_rows(self.data, "SELECT pro_until FROM businesses WHERE id=?", (row["business_id"],))[0]["pro_until"]
        self.assertNotEqual(before, after, "Pro days were added")
        self._webhook({"event": "charge.success", "data": {"reference": ref}})
        again = db_rows(self.data, "SELECT pro_until FROM businesses WHERE id=?", (row["business_id"],))[0]["pro_until"]
        self.assertEqual(after, again, "a repeated webhook must not grant a second month")

    def test_paystack_wrong_amount_or_failed_payment_grants_nothing(self):
        ref, _ = self._start_checkout()
        self.mock.verify[ref] = {"status": "success", "amount": 100, "currency": "NGN"}   # paid 1 naira instead of the price
        self._webhook({"event": "charge.success", "data": {"reference": ref}})
        self.assertEqual(db_rows(self.data, "SELECT status FROM billing_payments WHERE reference=?", (ref,))[0]["status"], "pending")
        ref2, _ = self._start_checkout()
        self.mock.verify[ref2] = {"status": "failed", "amount": 0, "currency": "NGN"}
        self._webhook({"event": "charge.success", "data": {"reference": ref2}})
        self.assertEqual(db_rows(self.data, "SELECT status FROM billing_payments WHERE reference=?", (ref2,))[0]["status"], "pending")

    def test_paystack_return_page_confirms_and_sends_shopper_to_the_web_app(self):
        ref, _ = self._start_checkout()
        amount = db_rows(self.data, "SELECT amount FROM billing_payments WHERE reference=?", (ref,))[0]["amount"]
        self.mock.verify[ref] = {"status": "success", "amount": amount, "currency": "NGN"}
        s, _, page = Client(self.port, None).req("GET", f"/billing/return?reference={ref}")
        self.assertEqual(s, 200)
        self.assertIn(f"url={FRONTEND}/#/billing?paid=1", page.decode())
        s, _, page = Client(self.port, None).req("GET", "/billing/return?reference=OJAUNKNOWN123456")
        self.assertIn("paid=0", page.decode())

    # ---- WhatsApp: PDF straight into the customer's chat -------------------------------------
    def _wa_calls(self):
        media = [c for c in self.mock.calls if c["path"].endswith("/media")]
        msgs = [c for c in self.mock.calls if c["path"].endswith("/messages")]
        return media, msgs

    def test_whatsapp_receipt_pdf_is_uploaded_then_sent_as_template_document(self):
        self.mock.calls.clear(); self.mock.graph_error = None
        s, _, d = self.api.req("POST", "/api/share/whatsapp", {"doc": "receipt", "ref": self.token})
        self.assertEqual((s, d), (200, {"ok": True}))
        media, msgs = self._wa_calls()
        self.assertEqual(len(media), 1)
        self.assertEqual(len(msgs), 1)
        up = media[0]
        self.assertEqual(up["path"], "/v23.0/1234567890/media")
        self.assertEqual(up["auth"], "Bearer wa_token_unittest")
        self.assertTrue(up["ctype"].startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="messaging_product"\r\n\r\nwhatsapp', up["raw"])
        self.assertIn(b"Content-Type: application/pdf", up["raw"])
        self.assertIn(b"%PDF-", up["raw"], "a real PDF is attached")
        self.assertIn(b"%%EOF", up["raw"])
        body = json.loads(msgs[0]["raw"])
        self.assertEqual(body["to"], "2348031234567", "number comes from the customer record, normalised")
        self.assertEqual(body["type"], "template")
        self.assertEqual(body["template"]["name"], "ojaloom_receipt")
        header, text = body["template"]["components"]
        self.assertEqual(header["parameters"][0]["document"]["id"], "MEDIA123")
        self.assertTrue(header["parameters"][0]["document"]["filename"].endswith(".pdf"))
        params = [p["text"] for p in text["parameters"]]
        self.assertEqual(params[0], "Chioma")
        self.assertEqual(params[2], "Ada Fabrics")
        self.assertIn("balance due", params[3])
        log = db_rows(self.data, "SELECT * FROM outbound_messages WHERE provider_id='wamid.TEST' AND doc='receipt' AND ref=?", (self.token,))
        self.assertTrue(log, "the delivery is recorded")
        self.assertEqual((log[0]["status"], log[0]["to_phone"]), ("sent", "2348031234567"))

    def test_whatsapp_statement_pdf(self):
        self.mock.calls.clear(); self.mock.graph_error = None
        s, _, d = self.api.req("POST", "/api/share/whatsapp", {"doc": "statement", "ref": self.customer_id})
        self.assertEqual(s, 200, d)
        _, msgs = self._wa_calls()
        body = json.loads(msgs[0]["raw"])
        self.assertEqual(body["template"]["name"], "ojaloom_statement")
        self.assertEqual(len(body["template"]["components"][1]["parameters"]), 3)
        self.assertIn("Balance owing", body["template"]["components"][1]["parameters"][2]["text"])

    def test_whatsapp_delivery_error_is_friendly_and_logged(self):
        self.mock.calls.clear()
        self.mock.graph_error = {"error": {"message": "secret internal detail +2348031234567", "code": 131026, "fbtrace_id": "T1"}}
        try:
            s, _, d = self.api.req("POST", "/api/share/whatsapp", {"doc": "receipt", "ref": self.token})
        finally:
            self.mock.graph_error = None
        self.assertEqual(s, 422)
        self.assertIn("may not be on WhatsApp", d["error"])
        self.assertNotIn("secret internal detail", json.dumps(d), "provider text is never shown to the shop owner")
        failed = db_rows(self.data, "SELECT error FROM outbound_messages WHERE status='failed' AND doc='receipt'")
        self.assertTrue(failed, "the failure is recorded")
        self.assertNotIn("secret internal detail", failed[0]["error"])

    def test_whatsapp_endpoint_cannot_be_used_as_a_relay(self):
        self.mock.calls.clear()
        # somebody else's shop and its receipt
        other = Client(self.port)
        other.signup("other@example.test", "Other Shop")
        s, _, d = other.req("POST", "/api/share/whatsapp", {"doc": "receipt", "ref": self.token})
        self.assertEqual(s, 404, "another shop's receipt looks exactly like a missing one")
        s, _, _ = other.req("POST", "/api/share/whatsapp", {"doc": "statement", "ref": self.customer_id})
        self.assertEqual(s, 404)
        # arbitrary documents / numbers / files are not accepted at all
        self.assertEqual(self.api.req("POST", "/api/share/whatsapp", {"doc": "anything", "ref": "x"})[0], 400)
        self.assertEqual(self.api.req("POST", "/api/share/whatsapp", {"doc": "receipt"})[0], 400)
        s, _, _ = self.api.req("POST", "/api/share/whatsapp", {"doc": "receipt", "ref": self.token, "phone": "2348000000000", "to": "2348000000000"})
        self.assertEqual(s, 200)
        _, msgs = self._wa_calls()
        self.assertEqual(json.loads(msgs[-1]["raw"])["to"], "2348031234567", "a client-supplied number is ignored")
        # login + CSRF are required
        self.assertEqual(Client(self.port).req("POST", "/api/share/whatsapp", {"doc": "receipt", "ref": self.token})[0], 401)
        self.assertEqual(self.api.req("POST", "/api/share/whatsapp", {"doc": "receipt", "ref": self.token}, csrf=False)[0], 403)

    def test_whatsapp_daily_cap_per_customer(self):
        # its own customer, so the allowance used up here cannot affect the other tests
        self.mock.graph_error = None
        _, _, c = self.api.req("POST", "/api/customers", {"full_name": "Cap Test", "phone": "08077777777", "email": ""})
        _, _, p = self.api.req("POST", "/api/products", {"name": "Cap item", "selling_price": 100, "cost_price": 50, "stock_quantity": 5})
        s, _, o = self.api.req("POST", "/api/orders", {"customer_id": c["id"], "items": [{"product_id": p["product"]["id"], "quantity": 1}],
                                                       "status": "pending", "payment_method": "Cash", "initial_payment": 10})
        self.assertIn(s, (200, 201))
        token = next(r["public_token"] for r in self.api.req("GET", "/api/receipts")[2]["items"] if r["customer_name"] == "Cap Test")
        codes = [self.api.req("POST", "/api/share/whatsapp", {"doc": "receipt", "ref": token})[0] for _ in range(14)]
        self.assertEqual(codes[:10], [200] * 10)
        self.assertEqual(set(codes[10:]), {429}, "one customer cannot be spammed with PDFs")
        sent = db_rows(self.data, "SELECT COUNT(*) n FROM outbound_messages WHERE status='sent' AND to_phone='2348077777777'")[0]["n"]
        self.assertEqual(sent, 10)


class NoIntegrations(unittest.TestCase):
    """A bare server: Paystack and WhatsApp Cloud API are not configured, and the app is told so."""

    @classmethod
    def setUpClass(cls):
        cls.proc, cls.port, cls.data = start_server({})
        cls.api = Client(cls.port)
        cls.api.signup("bare@example.test", "Bare Shop")

    @classmethod
    def tearDownClass(cls):
        stop_server(cls.proc, cls.data)

    def test_direct_whatsapp_is_off_and_refused(self):
        self.assertFalse(Client(self.port).req("GET", "/api/boot")[2]["share"]["whatsapp_direct"])
        s, _, d = self.api.req("POST", "/api/share/whatsapp", {"doc": "receipt", "ref": "x" * 12})
        self.assertEqual(s, 503)

    def test_checkout_says_so_when_paystack_is_not_configured(self):
        s, _, d = self.api.req("POST", "/api/plan/checkout", {})
        self.assertEqual(s, 503)
        s, _, _ = Client(self.port, None).req("POST", "/webhooks/paystack", raw=b'{"event":"charge.success"}', headers={"X-Paystack-Signature": "abc"})
        self.assertEqual(s, 401, "webhook is closed without a secret")


class ProductionBehindProxy(unittest.TestCase):
    """A correctly configured production server, reached the way Caddy reaches it (X-Forwarded-Proto: https)."""

    @classmethod
    def setUpClass(cls):
        cls.proc, cls.port, cls.data = start_server({
            "OJALOOM_ENV": "production", "OJALOOM_FRONTEND_URL": "https://app.example.com",
            "OJALOOM_PUBLIC_API_URL": "https://api.example.com", "OJALOOM_ALLOWED_ORIGINS": "https://app.example.com",
        }, "--trust-proxy", "--secure-cookies")

    @classmethod
    def tearDownClass(cls):
        stop_server(cls.proc, cls.data)

    def _post(self, path, body, origin):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", path, body=json.dumps(body), headers={"Content-Type": "application/json", "Origin": origin, "X-Forwarded-Proto": "https", "X-Forwarded-For": "203.0.113.9"})
        res = conn.getresponse(); res.read()
        return res

    def test_cookie_is_secure_and_hsts_is_sent(self):
        res = self._post("/api/signup", {"email": "p@example.test", "password": "correct horse battery 42", "owner_name": "P", "business_name": "Prod Shop",
                                         "category": "Fashion & Clothing", "phone": "08030000009", "accept_terms": "1"}, "https://app.example.com")
        self.assertIn(res.status, (200, 201))
        cookie = res.getheader("Set-Cookie") or ""
        for flag in ("Secure", "HttpOnly", "SameSite=Strict"):
            self.assertIn(flag, cookie)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/health", headers={"X-Forwarded-Proto": "https"})
        res = conn.getresponse(); res.read()
        self.assertIn("max-age", res.getheader("Strict-Transport-Security") or "")

    def test_localhost_frontend_is_not_trusted_in_production(self):
        res = self._post("/api/login", {"email": "p@example.test", "password": "x"}, "http://127.0.0.1:5173")
        self.assertEqual(res.status, 403)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("OPTIONS", "/api/login", headers={"Origin": "http://127.0.0.1:5173", "Access-Control-Request-Method": "POST"})
        res = conn.getresponse(); res.read()
        self.assertEqual(res.status, 403)


class ProductionGuard(unittest.TestCase):
    """In production the server refuses to start while the setup is unsafe."""

    def _run(self, env_extra: dict, *flags: str, wait=2.5):
        env = {**os.environ, **{k: v for k, v in env_extra.items()}}
        data = tempfile.mkdtemp(prefix="oj_prod_")
        port = free_port()
        p = subprocess.Popen([sys.executable, str(SERVER), "--port", str(port), "--no-browser", "--data-dir", data, *flags], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            out, err = p.communicate(timeout=wait)
            return p.returncode, out + err, None, data
        except subprocess.TimeoutExpired:
            ok = False
            try:
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=2); c.request("GET", "/health"); ok = c.getresponse().status == 200
            except OSError:
                pass
            p.terminate(); p.wait(5)
            return None, "", ok, data

    def test_refuses_to_start_with_defaults(self):
        code, text, _, data = self._run({"OJALOOM_ENV": "production"})
        shutil.rmtree(data, ignore_errors=True)
        self.assertEqual(code, 2)
        for needle in ("FRONTEND_URL", "PUBLIC_API_URL", "ALLOWED_ORIGINS", "--trust-proxy", "--secure-cookies"):
            self.assertIn(needle, text)

    def test_refuses_github_io_frontend(self):
        code, text, _, data = self._run({"OJALOOM_ENV": "production", "OJALOOM_FRONTEND_URL": "https://me.github.io", "OJALOOM_PUBLIC_API_URL": "https://api.example.com",
                                         "OJALOOM_ALLOWED_ORIGINS": "https://me.github.io"}, "--trust-proxy", "--secure-cookies")
        shutil.rmtree(data, ignore_errors=True)
        self.assertEqual(code, 2)
        self.assertIn("public suffix", text)

    def test_refuses_different_registrable_domains(self):
        code, text, _, data = self._run({"OJALOOM_ENV": "production", "OJALOOM_FRONTEND_URL": "https://app.example.com", "OJALOOM_PUBLIC_API_URL": "https://api.other.org",
                                         "OJALOOM_ALLOWED_ORIGINS": "https://app.example.com"}, "--trust-proxy", "--secure-cookies")
        shutil.rmtree(data, ignore_errors=True)
        self.assertEqual(code, 2)
        self.assertIn("registrable domain", text)

    def test_refuses_to_talk_to_a_fake_paystack(self):
        code, text, _, data = self._run({"OJALOOM_ENV": "production", "OJALOOM_FRONTEND_URL": "https://app.example.com", "OJALOOM_PUBLIC_API_URL": "https://api.example.com",
                                         "OJALOOM_ALLOWED_ORIGINS": "https://app.example.com", "OJALOOM_PAYSTACK_BASE": "http://evil.example"}, "--trust-proxy", "--secure-cookies")
        shutil.rmtree(data, ignore_errors=True)
        self.assertEqual(code, 2)
        self.assertIn("PAYSTACK_BASE", text)

    def test_starts_with_a_correct_production_setup_and_marks_cookies_secure(self):
        code, _, ok, data = self._run({"OJALOOM_ENV": "production", "OJALOOM_FRONTEND_URL": "https://app.example.com", "OJALOOM_PUBLIC_API_URL": "https://api.example.com",
                                       "OJALOOM_ALLOWED_ORIGINS": "https://app.example.com"}, "--trust-proxy", "--secure-cookies")
        shutil.rmtree(data, ignore_errors=True)
        self.assertIsNone(code, "server stayed up")
        self.assertTrue(ok, "health check answered")


if __name__ == "__main__":
    unittest.main(verbosity=2)
