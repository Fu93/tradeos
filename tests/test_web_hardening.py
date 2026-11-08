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
from tests.helpers import FakeExtractor


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
                 rate_limit_global_per_hour=200, paypal_webhook_id="WH-X", trust_cf_connecting_ip=False,
                 allow_public_reset=True, **kw)
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


def test_public_reset_disabled_by_default_without_operator_token(tmp_path):
    """Safe default: allow_public_reset=False so any public host cannot wipe other judges' cases."""
    from app.config import Settings
    from app.intent import KeywordIntentExtractor
    from app.main import create_app
    from app.paypal_mock import MockPayPalClient
    from fastapi.testclient import TestClient
    s = Settings(db_path=str(tmp_path / "no-reset.db"), operator_token="")  # default allow_public_reset=False
    assert s.allow_public_reset is False
    client = TestClient(create_app(settings=s, paypal=MockPayPalClient(), extractor=KeywordIntentExtractor()))
    assert "/demo/reset" not in client.get("/").text
    r = client.post("/demo/reset", follow_redirects=False)
    assert r.status_code == 403 and "disabled on the open shared demo" in r.text


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


def _csrf_guarded_paths(case_id: str, batch_id: str = "batch-1") -> list[str]:
    """Every unsafe browser route the Origin/Referer check guards (webhook is exempt)."""
    return [
        "/demo/run/B",
        "/demo/merchant-order",
        "/merchant/import-sandbox-capture",
        f"/merchant/orders/{case_id}/revoke-return-pass",
        "/demo/agent-scenes",
        "/demo/fill-inbox",
        "/demo/live-agent",
        "/cases/free",
        "/demo/reset",
        f"/cases/{case_id}/approve",
        f"/cases/{case_id}/decline",
        f"/cases/{case_id}/safety-reviewed",
        f"/cases/{case_id}/refund",
        f"/cases/{case_id}/batches/{batch_id}/approve",
        f"/cases/{case_id}/batches/{batch_id}/decline",
        f"/cases/{case_id}/batches/{batch_id}/retry",
        f"/cases/{case_id}/batches/{batch_id}/confirm-refund",
        f"/cases/{case_id}/lines/1/resolve",
        f"/cases/{case_id}/mixed/propose",
        f"/cases/{case_id}/retry-payment",
        f"/cases/{case_id}/retry-policy",
        f"/demo/mock-webhook/{case_id}",
        f"/cases/{case_id}/approve-twice",
        "/disputes/sync",
        "/disputes/D-1/refresh",
        f"/cases/{case_id}/refresh-refund",
        f"/cases/{case_id}/confirm-refund",
        f"/cases/{case_id}/paypal-return",
    ]


def test_malformed_origin_or_referer_is_403_not_500_on_all_csrf_routes(settings):
    """B01: urlsplit ValueError on `Origin: https://[` (or Referer) must not become HTTP 500."""
    client, pp, wf = make(settings)
    case = wf.run_scenario("A")
    before = wf.db.get_case(case)
    chain_before = [(e["seq"], e["entry_hash"]) for e in wf.db.chain_entries(case)]
    timeline_before = wf.db.timeline(case)
    refunds_before = pp.refund_capture.call_count
    bad = ("https://[", "http://[::1", "https://[bad")
    headers_sets = (
        [{"Origin": o} for o in bad]
        + [{"Referer": o} for o in bad]
        + [{"Origin": o, "Referer": o} for o in bad]
    )
    for path in _csrf_guarded_paths(case):
        for headers in headers_sets:
            r = client.post(path, headers=headers, follow_redirects=False)
            assert r.status_code == 403, (path, headers, r.status_code, r.text[:200])
            assert r.status_code != 500
    after = wf.db.get_case(case)
    assert after["status"] == before["status"]
    assert after.get("refund_id") == before.get("refund_id")
    assert [(e["seq"], e["entry_hash"]) for e in wf.db.chain_entries(case)] == chain_before
    assert wf.db.timeline(case) == timeline_before
    assert wf.db.verify_chain(case)["ok"]
    assert pp.refund_capture.call_count == refunds_before
    # Webhook stays CSRF-exempt and must not 500 on the same malformed headers.
    for headers in headers_sets:
        wr = client.post("/webhooks/paypal", content="{}", headers=headers)
        assert wr.status_code == 200 and wr.status_code != 500


def test_origin_of_treats_parse_failures_as_invalid():
    from app.security import _origin_of
    assert _origin_of("https://[") is None
    assert _origin_of("http://[::1") is None
    assert _origin_of("https://tradeos.example") == "tradeos.example"


def test_judge_guidance_and_environment_status_are_visible(settings):
    client, pp, wf = make(settings)
    html = client.get("/").text
    assert "HACKATHON DEMO" in html
    assert "PayPal Sandbox" in html
    assert "No real money" in html
    assert "Judge path" in html
    assert "Buyer agents request. Merchants approve. PayPal confirms." in html
    assert 'action="/demo/agent-scenes"' in html
    assert "LLM: Fallback" in html
    assert "Webhook: configured" in html


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


