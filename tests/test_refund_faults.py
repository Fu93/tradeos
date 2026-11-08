"""Refund failure matrix — the scenarios the 2026-10-14 review asked for.

These are unit-level with a MagicMock-wrapped MockPayPalClient. They do not replace
live Sandbox verification; they pin the recovery, concurrency, and restart behaviour
that the review flagged as under-tested.
"""
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.paypal_client import PayPalError
from app.paypal_mock import MockPayPalClient
from app.workflow import REFUND_COMPLETED, REFUND_UNKNOWN, RefundNotAllowed, Workflow
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
    wf.reconcile(case_id)
    case = wf.db.get_case(case_id)
    assert case["status"] == REFUND_COMPLETED
    assert case["refund_id"]  # recovery recorded a refund id
    assert case["refund_request_id"] == request_id
    titles = [e["title"] for e in wf.db.timeline(case_id)]
    assert any("Recovered the refund" in t for t in titles)
    assert wf.db.verify_chain(case_id)["ok"]


def test_real_sandbox_unknown_refund_is_never_replayed(settings):
    """A lost reply after PayPal moves money must not trigger a second real Refund API call."""
    mock = MockPayPalClient()
    pp = MagicMock(wraps=mock, is_mock=False)
    wf, _ = make_wf(settings, paypal=pp)
    case_id = wf.run_scenario("A")
    original = mock.refund_capture

    def lost_reply(*args, **kwargs):
        original(*args, **kwargs)
        raise PayPalError("timeout after refund", status_code=408)

    pp.refund_capture.side_effect = lost_reply
    with pytest.raises(PayPalError):
        wf.approve(case_id)
    assert wf.db.get_case(case_id)["status"] == REFUND_UNKNOWN
    assert len(mock.refunds_by_request) == 1
    wf.reconcile(case_id)
    assert pp.refund_capture.call_count == 1
    with pytest.raises(RefundNotAllowed, match="does not document"):
        wf.execute_refund(case_id)
    # A migrated/incomplete UNKNOWN row must also fail closed if its request ID is missing.
    wf.db.update_case(case_id, refund_request_id=None)
    with pytest.raises(RefundNotAllowed, match="does not document"):
        wf.execute_refund(case_id)
    assert pp.refund_capture.call_count == 1
    assert wf.db.verify_chain(case_id)["ok"]


def test_real_sandbox_definite_refusal_can_be_retried(settings):
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=False)
    wf, _ = make_wf(settings, paypal=pp)
    case_id = wf.run_scenario("A")
    original = pp._mock_wraps.refund_capture
    attempts = 0

    def refused_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PayPalError("definitely refused", status_code=422)
        return original(*args, **kwargs)

    pp.refund_capture.side_effect = refused_once
    with pytest.raises(PayPalError):
        wf.approve(case_id)
    assert wf.db.get_case(case_id)["status"] == "REFUND_ERROR"
    wf.execute_refund(case_id)
    assert wf.db.get_case(case_id)["status"] == REFUND_COMPLETED
    assert pp.refund_capture.call_count == 2


def test_real_sandbox_double_click_stops_before_second_refund_call(settings):
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=False)
    wf, _ = make_wf(settings, paypal=pp)
    case_id = wf.run_scenario("D")
    wf.approve_twice(case_id)
    evidence = wf.db.get_case(case_id)["duplicate"]
    assert evidence["refund_api_calls"] == 1
    assert evidence["replayed_refund_id"] is None
    assert pp.refund_capture.call_count == 1
    assert wf.db.verify_chain(case_id)["ok"]


@pytest.mark.parametrize("patch, issue", [
    ({"id": None}, "no refund ID"),
    ({"status": None}, "no recognized refund status"),
    ({"links": [{"rel": "up", "href": "https://api-m.sandbox.paypal.com/v2/payments/captures/OTHER"}]},
     "another capture"),
    ({"links": ["invalid"]}, "malformed refund links"),
])
def test_unverifiable_refund_reply_stays_unknown(settings, patch, issue):
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    wf, _ = make_wf(settings, paypal=pp)
    case_id = wf.run_scenario("A")
    real_refund = pp._mock_wraps.refund_capture
    pp.refund_capture.side_effect = lambda *a, **kw: {**real_refund(*a, **kw), **patch}

    wf.approve(case_id)
    case = wf.db.get_case(case_id)
    assert case["status"] == REFUND_UNKNOWN and case["refund_id"] is None
    assert issue in case["error"]
    assert len(pp._mock_wraps.refunds_by_request) == 1
    assert wf.db.verify_chain(case_id)["ok"]


@pytest.mark.parametrize("entry_point", ["reconcile", "background_check"])
def test_unknown_refund_never_recovers_from_a_different_capture(settings, entry_point):
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    wf, _ = make_wf(settings, paypal=pp)
    case_id = wf.run_scenario("A")
    _unknown_then_refunded(wf, case_id)
    original = pp._mock_wraps.get_capture
    pp.get_capture.side_effect = lambda cid, timeout=None: {**original(cid), "id": "OTHER-CAPTURE"}

    if entry_point == "reconcile":
        assert not wf.reconcile(case_id)["ok"]
    else:
        wf._refund_check(case_id)

    assert wf.db.get_case(case_id)["status"] == REFUND_UNKNOWN
    assert not pp._mock_wraps.refunds_by_request
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


@pytest.mark.parametrize("expired", [False, True])
def test_crash_after_paypal_refund_before_call_log_is_reconciled_or_blocked(settings, expired):
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    wf, _ = make_wf(settings, paypal=pp)
    case_id = wf.run_scenario("A")
    real_refund = pp._mock_wraps.refund_capture

    def crash_after_money(*args, **kwargs):
        real_refund(*args, **kwargs)
        raise SystemExit("process died before recording PayPal's reply")

    pp.refund_capture.side_effect = crash_after_money
    with pytest.raises(SystemExit):
        wf.approve(case_id)
    case = wf.db.get_case(case_id)
    assert case["status"] == REFUND_UNKNOWN and case["refund_request_id"]
    assert wf.db.paypal_calls(case_id, "refund_capture") == []
    assert len(pp._mock_wraps.refunds_by_request) == 1
    pp.refund_capture.side_effect = real_refund

    restarted = Workflow(wf.db, settings, FakeExtractor(), paypal=pp)
    if expired:
        restarted._now = lambda: (datetime.now(timezone.utc) + timedelta(hours=7)).isoformat()
    restarted.resume_unresolved_refunds()
    if expired:
        assert restarted.db.get_case(case_id)["status"] == REFUND_UNKNOWN
        with pytest.raises(RefundNotAllowed, match="6 hours"):
            restarted.execute_refund(case_id)
        assert pp.refund_capture.call_count == 1
    else:
        assert restarted.db.get_case(case_id)["status"] == REFUND_COMPLETED
        assert pp.refund_capture.call_count == 2  # same request ID, one refund at PayPal
    assert len(pp._mock_wraps.refunds_by_request) == 1
    assert restarted.db.verify_chain(case_id)["ok"]


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
    t1.start()
    t2.start()
    t1.join()
    t2.join()

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
