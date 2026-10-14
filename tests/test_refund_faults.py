"""Refund failure matrix — the scenarios the 2026-10-14 review asked for.

These are unit-level with a MagicMock-wrapped MockPayPalClient. They do not replace
live Sandbox verification; they pin the recovery, concurrency, and restart behaviour
that the review flagged as under-tested.
"""
import threading
from unittest.mock import MagicMock

import pytest

from app.paypal_client import PayPalError
from app.paypal_mock import MockPayPalClient
from app.workflow import REFUND_COMPLETED, REFUND_UNKNOWN, Workflow
from tests.helpers import FakeExtractor, make_wf


def _unknown_then_refunded(wf, case_id):
    """First refund call times out (UNKNOWN). Simulate that PayPal actually refunded
    (capture now REFUNDED) so recovery can re-send the same Request-Id."""
    pp = wf._paypal
    real = getattr(pp, "_mock_wraps", pp)
    orig = real.refund_capture

    def fail_once(*a, **k):
        fail_once.calls += 1
        if fail_once.calls == 1:
            raise PayPalError("timeout", status_code=408)
        return orig(*a, **k)
    fail_once.calls = 0
    real.refund_capture = fail_once
    if hasattr(pp, "refund_capture"):
        pp.refund_capture = fail_once

    with pytest.raises(PayPalError):
        wf.approve(case_id)
    assert wf.db.get_case(case_id)["status"] == REFUND_UNKNOWN

    # PayPal side: the timed-out call actually went through (capture now REFUNDED).
    # Do not pre-seed a refund with a mismatched note — the recovery re-sends the same
    # Request-Id and the mock's idempotent path requires an identical body.
    request_id = f"tradeos-refund-{case_id}"
    cap_id = wf.db.get_case(case_id)["capture_id"]
    real.captures[cap_id]["status"] = "REFUNDED"
    return request_id


def test_unknown_then_reconcile_recovers_same_request_id(settings):
    """API timed out (PayPal may have refunded) → reconcile sees REFUNDED → recovery
    re-sends the same PayPal-Request-Id once → records the refund, no second distinct refund."""
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    wf, _ = make_wf(settings, paypal=pp)
    case_id = wf.run_scenario("A")
    request_id = _unknown_then_refunded(wf, case_id)

    # Reconcile discovers the refund and recovers it.
    r = wf.reconcile(case_id)
    case = wf.db.get_case(case_id)
    assert case["status"] == REFUND_COMPLETED
    assert case["refund_id"]  # recovery recorded a refund id
    assert case["refund_request_id"] == request_id
    titles = [e["title"] for e in wf.db.timeline(case_id)]
    assert any("Recovered the refund" in t for t in titles)
    assert wf.db.verify_chain(case_id)["ok"]


def test_restart_with_unknown_does_not_create_second_refund(settings):
    """Service restarts while a refund is UNKNOWN. resume_unresolved_refunds recovers
    with the same Request-Id; it does not create a second refund."""
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    wf, _ = make_wf(settings, paypal=pp)
    case_id = wf.run_scenario("A")
    request_id = _unknown_then_refunded(wf, case_id)

    # Simulate restart: new Workflow on the same DB + PayPal client.
    from app.config import Settings as S
    from app.notes import TemplateNoteWriter
    wf2 = Workflow(wf.db, S(), FakeExtractor(), paypal=pp, note_writer=TemplateNoteWriter())
    n = wf2.resume_unresolved_refunds()
    assert n >= 1
    case = wf2.db.get_case(case_id)
    assert case["status"] == REFUND_COMPLETED
    assert case["refund_request_id"] == request_id
    # Only one refund recorded for this capture.
    real = getattr(pp, "_mock_wraps", pp)
    assert len([r for r in real.refunds_by_request.values() if r["_capture"] == case["capture_id"]]) == 1
    assert wf2.db.verify_chain(case_id)["ok"]


def test_concurrent_webhook_and_reconcile_end_consistent(settings):
    """Webhook and background reconcile both discover the refund is COMPLETED.
    The case ends in one consistent terminal state; the audit chain stays intact."""
    pp = MagicMock(wraps=MockPayPalClient(refund_status="PENDING"), is_mock=True)
    wf, _ = make_wf(settings, paypal=pp)
    case_id = wf.run_scenario("A")
    wf.approve(case_id)
    case = wf.db.get_case(case_id)
    assert case["status"] == "REFUND_PENDING"
    refund_id = case["refund_id"]

    # PayPal settles.
    pp.complete_refund(refund_id)

    barrier = threading.Barrier(2)
    results = []

    def do_reconcile():
        barrier.wait()
        results.append(wf.reconcile(case_id))

    def do_webhook():
        barrier.wait()
        event = {"id": "WH-CONCURRENT", "event_type": "PAYMENT.CAPTURE.REFUNDED",
                 "resource": {"id": refund_id, "status": "COMPLETED"}}
        results.append(wf.record_webhook(event, "SUCCESS", method="self"))

    t1 = threading.Thread(target=do_reconcile)
    t2 = threading.Thread(target=do_webhook)
    t1.start(); t2.start()
    t1.join(); t2.join()

    case = wf.db.get_case(case_id)
    assert case["status"] == REFUND_COMPLETED
    assert case["refund_status"] == "COMPLETED"
    assert wf.db.verify_chain(case_id)["ok"]
    # No second refund was created.
    assert pp.refund_capture.call_count == 1


def test_duplicate_webhook_ignored(settings):
    """Same verified webhook delivered twice: the second is logged as duplicate and
    does not change state or create another refund."""
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    wf, _ = make_wf(settings, paypal=pp)
    case_id = wf.run_scenario("A")
    wf.approve(case_id)
    case = wf.db.get_case(case_id)
    refund_id = case["refund_id"]

    event = {"id": "WH-DUP", "event_type": "PAYMENT.CAPTURE.REFUNDED",
             "resource": {"id": refund_id, "status": "COMPLETED"}}
    wf.record_webhook(event, "SUCCESS", method="self")
    before = wf.db.get_case(case_id)["status"]
    wf.record_webhook(event, "SUCCESS", method="self")  # duplicate
    after = wf.db.get_case(case_id)
    assert after["status"] == before == REFUND_COMPLETED
    outcomes = [e["outcome"] for e in wf.db.webhook_events(case_id)]
    assert "DUPLICATE_IGNORED" in outcomes
    assert pp.refund_capture.call_count == 1
    assert wf.db.verify_chain(case_id)["ok"]
