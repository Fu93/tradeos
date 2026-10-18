"""PayPal Disputes — READ-ONLY. PayPal HTTP is mocked (httpx.MockTransport / MockPayPalClient); nothing here
proves behaviour against live PayPal (see docs/disputes-readonly.md for the evidence tiers)."""
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from app.paypal_client import DISPUTES_READ_SCOPE, PayPalClient, PayPalError, is_scope_error
from app.paypal_mock import MockPayPalClient
from app.policy import DISPUTE_RECOMMENDATION_LABEL, DisputeFacts, recommend_dispute
from tests.helpers import SIG_BAD, SIG_OK, case_from, make_app, run_a

SIGHDR = {"paypal-transmission-id": "t", "paypal-transmission-time": "2026-10-18T00:00:00Z",
          "paypal-transmission-sig": "valid-mock-signature", "paypal-cert-url": "x", "paypal-auth-algo": "x"}


def dispute(did="PP-D-1", capture="CAP", status="UNDER_REVIEW", update="2026-10-18T10:00:00.000Z", amount="49.99",
            due="2026-10-30T10:00:00.000Z", reason="MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED"):
    return {"dispute_id": did, "create_time": "2026-10-18T09:00:00.000Z", "update_time": update, "status": status,
            "reason": reason, "dispute_state": "OPEN_INQUIRIES", "dispute_life_cycle_stage": "INQUIRY",
            "dispute_amount": {"currency_code": "USD", "value": amount}, "seller_response_due_date": due,
            "disputed_transactions": [{"seller_transaction_id": capture, "buyer_transaction_id": "B1"}]}


def event(res, etype="CUSTOMER.DISPUTE.CREATED", eid="WH-D-1"):
    return {"id": eid, "event_type": etype, "resource": res}


def post(client, ev, headers=SIG_OK):
    return client.post("/webhooks/paypal", content=json.dumps(ev), headers=headers)


@pytest.fixture
def ctx(settings):
    client, pp, wf = make_app(settings)
    case_id = run_a(client)
    return client, pp, wf, case_id, wf.db.get_case(case_id)["capture_id"]


def refund_calls(pp):
    return pp.refund_capture.call_count


def test_signed_created_event_is_stored_linked_and_chained(ctx):
    client, pp, wf, case_id, cap = ctx
    before, status = refund_calls(pp), wf.db.get_case(case_id)["status"]
    r = post(client, event(dispute(capture=cap)))
    assert r.status_code == 200 and r.json()["case"] == case_id and r.json()["verified"] is True
    d = wf.db.get_dispute("PP-D-1")
    assert d["case_id"] == case_id and d["capture_id"] == cap and d["source"] == "webhook"
    assert d["reason"] == "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED" and d["amount"] == "49.99"
    assert any(e["stage"] == "dispute" for e in wf.db.timeline(case_id))
    assert wf.db.verify_chain(case_id)["ok"] is True
    # read-only: no state change, no money call
    assert wf.db.get_case(case_id)["status"] == status and refund_calls(pp) == before


def test_duplicate_delivery_is_a_noop(ctx):
    client, _pp, wf, case_id, cap = ctx
    ev = event(dispute(capture=cap))
    post(client, ev)
    n = len(wf.db.timeline(case_id))
    again = post(client, ev)
    assert again.status_code == 200
    assert len(wf.db.list_disputes()) == 1 and len(wf.db.timeline(case_id)) == n + 1  # one 'duplicate ignored' note
    outcomes = [w["outcome"] for w in wf.db.webhook_events(case_id) if w["event_type"].startswith("CUSTOMER.DISPUTE")]
    assert "DUPLICATE_IGNORED" in outcomes and wf.db.verify_chain(case_id)["ok"]