def test_mobile_css_lets_confirmation_chips_wrap():
    """375px: the 'Signed PayPal webhook: not configured' chip is nowrap by default and forced a horizontal
    scroll; the <=640px block must let .confirm chips wrap and keep the evidence log inside the viewport."""
    from pathlib import Path
    css = (Path(__file__).resolve().parents[1] / "app" / "static" / "style.css").read_text()
    mobile = css[css.index("@media (max-width: 640px)"):]
    assert ".confirm .chip { white-space: normal" in mobile
    assert "details.ev-log { min-width: 0; max-width: 100%; }" in mobile


def test_home_three_step_hint_and_sandbox_notice_without_stale_or_overclaiming_text(settings):
    client, pp, wf = make(settings)
    html = client.get("/").text
    for step in ("Agent asks", "Inspect, then approve", "Compare the refusal"):
        assert step in html
    assert html.index("Agent asks") < html.index("Inspect, then approve") < html.index("Compare the refusal")
    assert "PayPal Sandbox: no real money moves" in html
    assert "This public demo is shared" in html and "ephemeral database" in html
    assert "new PayPal Sandbox demo order" in html and "not looked up" in html
    # the old "wakes up" cold-start note and "free tier" wording are stale on the Starter plan
    assert "Free-tier note" not in html and "wakes up" not in html and "free tier" not in html.lower()
    assert "guaranteed" not in html.lower()


def test_private_persistent_profile_omits_public_shared_ephemeral_notice(tmp_path):
    import base64
    disk = tmp_path / "disk"
    disk.mkdir()
    token = "x" * 24
    s = Settings(db_path=str(disk / "tradeos.db"), persistent_data_dir=str(disk), reset_on_start=False,
                 operator_token=token, public_base_url="https://merchant.example", mcp_enabled=False,
                 allow_public_reset=False, paypal_webhook_id="WH-X", agent_demo_orders=False)
    app = create_app(settings=s, paypal=MagicMock(wraps=MockPayPalClient(), is_mock=True),
                     extractor=FakeExtractor(), note_writer=TemplateNoteWriter())
    auth = "Basic " + base64.b64encode(b"operator:" + token.encode()).decode()
    html = TestClient(app).get("/", headers={"Authorization": auth}).text
    assert "PayPal Sandbox: no real money moves" in html
    assert "This public demo is shared" not in html and "ephemeral database" not in html


def test_local_file_db_omits_public_shared_ephemeral_notice(tmp_path):
    """healthz reports local-file when db_path is outside /tmp; the shared/ephemeral notice must not appear."""
    from pathlib import Path
    # Prefer a non-/tmp path (pytest's tmp_path is usually under /tmp and would look ephemeral).
    root = Path("/var/tmp") if Path("/var/tmp").is_dir() else Path.cwd()
    local = root / f"tradeos-local-file-{tmp_path.name}"
    local.mkdir(parents=True, exist_ok=True)
    try:
        s = Settings(db_path=str(local / "tradeos.db"), allow_public_reset=True, paypal_webhook_id="WH-X",
                     trust_cf_connecting_ip=False)
        assert not s.db_path.startswith("/tmp/")
        assert not s.operator_token and not s.persistent_data_dir
        client, _, _ = make(s)
        html = client.get("/").text
        assert "PayPal Sandbox: no real money moves" in html
        assert "This public demo is shared" not in html and "ephemeral database" not in html
    finally:
        import shutil
        shutil.rmtree(local, ignore_errors=True)


def test_selected_case_next_step_matches_case_type(settings):
    from app.intent import KeywordIntentExtractor
    from app.workflow import EXCHANGE_MESSAGE
    # Keyword extractor so free-text exchange/safety messages classify correctly (FakeExtractor is refund-only).
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    s = Settings(db_path=settings.db_path, rate_limit_per_minute=50, rate_limit_per_hour=200,
                 rate_limit_global_per_hour=500, paypal_webhook_id="WH-X", trust_cf_connecting_ip=False,
                 allow_public_reset=True)
    app = create_app(settings=s, paypal=pp, extractor=KeywordIntentExtractor(), note_writer=TemplateNoteWriter())
    client = TestClient(app)
    wf = app.state.workflow

    refund_id = wf.run_scenario("A")
    exchange_id = wf.run_free_text(EXCHANGE_MESSAGE)
    safety_id = client.post("/cases/free", data={"message": "The sole melted in the heat and burned my foot."},
                            follow_redirects=False).headers["location"].split("case=")[1]
    rejected_id = wf.run_scenario("B")

    refund_html = client.get(f"/?case={refund_id}").text
    assert 'class="case-next-step"' in refund_html
    assert "Approve to refund" in refund_html
    assert "supplier replacement" not in refund_html

    exchange_html = client.get(f"/?case={exchange_id}").text
    assert "Approve the exchange" in exchange_html and "no refund" in exchange_html
    assert "Approve to refund" not in exchange_html
    assert wf.db.get_case(exchange_id)["decision"] == "EXCHANGE_ELIGIBLE"

    safety_html = client.get(f"/?case={safety_id}").text
    assert "safety" in safety_html.lower() and "no money moves" in safety_html
    assert "Approve to refund" not in safety_html

    rejected_html = client.get(f"/?case={rejected_id}").text
    assert "Rejected by the return policy" in rejected_html or "never called" in rejected_html
    assert "Approve to refund" not in rejected_html
    assert pp.refund_capture.call_count == 0
