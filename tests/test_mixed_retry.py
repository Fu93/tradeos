"""A mixed order (some items returned, some exchanged) must stay mixed when its policy check is retried.

Found by a logic review: if PayPal could not be read during a mixed order's policy check, "Retry the policy check"
ran the single-item flow. With a refund reading of the message the whole order became ELIGIBLE, and Approve refunded
the full capture (191.21 USD), the item meant for exchange included. The retry now evaluates the order line by line,
and the whole-case approve and refund guards refuse any mixed order outright.
"""
from __future__ import annotations

import pytest

from app.paypal_client import PayPalError
from app.workflow import RefundNotAllowed
from tests.helpers import FakeExtractor, make_wf

REFUND_READING = {"intent": "REFUND_REQUEST", "reason": "WRONG_ITEM", "requested_action": "REFUND"}


def mixed_after_a_failed_capture_read(settings):
    wf, pp = make_wf(settings, extractor=FakeExtractor(core=REFUND_READING))
    real, calls = pp._mock_wraps, {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PayPalError("PayPal timed out", status_code=503)
        return real.get_capture(*args, **kwargs)
    pp.get_capture.side_effect = flaky
    case_id = wf.run_scenario("M")
    case = wf.db.get_case(case_id)
    assert case["status"] == "ERROR" and case["capture_id"] and not case["decision"]
    return wf, pp, case_id


def test_retrying_the_policy_check_keeps_a_mixed_order_mixed(settings):
    wf, pp, case_id = mixed_after_a_failed_capture_read(settings)
    wf.retry_policy_check(case_id)
    case = wf.db.get_case(case_id)
    assert case["decision"] == "MIXED" and case["status"].startswith("MIXED_")
    with pytest.raises(RefundNotAllowed, match="per batch"):
        wf.approve(case_id)
    assert pp.refund_capture.call_count == 0


def test_the_whole_case_refund_guard_refuses_a_mixed_order_whatever_its_decision(settings):
    """Defence in depth: even if a mixed order's row and chain said ELIGIBLE + APPROVED, the whole-capture refund
    path refuses it. Mixed orders are refunded only through their batches."""
    wf, pp, case_id = mixed_after_a_failed_capture_read(settings)
    wf.db.update_case(case_id, decision="ELIGIBLE", human_decision="APPROVED", approval_source="human",
                      status="PENDING_APPROVAL")
    with pytest.raises(RefundNotAllowed, match="mixed order"):
        wf.execute_refund(case_id)
    with pytest.raises(RefundNotAllowed, match="mixed order"):
        wf.approve(case_id)
    assert pp.refund_capture.call_count == 0


def test_a_whole_case_approve_of_a_mixed_order_records_no_approval(settings):
    """Refused before anything is written: no APPROVED entry lands on a mixed order's chain from the whole-case
    path, so the record never says a person approved something that could not be paid."""
    wf, pp, case_id = mixed_after_a_failed_capture_read(settings)
    wf.db.update_case(case_id, decision="ELIGIBLE", status="PENDING_APPROVAL")
    with pytest.raises(RefundNotAllowed, match="per batch"):
        wf.approve(case_id)
    case = wf.db.get_case(case_id)
    assert case["human_decision"] is None and case["status"] == "PENDING_APPROVAL"
    assert pp.refund_capture.call_count == 0