def test_unsigned_event_is_ignored_and_stores_nothing(ctx):
    client, _pp, wf, case_id, cap = ctx
    r = post(client, event(dispute(capture=cap)), headers=SIG_BAD)
    assert r.json()["verified"] is False
    assert wf.db.list_disputes() == []
    assert [w["outcome"] for w in wf.db.webhook_events(case_id)][-1] == "UNVERIFIED_IGNORED"
    # an unverified event does not burn the event id: the real one still lands
    post(client, event(dispute(capture=cap)))
    assert len(wf.db.list_disputes()) == 1


def test_missing_signature_headers_rejected_outside_mock(settings):
    client, _pp, wf = make_app(settings)
    wf._paypal = MagicMock(wraps=MockPayPalClient(), is_mock=False)  # behave like a real (sandbox) client
    r = post(client, event(dispute()), headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and wf.db.list_disputes() == []


def test_future_dated_or_replayed_old_event_rejected(ctx):
    client, _pp, wf, case_id, cap = ctx
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    post(client, event(dispute(capture=cap)), headers={**SIG_OK, "paypal-transmission-time": future})
    assert wf.db.list_disputes() == []
    old = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    post(client, event(dispute(capture=cap)))  # fresh/unknown time: accepted, event id claimed
    assert len(wf.db.list_disputes()) == 1
    post(client, event(dispute(capture=cap, status="RESOLVED", update="2026-10-19T00:00:00.000Z")),
         headers={**SIG_OK, "paypal-transmission-time": old})  # same event id, old time: replay
    assert wf.db.get_dispute("PP-D-1")["status"] == "UNDER_REVIEW"


def test_updates_apply_in_order_and_old_update_cannot_move_it_back(ctx):
    client, _pp, wf, _c, cap = ctx
    post(client, event(dispute(capture=cap)))
    post(client, event(dispute(capture=cap, status="RESOLVED", update="2026-10-18T12:00:00.000Z"),
                       "CUSTOMER.DISPUTE.RESOLVED", "WH-D-2"))
    assert wf.db.get_dispute("PP-D-1")["status"] == "RESOLVED"
    post(client, event(dispute(capture=cap, status="OPEN", update="2026-10-18T11:00:00.000Z"),
                       "CUSTOMER.DISPUTE.UPDATED", "WH-D-3"))
    assert wf.db.get_dispute("PP-D-1")["status"] == "RESOLVED"


def test_unmatched_dispute_is_stored_without_a_case(ctx):
    client, _pp, wf, _c, _cap = ctx
    r = post(client, event(dispute(capture="NOPE-123")))
    assert r.json()["case"] is None
    d = wf.db.get_dispute("PP-D-1")
    assert d["case_id"] is None
    assert wf.disputes.view()[0]["recommendation"]["code"] == "REVIEW_MANUALLY"


def test_non_dispute_payload_and_garbage_are_harmless(ctx):
    client, *_ = ctx
    assert post(client, event({"id": "x"})).status_code == 200
    assert post(client, event("not-a-dict")).status_code == 200
    assert client.get("/disputes").status_code == 200


# ---- recommendation (policy engine, pure) ------------------------------------------------------
def facts(**kw):
    base = dict(status="UNDER_REVIEW", reason="MERCHANDISE_OR_SERVICE_NOT_RECEIVED", amount=Decimal("49.99"),
                currency="USD", due=date(2026, 10, 30), today=date(2026, 10, 18), case_matched=True)
    return DisputeFacts(**{**base, **kw})


def test_recommendation_rules():
    assert recommend_dispute(facts(status="RESOLVED")).code == "CLOSED"
    assert recommend_dispute(facts(case_matched=False)).code == "REVIEW_MANUALLY"
    dr = recommend_dispute(facts(case_refund_status="COMPLETED"))
    assert dr.code == "REVIEW_POSSIBLE_DOUBLE_RECOVERY"
    assert recommend_dispute(facts(case_decision="REJECTED")).code == "CONTEST_CANDIDATE"
    g = recommend_dispute(facts(case_decision="ELIGIBLE"))
    assert g.code == "GATHER_EVIDENCE" and "tracking" in g.summary
    assert g.label == DISPUTE_RECOMMENDATION_LABEL and "no action is taken" in g.label
    assert recommend_dispute(facts(due=date(2026, 10, 1))).urgency == "overdue"
    assert recommend_dispute(facts(due=date(2026, 10, 20))).urgency == "soon"
    assert recommend_dispute(facts()).urgency == "none"
    over = recommend_dispute(facts(case_refund_status="PENDING", amount=Decimal("99"), case_amount=Decimal("49.99")))
    assert any("larger" in r for r in over.reasons)


def test_refunded_case_gets_double_recovery_recommendation_in_ui(ctx):
    client, _pp, wf, _c, cap = ctx
    post(client, event(dispute(capture=cap)))
    row = wf.disputes.view()[0]
    assert row["recommendation"]["code"] == "REVIEW_POSSIBLE_DOUBLE_RECOVERY"  # Case A was refunded
    html = client.get("/disputes").text
    assert "PP-D-1" in html and "49.99 USD" in html and "2026-10-30" in html
    assert "no action is taken" in html and "evidence submission not implemented" in html
    assert "READ-ONLY" in html


def test_rejected_case_is_contest_candidate(settings):
    client, _pp, wf = make_app(settings)
    b = case_from(client.post("/demo/run/B", follow_redirects=False))
    cap = wf.db.get_case(b)["capture_id"]
    post(client, event(dispute(capture=cap)))
    assert wf.disputes.view()[0]["recommendation"]["code"] == "CONTEST_CANDIDATE"


# ---- GET fetch / scope degradation ---------------------------------------------------------------
def test_fetch_stores_dispute_via_get_and_logs_call_on_case(ctx):
    _client, pp, wf, case_id, cap = ctx
    pp._mock_wraps.disputes["PP-D-9"] = dispute("PP-D-9", cap)
    res = wf.disputes.fetch("PP-D-9")
    assert res["ok"] and res["case_id"] == case_id
    assert wf.db.get_dispute("PP-D-9")["source"] == "paypal_get"
    assert [c["operation"] for c in wf.db.paypal_calls(case_id) if c["operation"] == "get_dispute"] == ["get_dispute"]
    assert wf.db.verify_chain(case_id)["ok"]


def test_missing_scope_degrades_with_clear_message_no_crash(ctx):
    client, pp, wf, _c, _cap = ctx
    pp._mock_wraps.disputes_scope = False
    r = client.post("/disputes/sync", follow_redirects=False)
    assert r.status_code == 409 and "cannot read disputes" in r.text and DISPUTES_READ_SCOPE in r.text
    page = client.get("/disputes")
    assert page.status_code == 200 and "Disputes read access is not enabled" in page.text
    # a webhook-stored dispute still shows, and its refresh degrades the same way
    post(client, event(dispute()))
    r = client.post("/disputes/PP-D-1/refresh")
    assert r.status_code == 409 and "cannot read disputes" in r.text
    assert wf.disputes.fetch("PP-D-1")["code"] == "SCOPE_MISSING"
    assert client.post("/disputes/NOPE/refresh").status_code == 404


def test_sync_lists_then_gets_each(ctx):
    client, pp, wf, case_id, cap = ctx
    pp._mock_wraps.disputes.update({"PP-D-1": dispute("PP-D-1", cap), "PP-D-2": dispute("PP-D-2", "X")})
    r = client.post("/disputes/sync")
    assert r.status_code == 200 and "stored 2" in r.text
    assert {d["dispute_id"] for d in wf.db.list_disputes()} == {"PP-D-1", "PP-D-2"}
    pp._mock_wraps.disputes.clear()
    assert "no disputes" in client.post("/disputes/sync").text


def test_non_scope_paypal_error_is_reported_not_raised(ctx):
    _client, pp, wf, *_ = ctx
    res = wf.disputes.fetch("DOES-NOT-EXIST")
    assert res["ok"] is False and res["code"] == "PAYPAL_ERROR"


def test_reset_demo_still_works_with_disputes(ctx):
    client, _pp, wf, _c, cap = ctx
    post(client, event(dispute(capture=cap)))
    assert client.post("/demo/reset", follow_redirects=False).status_code == 303
    assert wf.db.get_dispute("PP-D-1") is not None  # informational mirror is kept, like the audit chain
    assert client.get("/disputes").status_code == 200


# ---- the HTTP client: GET only ---------------------------------------------------------------------
def real_client(routes, scope=DISPUTES_READ_SCOPE):
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.method, req.url.raw_path.decode("ascii").split("?")[0], str(req.url.query, "ascii")))
        if req.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3000, "scope": f"openid {scope}"})
        return routes(req)
    return PayPalClient("id", "secret", "https://api-m.sandbox.paypal.com",
                        transport=httpx.MockTransport(handler)), seen


