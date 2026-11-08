"""Confirm-by-GET state machine: every PayPal refund status is explicit and tested."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.paypal_client import PAYPAL_REQUEST_ID_MAX_LEN, PayPalError, mint_retry_request_id, refund_lookup_issue
from app.paypal_mock import MockPayPalClient
from app.workflow import REFUND_COMPLETED, REFUND_FAILED, REFUND_PENDING, REFUND_UNKNOWN, RefundNotAllowed
from tests.helpers import make_wf
from tests.test_refund_lookup import lost_reply_case


@pytest.mark.parametrize("status, case_status", [
    ("COMPLETED", REFUND_COMPLETED),
    ("PENDING", REFUND_PENDING),
    ("FAILED", REFUND_FAILED),
])
def test_confirm_binds_completed_pending_or_failed(settings, status, case_status):
    wf, pp, cid, _, rid, proof = lost_reply_case(settings)
    proof = {**proof, "status": status}
    pp.get_refund.side_effect = lambda *_a, **_kw: proof
    wf.confirm_unknown_refund(cid, rid)
    case = wf.db.get_case(cid)
    assert case["status"] == case_status and case["refund_id"] == rid
    assert case["refund_status"] == status
    assert pp.refund_capture.call_count == 1
    assert wf.db.verify_chain(cid)["ok"]


@pytest.mark.parametrize("status, error", [
    ("CANCELLED", "CANCELLED"),
    ("REFUNDED", "no recognized refund status"),  # not a refund-resource status
    (None, "no recognized refund status"),
])
def test_confirm_rejects_cancelled_and_unknown_statuses(settings, status, error):
    wf, pp, cid, _, rid, proof = lost_reply_case(settings)
    proof = {**proof, "status": status}
    pp.get_refund.side_effect = lambda *_a, **_kw: proof
    with pytest.raises(RefundNotAllowed, match=error):
        wf.confirm_unknown_refund(cid, rid)
    assert wf.db.get_case(cid)["status"] == REFUND_UNKNOWN
    assert pp.refund_capture.call_count == 1


def test_confirm_failed_unlocks_retry_with_new_request_id(settings):
    """UNKNOWN from a request that never reached PayPal, then GET proves FAILED → new request id."""
    mock = MockPayPalClient()
    pp = MagicMock(wraps=mock, is_mock=False)
    wf, _ = make_wf(settings, paypal=pp)
    cid = wf.run_scenario("A")
    pp.refund_capture.side_effect = PayPalError("timeout before send", status_code=408, sent=True)
    with pytest.raises(PayPalError):
        wf.approve(cid)
    assert wf.db.get_case(cid)["status"] == REFUND_UNKNOWN and not mock.refunds_by_request
    case = wf.db.get_case(cid)
    rid = "PAYPAL-FAILED-REFUND-1"
    proof = {
        "id": rid, "status": "FAILED", "custom_id": cid,
        "amount": {"currency_code": case["currency"], "value": case["amount"]},
        "links": [{"rel": "up",
                   "href": f"https://api-m.sandbox.paypal.com/v2/payments/captures/{case['capture_id']}"}],
    }
    pp.get_refund.side_effect = lambda *_a, **_kw: proof
    wf.confirm_unknown_refund(cid, rid)
    assert wf.db.get_case(cid)["status"] == REFUND_FAILED
    pp.refund_capture.side_effect = None
    prior_req = case["refund_request_id"] or f"tradeos-refund-{cid}"
    wf.retry_failed_refund(cid)
    case = wf.db.get_case(cid)
    expected = mint_retry_request_id(f"{prior_req}|failed|{rid}")
    assert case["status"] == REFUND_COMPLETED
    assert case["refund_request_id"] == expected and len(expected) <= PAYPAL_REQUEST_ID_MAX_LEN
    assert pp.refund_capture.call_count == 2


def test_lookup_helper_status_matrix():
    base = {
        "id": "RF-1",
        "status": "COMPLETED",
        "custom_id": "A-1",
        "amount": {"currency_code": "USD", "value": "10.00"},
        "links": [{"rel": "up", "href": "https://api-m.sandbox.paypal.com/v2/payments/captures/CAP-1"}],
    }
    assert refund_lookup_issue(base, "RF-1", "CAP-1", "A-1", "10.00", "USD") is None
    assert "CANCELLED" in (refund_lookup_issue({**base, "status": "CANCELLED"}, "RF-1", "CAP-1", "A-1",
                                               "10.00", "USD") or "")
    assert "no recognized refund status" in (refund_lookup_issue({**base, "status": "OTHER"}, "RF-1", "CAP-1",
                                                                 "A-1", "10.00", "USD") or "")


def test_refund_error_reuses_request_id_inside_six_hour_window(settings):
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=False)
    wf, _ = make_wf(settings, paypal=pp)
    case_id = wf.run_scenario("A")
    original = pp._mock_wraps.refund_capture
    attempts = {"n": 0}

    def refused_once(*args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise PayPalError("definitely refused", status_code=422)
        return original(*args, **kwargs)

    pp.refund_capture.side_effect = refused_once
    with pytest.raises(PayPalError):
        wf.approve(case_id)
    prior = wf.db.get_case(case_id)["refund_request_id"]
    wf.execute_refund(case_id)
    case = wf.db.get_case(case_id)
    assert case["status"] == REFUND_COMPLETED
    assert case["refund_request_id"] == prior == f"tradeos-refund-{case_id}"
    assert {c.args[1] for c in pp.refund_capture.call_args_list} == {prior}


def test_refund_error_mints_new_request_id_after_six_hour_window(settings):
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=False)
    wf, _ = make_wf(settings, paypal=pp)
    case_id = wf.run_scenario("A")
    original = pp._mock_wraps.refund_capture
    attempts = {"n": 0}

    def refused_once(*args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise PayPalError("definitely refused", status_code=422)
        return original(*args, **kwargs)

    pp.refund_capture.side_effect = refused_once
    with pytest.raises(PayPalError):
        wf.approve(case_id)
    prior = wf.db.get_case(case_id)["refund_request_id"]
    wf._now = lambda: (datetime.now(timezone.utc) + timedelta(hours=7)).isoformat()
    wf.execute_refund(case_id)
    case = wf.db.get_case(case_id)
    assert case["status"] == REFUND_COMPLETED
    assert case["refund_request_id"] == mint_retry_request_id(prior)
    assert len(case["refund_request_id"]) <= PAYPAL_REQUEST_ID_MAX_LEN
    assert {c.args[1] for c in pp.refund_capture.call_args_list} == {prior, case["refund_request_id"]}
    assert any("new PayPal-Request-Id" in e["title"] for e in wf.db.timeline(case_id))
