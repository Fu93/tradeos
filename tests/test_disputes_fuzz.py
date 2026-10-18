"""Adversarial / malformed input for the CUSTOMER.DISPUTE.* webhook and /disputes view: never a 500, never a
stored dispute from an unsigned event, and one poisoned record can never break the page for the others."""
import json

import pytest

from tests.helpers import SIG_BAD, SIG_OK, make_app, run_a
from tests.test_disputes import dispute, event

ET = "CUSTOMER.DISPUTE.UPDATED"


@pytest.fixture
def ctx(settings):
    client, pp, wf = make_app(settings)
    case_id = run_a(client)
    return client, pp, wf, case_id, wf.db.get_case(case_id)["capture_id"]


def send(client, body, headers=SIG_OK):
    raw = body if isinstance(body, (bytes, str)) else json.dumps(body)
    return client.post("/webhooks/paypal", content=raw, headers=headers)


NASTY_RESOURCES = [
    {"dispute_id": 123}, {"dispute_id": True}, {"dispute_id": ["a"]}, {"dispute_id": {"a": 1}},
    {"dispute_id": "D" * 100000}, {"dispute_id": "<script>alert(1)</script>"}, {"dispute_id": "a\x00b\u202e\ud83d"},
    {"dispute_id": "D1", "disputed_transactions": 5}, {"dispute_id": "D1", "disputed_transactions": "abc"},
    {"dispute_id": "D1", "disputed_transactions": [None, 1, "x", [], {"seller_transaction_id": {"a": 1}}]},
    {"dispute_id": "D1", "disputed_transactions": {"seller_transaction_id": "X"}},
    {"dispute_id": "D1", "dispute_amount": "49.99"}, {"dispute_id": "D1", "dispute_amount": {"value": "NaN"}},
    {"dispute_id": "D1", "dispute_amount": {"value": "-5", "currency_code": "USD"}},
    {"dispute_id": "D1", "dispute_amount": {"value": "9" * 5000, "currency_code": "U" * 5000}},
    {"dispute_id": "D1", "dispute_amount": {"value": "1e999999999", "currency_code": "USD"}},
    {"dispute_id": "D1", "dispute_amount": {"value": [1], "currency_code": {"x": 1}}},
    {"dispute_id": "D1", "seller_response_due_date": "not a date"}, {"dispute_id": "D1", "seller_response_due_date": 5},
    {"dispute_id": "D1", "seller_response_due_date": "9999-12-31T00:00:00Z", "update_time": "9999"},
    {"dispute_id": "D1", "status": {"a": 1}, "reason": ["x"], "update_time": 1},
    {"dispute_id": "D1", "status": "<img src=x onerror=alert(1)>", "reason": "\"><svg/onload=alert(1)>"},
    {"dispute_id": "D1", "dispute_amount": {"value": "Infinity", "currency_code": "USD"}},
    "string", 5, None, [], [[[]]],
]


@pytest.mark.parametrize("res", NASTY_RESOURCES, ids=range(len(NASTY_RESOURCES)))
@pytest.mark.parametrize("headers", [SIG_OK, SIG_BAD], ids=["signed", "unsigned"])
def test_malformed_resource_never_500_and_page_still_renders(ctx, res, headers):
    client, _, wf, _, cap = ctx
    assert send(client, event(res, ET, "WH-F"), headers).status_code < 500
    r = client.get("/disputes")
    assert r.status_code == 200
    assert "<script>alert(1)" not in r.text and "<img src=x" not in r.text and "<svg/onload" not in r.text
    if headers is SIG_BAD:
        assert wf.db.list_disputes() == []


@pytest.mark.parametrize("body", [
    b"", b"null", b"[]", b"5", b'"x"', b"{", b"\xff\xfe\x00", b'{"event_type": "CUSTOMER.DISPUTE.CREATED"}',
    b'{"event_type": ["CUSTOMER.DISPUTE.CREATED"]}', b'{"event_type": {"a": 1}, "resource": 1}',
    b'{"event_type": "CUSTOMER.DISPUTE.CREATED", "id": {"x": 1}, "resource": {"dispute_id": "D1"}}',
    b'{"event_type": "CUSTOMER.DISPUTE.CREATED", "id": 12345678901234567890123, "resource": {"dispute_id": "D1"}}',
    b"[" * 200000 + b"]" * 200000, b'{"a":' * 50000 + b"1" + b"}" * 50000,
    b'{"event_type": "CUSTOMER.DISPUTE.CREATED", "resource": ' + b"[" * 100000 + b"]" * 100000 + b"}",
], ids=lambda b: f"{len(b)}b-{b[:12]!r}")
def test_malformed_body_never_500(ctx, body):
    client, *_ = ctx
    assert send(client, body).status_code < 500
    assert send(client, body, SIG_BAD).status_code < 500


