"""Phase 1 web hardening: client IP, reset cooldown, webhook header gate, security headers, CSRF, errors."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from app.config import Settings
from app.main import create_app
from app.notes import TemplateNoteWriter
from app.paypal_mock import MockPayPalClient
from app.ratelimit import Cooldown, RateLimiter, client_key
from tests.test_upgrade import FakeExtractor


def req(headers=None, host="10.0.0.9"):
    return SimpleNamespace(headers=Headers(headers or {}), client=SimpleNamespace(host=host))


# ---------------------------------------------------------------- (1) client IP
def test_spoofed_leftmost_xff_is_ignored():
    r = req({"x-forwarded-for": "1.2.3.4, 203.0.113.7"})
    assert client_key(r, trusted_hops=1, trust_cf_header=False) == "203.0.113.7"


def test_trusted_hops_count_from_the_right():
    r = req({"x-forwarded-for": "6.6.6.6, 203.0.113.7, 198.51.100.2"})
    assert client_key(r, trusted_hops=2, trust_cf_header=False) == "203.0.113.7"
    assert client_key(r, trusted_hops=1, trust_cf_header=False) == "198.51.100.2"


def test_multiple_xff_headers_joined_and_garbage_falls_back():
    r = SimpleNamespace(headers=Headers(raw=[(b"x-forwarded-for", b"6.6.6.6"), (b"x-forwarded-for", b"203.0.113.7")]),
                        client=SimpleNamespace(host="10.0.0.9"))
    assert client_key(r, 1, False) == "203.0.113.7"
    assert client_key(req({"x-forwarded-for": "not-an-ip"}), 1, False) == "10.0.0.9"
    assert client_key(req({}), 1, False) == "10.0.0.9"


def test_cf_connecting_ip_preferred_when_valid():
    r = req({"cf-connecting-ip": "203.0.113.7", "x-forwarded-for": "1.1.1.1, 2.2.2.2"})
    assert client_key(r, 1, True) == "203.0.113.7"
    assert client_key(req({"cf-connecting-ip": "junk", "x-forwarded-for": "2.2.2.2"}), 1, True) == "2.2.2.2"
    assert client_key(r, 1, False) == "2.2.2.2"


def make(settings, mock=True, **kw):
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=mock)
    s = Settings(db_path=settings.db_path, rate_limit_per_minute=5, rate_limit_per_hour=30,
                 rate_limit_global_per_hour=200, paypal_webhook_id="WH-X", trust_cf_connecting_ip=False, **kw)
    app = create_app(settings=s, paypal=pp, extractor=FakeExtractor(), note_writer=TemplateNoteWriter())
    return TestClient(app), pp, app.state.workflow


def test_rotating_spoofed_xff_cannot_bypass_per_ip_limit(settings):
    client, pp, wf = make(settings)
    codes = [client.post("/demo/run/B", headers={"x-forwarded-for": f"9.9.9.{i}, 203.0.113.7"},
                         follow_redirects=False).status_code for i in range(7)]
    assert codes[:5] == [303] * 5 and codes[5:] == [429, 429]


def test_one_client_cannot_exhaust_global_cap():
    t = [0.0]
    rl = RateLimiter(per_minute=5, per_hour=30, global_per_hour=200, clock=lambda: t[0])
    used = 0
    for i in range(300):
        t[0] += 61 if i % 5 == 0 else 0
        used += rl.check("203.0.113.7") is None
    assert used == 30                       # capped per hour per address
    assert rl.check("198.51.100.1") is None  # others still get through


# ---------------------------------------------------------------- (2) reset
def test_reset_cooldown_per_ip_and_global(settings):
    client, pp, wf = make(settings)
    assert client.post("/demo/reset", follow_redirects=False).status_code == 303
    r = client.post("/demo/reset", follow_redirects=False)
    assert r.status_code == 429 and "Not reset" in r.text
    r2 = client.post("/demo/reset", headers={"x-forwarded-for": "198.51.100.9"}, follow_redirects=False)
    assert r2.status_code == 429 and "someone else" in r2.text
    assert "data-confirm" in client.get("/").text


def test_cooldown_expires():
    t = [0.0]
    c = Cooldown(60, 15, clock=lambda: t[0])
    assert c.check("a") is None and c.check("b") is not None
    t[0] = 16
    assert c.check("b") is None and c.check("a") is not None
    t[0] = 61
    assert c.check("a") is None


# ---------------------------------------------------------------- (3) webhook headers
def test_webhook_missing_signature_headers_rejected_without_verify_call(settings):
    client, pp, wf = make(settings, mock=False)
    ev = {"id": "WH-1", "event_type": "PAYMENT.CAPTURE.REFUNDED", "resource": {"id": "R1", "status": "COMPLETED"}}
    r = client.post("/webhooks/paypal", content=json.dumps(ev), headers={"paypal-transmission-sig": "x"})
    assert r.status_code == 400
    pp.verify_webhook_signature.assert_not_called()
    assert wf.db.webhook_events() == []


def test_webhook_with_all_headers_still_goes_to_verification(settings):
    client, pp, wf = make(settings, mock=False)
    ev = {"id": "WH-2", "event_type": "PAYMENT.CAPTURE.REFUNDED", "resource": {"id": "R1", "status": "COMPLETED"}}
    h = {"paypal-transmission-id": "t", "paypal-transmission-time": "2026-10-10T00:00:00Z",
         "paypal-transmission-sig": "c2ln", "paypal-cert-url": "https://evil.example/c", "paypal-auth-algo": "SHA256withRSA"}
    r = client.post("/webhooks/paypal", content=json.dumps(ev), headers=h)
    assert r.status_code == 200 and r.json()["verified"] is False


def test_webhook_csrf_exempt(settings):
    client, pp, wf = make(settings)
    r = client.post("/webhooks/paypal", content="{}", headers={"origin": "https://evil.example"})
    assert r.status_code == 200


# ---------------------------------------------------------------- (4) headers + CSRF
def test_security_headers_on_pages_and_errors(settings):
    client, pp, wf = make(settings)
    for r in (client.get("/"), client.get("/healthz"), client.get("/nope", headers={"accept": "text/html"})):
        h = r.headers
        assert "script-src 'self'" in h["content-security-policy"] and "frame-ancestors 'none'" in h["content-security-policy"]
        assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
        assert h["strict-transport-security"].startswith("max-age=") and h["referrer-policy"]


def test_templates_have_no_inline_script_or_style(settings):
    client, pp, wf = make(settings)
    case = wf.db.list_cases()[0]["id"]
    html = client.get(f"/?case={case}").text
    import re
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert " style=" not in html and "<style" not in html
    assert not re.search(r"\son[a-z]+=", html)


def test_csrf_cross_origin_post_blocked_same_origin_allowed(settings):
    client, pp, wf = make(settings)
    paths = ["/demo/run/B", "/demo/reset", "/cases/free"]
    case = wf.db.list_cases()[0]["id"]
    paths += [f"/cases/{case}/{a}" for a in ("approve", "decline", "refund", "refresh-refund", "approve-twice")]
    for p in paths:
        assert client.post(p, headers={"origin": "https://evil.example"}, follow_redirects=False).status_code == 403, p
        assert client.post(p, headers={"origin": "null"}, follow_redirects=False).status_code == 403, p
        assert client.post(p, headers={"referer": "https://evil.example/x"}, follow_redirects=False).status_code == 403
    assert pp.refund_capture.call_count == 0
    ok = client.post("/demo/run/B", headers={"origin": "http://testserver"}, follow_redirects=False)
    assert ok.status_code == 303
    ok2 = client.post("/demo/run/B", headers={"referer": "http://testserver/?case=x"}, follow_redirects=False)
    assert ok2.status_code == 303


# ---------------------------------------------------------------- (5) small fixes
def test_head_root_and_html_404(settings):
    client, pp, wf = make(settings)
    assert client.head("/").status_code == 200
    r = client.get("/no/such/page", headers={"accept": "text/html"})
    assert r.status_code == 404 and "Page not found" in r.text and "<html" in r.text
    assert client.get("/api/cases/NOPE", headers={"accept": "text/html"}).headers["content-type"].startswith("application/json")
    assert client.get("/api/cases/NOPE").status_code == 404


def test_case_a_once_case_b_409_unchanged(settings):
    client, pp, wf = make(settings)
    a = client.post("/demo/run/A", follow_redirects=False).headers["location"].split("case=")[1]
    client.post(f"/cases/{a}/approve", follow_redirects=False)
    b = client.post("/demo/run/B", follow_redirects=False).headers["location"].split("case=")[1]
    assert client.post(f"/cases/{b}/approve", follow_redirects=False).status_code == 409
    assert pp.refund_capture.call_count == 1
