"""Item 3 (feat/paypal-reconcile): reconciliation against PayPal (GET capture + GET refund)."""
import json
from unittest.mock import MagicMock

from app.paypal_client import PayPalError
from app.paypal_mock import MockPayPalClient
from app.views import evidence_view
from tests.test_upgrade import app_ctx, case_from, make_wf  # noqa: F401


def approved_a(settings, **mock_kw):
    pp = MagicMock(wraps=MockPayPalClient(**mock_kw), is_mock=True)
    wf, _ = make_wf(settings, paypal=pp)
    case_id = wf.run_scenario("A")
    wf.approve(case_id)
    return wf, pp, case_id


def last_reconcile(wf, case_id):
    return [e for e in wf.db.timeline(case_id) if e["stage"] == "reconcile"][-1]


def test_all_match_after_case_a(settings):
    wf, pp, case_id = approved_a(settings)
    calls = pp.refund_capture.call_count
    r = wf.reconcile(case_id)
    assert r["ok"] and not r["advanced"]
    assert pp.refund_capture.call_count == calls == 1  # reconciliation never refunds
    assert last_reconcile(wf, case_id)["title"] == "Reconciled with PayPal — all match"


def test_pending_advances_to_completed_from_paypal_get(settings):
    wf, pp, case_id = approved_a(settings, refund_status="PENDING")
    assert wf.db.get_case(case_id)["status"] == "REFUND_PENDING"
    r = wf.reconcile(case_id)  # mock GET refund reports COMPLETED
    case = wf.db.get_case(case_id)
    assert r["advanced"] and case["status"] == "REFUND_COMPLETED" and case["refund_status"] == "COMPLETED"
    assert case["note"]["outcome"] == "COMPLETED_NOTE"
    assert pp.refund_capture.call_count == 1


def test_pending_stays_pending_when_paypal_still_pending(settings):
    wf, pp, case_id = approved_a(settings, refund_status="PENDING")
    pp.get_refund.side_effect = lambda rid: {"id": rid, "status": "PENDING", "status_details": {"reason": "ECHECK"}}
    r = wf.reconcile(case_id)
    assert r["ok"] and wf.db.get_case(case_id)["status"] == "REFUND_PENDING"


def test_mismatch_is_flagged_never_downgrades(settings):
    wf, pp, case_id = approved_a(settings)
    pp.get_refund.side_effect = lambda rid: {"id": rid, "status": "PENDING", "amount": {"value": "49.99"}}
    r = wf.reconcile(case_id)
    case = wf.db.get_case(case_id)
    assert not r["ok"] and case["status"] == "REFUND_COMPLETED" and case["refund_status"] == "COMPLETED"
    row = [x for x in evidence_view(wf.db, case_id) if x["source"] == "reconcile"][-1]
    assert not row["ok"] and "refund.status: local COMPLETED vs PayPal PENDING" in row["status"]
    assert "MISMATCH" in row["what"]


def test_capture_mismatch_flagged(settings):
    wf, pp, case_id = approved_a(settings)
    pp.get_capture.side_effect = lambda cid: {"id": cid, "status": "COMPLETED", "amount": {"value": "49.99"}}
    assert not wf.reconcile(case_id)["ok"]


def test_paypal_down_is_safe(settings):
    wf, pp, case_id = approved_a(settings, refund_status="PENDING")
    pp.get_capture.side_effect = PayPalError("Could not reach PayPal: ConnectError")
    before = wf.db.get_case(case_id)
    r = wf.reconcile(case_id)
    after = wf.db.get_case(case_id)
    assert r["ok"] is False and after["status"] == before["status"] == "REFUND_PENDING"
    assert "PayPal unreachable" in last_reconcile(wf, case_id)["title"]
    wf._reconciled.clear()
    assert wf.auto_reconcile(case_id, background=False)  # view-trigger path also swallows it


def test_already_refunded_capture_blocks_new_refund(settings):
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    wf, _ = make_wf(settings, paypal=pp)
    real = pp._mock_wraps.get_capture
    pp.get_capture.side_effect = lambda cid: {**real(cid), "status": "REFUNDED"}
    case_id = wf.run_scenario("A")
    case = wf.db.get_case(case_id)
    assert case["status"] == "REJECTED"
    last = [e for e in wf.db.timeline(case_id) if e["stage"] == "policy"][-1]
    checks = {c["name"]: c for c in last["detail"]["checks"]}
    assert checks["refundable_amount"]["passed"] is False and "refundable 0.00" in checks["refundable_amount"]["detail"]
    pp.refund_capture.assert_not_called()


def test_partially_refunded_without_known_refund_fails_closed(settings):
    wf, _ = make_wf(settings)
    amt = wf._already_refunded({}, {"status": "PARTIALLY_REFUNDED", "amount": {"value": "49.99"}})
    assert str(amt) == "49.99"
    known = {"refund": {"seller_payable_breakdown": {"total_refunded_amount": {"value": "10.00"}}}}
    assert str(wf._already_refunded(known, {"status": "PARTIALLY_REFUNDED", "amount": {"value": "49.99"}})) == "10.00"
    assert str(wf._already_refunded({}, {"status": "COMPLETED", "amount": {"value": "49.99"}})) == "0"


def test_view_trigger_is_bounded(app_ctx):
    client, pp, wf = app_ctx
    case_id = case_from(client.post("/demo/run/A", follow_redirects=False))
    client.post(f"/cases/{case_id}/approve", follow_redirects=False)
    for _ in range(5):
        client.get(f"/?case={case_id}")
    assert pp.get_refund.call_count == 1  # once per case for a final state
    assert pp.refund_capture.call_count == 1
    html = client.get(f"/?case={case_id}").text
    assert "TradeOS reconciled" in html and "Reconcile with PayPal" in html


def test_case_b_unaffected_no_reconcile_without_refund(app_ctx):
    client, pp, wf = app_ctx
    case_id = case_from(client.post("/demo/run/B", follow_redirects=False))
    client.get(f"/?case={case_id}")
    pp.get_refund.assert_not_called()
    assert client.post(f"/cases/{case_id}/approve", follow_redirects=False).status_code == 409
    pp.refund_capture.assert_not_called()
