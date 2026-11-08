"""PayPal-Request-Id expiry rotation must stay ≤38 chars and unique across repeated windows."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.paypal_client import PAYPAL_REQUEST_ID_MAX_LEN, PayPalError, mint_retry_request_id
from app.paypal_mock import MockPayPalClient
from app.workflow import REFUND_COMPLETED, REFUND_ERROR
from tests.helpers import make_wf
from tests.test_mixed_orders import approve, only_batch, start


def test_mint_retry_request_id_stays_within_paypal_budget_and_chains():
    prior = "tos-mx-M-0EB7483A270E4EEB-30c1fcc5de"  # 36 chars — the Sandbox regression shape
    assert len(prior) == 36
    # Old append+truncate collapsed: f"{prior}-e{digest}"[:38] == prior + "-e"
    collapsed = f"{prior}-e{'deadbeef'}"[:PAYPAL_REQUEST_ID_MAX_LEN]
    assert collapsed == prior + "-e"
    assert f"{collapsed}-e{'cafebabe'}"[:PAYPAL_REQUEST_ID_MAX_LEN] == collapsed

    first = mint_retry_request_id(prior)
    second = mint_retry_request_id(first)
    third = mint_retry_request_id(second)
    assert len(first) <= PAYPAL_REQUEST_ID_MAX_LEN and first.startswith("tos-mx-")
    assert len(second) <= PAYPAL_REQUEST_ID_MAX_LEN and len(third) <= PAYPAL_REQUEST_ID_MAX_LEN
    assert len({prior, first, second, third}) == 4
    assert mint_retry_request_id(prior) == first  # deterministic / idempotent mint

    single = "tradeos-refund-A-0EB7483A270E4EEB"
    s1 = mint_retry_request_id(single)
    s2 = mint_retry_request_id(s1)
    assert len(s1) <= PAYPAL_REQUEST_ID_MAX_LEN and s1.startswith("tradeos-")
    assert s1 != single != s2 and s1 != s2


def test_mixed_error_repeated_expiry_rotations_yield_fresh_keys(settings):
    mock = MockPayPalClient()
    wf, pp, cid = start(settings, pp=MagicMock(wraps=mock, is_mock=True))
    batch = only_batch(wf, cid)
    mock.fail_refund = True
    with pytest.raises(PayPalError):
        approve(wf, cid, batch)
    first = only_batch(wf, cid)["request_id"]
    assert only_batch(wf, cid)["status"] == "ERROR" and len(first) <= PAYPAL_REQUEST_ID_MAX_LEN

    # DB timestamps use wall clock; _now is only the freshness comparator. Advance past the
    # original key, mint, then pull _now back inside the new key's wall-clock window to prove
    # idempotent reuse before a second expiry.
    t0 = datetime.now(timezone.utc)
    wf._now = lambda: (t0 + timedelta(hours=7)).isoformat()
    with pytest.raises(PayPalError):
        wf.mixed.retry_batch(cid, batch["id"])
    second = only_batch(wf, cid)["request_id"]
    assert only_batch(wf, cid)["status"] == "ERROR"
    assert second == mint_retry_request_id(first) and second != first
    assert len(second) <= PAYPAL_REQUEST_ID_MAX_LEN

    wf._now = lambda: (t0 + timedelta(hours=1)).isoformat()  # still <6h after mint wall time
    with pytest.raises(PayPalError):
        wf.mixed.retry_batch(cid, batch["id"])
    assert only_batch(wf, cid)["request_id"] == second

    mock.fail_refund = False
    wf._now = lambda: (t0 + timedelta(hours=7)).isoformat()  # minted key itself now past 6h
    wf.mixed.retry_batch(cid, batch["id"])
    third = only_batch(wf, cid)["request_id"]
    assert only_batch(wf, cid)["status"] == "COMPLETED"
    assert third == mint_retry_request_id(second) and third not in (first, second)
    assert len(third) <= PAYPAL_REQUEST_ID_MAX_LEN

    from app.workflow import RefundNotAllowed
    sent = [c.args[1] for c in pp.refund_capture.call_args_list]
    assert sent == [first, second, second, third]
    with pytest.raises(RefundNotAllowed):
        wf.mixed.retry_batch(cid, batch["id"])


def test_single_error_repeated_expiry_rotations_yield_fresh_keys(settings):
    mock = MockPayPalClient()
    pp = MagicMock(wraps=mock, is_mock=False)
    wf, _ = make_wf(settings, paypal=pp)
    case_id = wf.run_scenario("A")
    original = mock.refund_capture
    attempts = {"n": 0}

    def refuse_three(*args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] <= 3:
            raise PayPalError("definitely refused", status_code=422)
        return original(*args, **kwargs)

    pp.refund_capture.side_effect = refuse_three
    with pytest.raises(PayPalError):
        wf.approve(case_id)
    first = wf.db.get_case(case_id)["refund_request_id"]
    assert wf.db.get_case(case_id)["status"] == REFUND_ERROR
    assert first == f"tradeos-refund-{case_id}" and len(first) <= PAYPAL_REQUEST_ID_MAX_LEN

    t0 = datetime.now(timezone.utc)
    wf._now = lambda: (t0 + timedelta(hours=7)).isoformat()
    with pytest.raises(PayPalError):
        wf.execute_refund(case_id)
    second = wf.db.get_case(case_id)["refund_request_id"]
    assert wf.db.get_case(case_id)["status"] == REFUND_ERROR
    assert second == mint_retry_request_id(first) and len(second) <= PAYPAL_REQUEST_ID_MAX_LEN

    wf._now = lambda: (t0 + timedelta(hours=1)).isoformat()
    with pytest.raises(PayPalError):
        wf.execute_refund(case_id)
    assert wf.db.get_case(case_id)["refund_request_id"] == second

    wf._now = lambda: (t0 + timedelta(hours=7)).isoformat()
    wf.execute_refund(case_id)
    third = wf.db.get_case(case_id)["refund_request_id"]
    assert wf.db.get_case(case_id)["status"] == REFUND_COMPLETED
    assert third == mint_retry_request_id(second) and third not in (first, second)
    assert len(third) <= PAYPAL_REQUEST_ID_MAX_LEN

    sent = [c.args[1] for c in pp.refund_capture.call_args_list]
    assert sent == [first, second, second, third]