def test_oversized_body_rejected_before_any_work(ctx):
    client, _, wf, *_ = ctx
    big = event(dispute(), ET) | {"pad": "x" * (70 * 1024)}
    assert send(client, big).status_code == 400
    assert wf.db.list_disputes() == []


def test_unicode_and_xss_fields_are_escaped_and_capped(ctx):
    client, _, wf, _, cap = ctx
    d = dispute(capture=cap, status="<b>x</b>" * 50, reason="<script>alert(1)</script>")
    d["dispute_id"] = "D<i>1</i>\u202e\u4e2d"
    assert send(client, event(d, ET, "WH-X")).status_code == 200
    html = client.get("/disputes").text
    assert "<script>alert(1)</script>" not in html and "<b>x</b>" not in html and "<i>1</i>" not in html
    assert all(len(v) <= 200 for v in wf.db.list_disputes()[0].values() if isinstance(v, str))


def test_nan_amount_cannot_break_the_page_for_everyone(ctx):
    client, _, wf, _, cap = ctx
    send(client, event(dispute("D-OK", capture=cap), ET, "WH-OK"))
    send(client, event(dispute("D-NAN", capture=cap, amount="NaN"), ET, "WH-NAN"))
    send(client, event(dispute("D-NEG", capture=cap, amount="-100"), ET, "WH-NEG"))
    send(client, event(dispute("D-HUGE", capture=cap, amount="9" * 40), ET, "WH-HUGE"))
    r = client.get("/disputes")
    assert r.status_code == 200 and "D-OK" in r.text and "D-NAN" in r.text


def test_audit_chain_still_verifies_after_hostile_events(ctx):
    client, _, wf, case_id, cap = ctx
    for i, res in enumerate(NASTY_RESOURCES[:12]):
        send(client, event(res, ET, f"WH-{i}"))
        send(client, event(dispute(f"D{i}", capture=cap, status="<x>" * 30), ET, f"WH-ok{i}"))
    assert wf.db.verify_chain(case_id)["ok"] is True


def test_dispute_cannot_attach_to_a_case_by_a_non_capture_id(ctx):
    """Matching is exact on the recorded capture id only: order ids, buyer ids, case ids, prefixes, wildcards."""
    client, _, wf, case_id, cap = ctx
    case = wf.db.get_case(case_id)
    for i, tid in enumerate([case_id, case["order_id"] if case.get("order_id") else "ORD", cap[:-1], cap + " ", cap.lower(),
                             "%", "_", "' OR 1=1 --", "%" + cap[1:]]):
        d = dispute(f"D{i}", capture=tid)
        send(client, event(d, ET, f"WH-m{i}"))
        assert wf.db.get_dispute(f"D{i}")["case_id"] is None, tid


# ---- PayPal failures degrade safely; the fetch endpoints cannot be used to hammer PayPal --------------------------
import logging  # noqa: E402

import httpx  # noqa: E402

from app.paypal_client import PayPalClient  # noqa: E402


def wired(settings, routes, **kw):
    """App whose PayPal client is the REAL PayPalClient over a MockTransport (OAuth ok, disputes via `routes`)."""
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path))
        if req.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "SECRET-TOKEN-123", "expires_in": 3000,
                                             "scope": "https://uri.paypal.com/services/disputes/read-seller"})
        return routes(req)
    pp = PayPalClient("cid", "SECRET-CLIENT-SECRET", "https://api-m.sandbox.paypal.com",
                      transport=httpx.MockTransport(handler))
    client, _, wf = make_app(settings, mock=pp, disputes_sync_interval_s=0, disputes_refresh_interval_s=0, **kw)
    wf._paypal = pp
    return client, wf, calls


def boom_timeout(req):
    raise httpx.ReadTimeout("slow", request=req)