def test_client_uses_get_only_and_encodes_id():
    pp, seen = real_client(lambda r: httpx.Response(200, json={"dispute_id": "PP-D-1", "items": []}))
    pp.list_disputes(page_size=500)
    pp.get_dispute("PP-D-1/../x")
    calls = [c for c in seen if "disputes" in c[1]]
    assert all(m == "GET" for m, _p, _q in calls) and len(calls) == 2
    assert calls[0][2] == "page_size=50"
    assert "/../" not in calls[1][1] and "%2F" in calls[1][1]
    assert pp.has_scope(DISPUTES_READ_SCOPE) is True


def test_client_reports_missing_scope_and_403_is_scope_error():
    pp, _ = real_client(lambda r: httpx.Response(403, json={"name": "NOT_AUTHORIZED", "message": "no"}),
                        scope="https://uri.paypal.com/services/payments/refund")
    assert pp.has_scope(DISPUTES_READ_SCOPE) is False
    with pytest.raises(PayPalError) as e:
        pp.list_disputes()
    assert is_scope_error(e.value)
    assert not is_scope_error(PayPalError("boom", 500, "INTERNAL_SERVICE_ERROR"))


def test_no_disputes_write_endpoint_exists_in_code():
    """Static guard: nothing in the app may call a Disputes write endpoint."""
    root = Path(__file__).resolve().parents[1] / "app"
    src = "\n".join(p.read_text() for p in root.glob("*.py"))
    for forbidden in ("provide-evidence", "accept-claim", "/appeal", "make-offer", "send-message", "adjudicate",
                      "require-evidence", "acknowledge-return-item", "/escalate", "provide-supporting-info"):
        assert forbidden not in src, forbidden
    assert '"POST", f"/v1/customer' not in src and '"PATCH", f"/v1/customer' not in src


# ---- through the REAL self-verification path (RSA / CRC32; test certificate, not PayPal's) -----------
def test_dispute_webhook_through_self_verify_accepts_valid_and_rejects_tampered(ctx, monkeypatch):
    from app import webhook_verify as wv
    from tests.test_hardening import PEM, signed_headers
    client, _pp, wf, case_id, cap = ctx
    wv.clear_cache()
    monkeypatch.setattr(wv, "_http_fetch", lambda url, timeout: PEM)
    raw = json.dumps(event(dispute(capture=cap))).encode()
    h = {**signed_headers(raw), "Content-Type": "application/json"}
    bad = client.post("/webhooks/paypal", content=raw + b" ", headers=h)  # body altered after signing
    assert bad.json()["verified"] is False and wf.db.list_disputes() == []
    ok = client.post("/webhooks/paypal", content=raw, headers=h)
    assert ok.json() == {"ok": True, "handled": True, "verified": True, "case": case_id, "method": "self"}
    assert wf.db.get_dispute("PP-D-1")["case_id"] == case_id
    wv.clear_cache()