@pytest.mark.parametrize("route", [
    lambda r: httpx.Response(500, json={"name": "INTERNAL_SERVICE_ERROR", "message": "x"}),
    lambda r: httpx.Response(503, text="<html>down</html>"),
    lambda r: httpx.Response(429, json={"name": "RATE_LIMIT_REACHED", "message": "slow down"}),
    lambda r: httpx.Response(200, text="<html>not json</html>"),
    lambda r: httpx.Response(200, json=["a list"]),
    lambda r: httpx.Response(200, json={"items": "oops"}),
    lambda r: httpx.Response(200, json={"items": [None, 5, {"dispute_id": {"a": 1}}]}),
    boom_timeout,
], ids=["500", "503-html", "429", "200-nonjson", "200-list", "items-str", "items-junk", "timeout"])
def test_paypal_failures_never_500_never_leak_secrets(settings, route, caplog):
    caplog.set_level(logging.DEBUG)
    client, wf, _ = wired(settings, route)
    wf.db.upsert_dispute({"dispute_id": "D1", "case_id": None, "capture_id": None, "status": "OPEN",
                          "dispute_state": None, "life_cycle_stage": None, "reason": None, "amount": None,
                          "currency": None, "due_date": None, "create_time": None, "update_time": None,
                          "source": "webhook", "last_event_id": None})
    for r in (client.post("/disputes/sync"), client.post("/disputes/D1/refresh"), client.get("/disputes")):
        assert r.status_code < 500, r.text[:300]
        for secret in ("SECRET-TOKEN-123", "SECRET-CLIENT-SECRET", "Bearer"):
            assert secret not in r.text
    assert all(s not in caplog.text for s in ("SECRET-TOKEN-123", "SECRET-CLIENT-SECRET"))


def test_oauth_failure_page_view_is_cached_not_a_hammer(settings):
    hits = []

    def handler(req):
        hits.append(req.url.path)
        return httpx.Response(503, text="down")
    pp = PayPalClient("cid", "sec", "https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    client, _, wf = make_app(settings, mock=pp)
    wf._paypal = pp
    for _ in range(20):
        assert client.get("/disputes").status_code == 200
    assert len(hits) == 1, hits


def test_sync_and_refresh_are_throttled_app_wide(settings):
    client, wf, calls = wired(settings, lambda r: httpx.Response(200, json={"items": []}))
    client.app.state.workflow  # noqa: B018
    # same app but with the real default gates
    client2, _, wf2 = make_app(settings, mock=wf.paypal())
    wf2._paypal = wf.paypal()
    assert client2.post("/disputes/sync").status_code == 200
    for _ in range(5):
        r = client2.post("/disputes/sync")
        assert r.status_code == 429 and "moments ago" in r.text
    assert len([c for c in calls if c[1] == "/v1/customer/disputes"]) == 1


def test_csrf_cross_site_post_to_fetch_endpoints_refused(settings):
    client, wf, calls = wired(settings, lambda r: httpx.Response(200, json={"items": []}))
    for path in ("/disputes/sync", "/disputes/D1/refresh"):
        r = client.post(path, headers={"origin": "https://evil.example"})
        assert r.status_code == 403
    assert not [c for c in calls if "disputes" in c[1]]


def test_fetch_endpoints_use_get_only_toward_paypal(settings):
    client, wf, calls = wired(settings, lambda r: httpx.Response(200, json={"items": [{"dispute_id": "D9"}]}))
    client.post("/disputes/sync")
    assert {m for m, p in calls if "disputes" in p} == {"GET"}


def test_disputes_page_has_no_inline_styles_or_handlers(settings):
    """The app's CSP is style-src 'self': an inline style="" is silently dropped by browsers (layout bug)."""
    import re
    client, _, wf = make_app(settings)
    wf.disputes.ingest(dispute("PP-D-STYLE"), "webhook", "WH-STYLE")
    html = client.get("/disputes").text
    assert "PP-D-STYLE" in html
    assert not re.search(r"\sstyle\s*=|\son[a-z]+\s*=|<style|<script(?![^>]*src=)", html)


@pytest.mark.parametrize("value", ["NaN", "-1", "-0.01", "Infinity", "1e999", "9" * 30, "abc", "", "1,5"])
def test_unusable_amounts_are_stored_as_unknown_not_shown(ctx, value):
    from app.disputes import parse_dispute
    rec = parse_dispute(dispute("D-A", amount=value))
    assert rec["amount"] is None and rec["currency"] is None
    assert parse_dispute(dispute("D-B", amount="49.99"))["amount"] == "49.99"
