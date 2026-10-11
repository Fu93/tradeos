"""Correctness batch from the 2026-10-11 audit: refund error classification (408/429/sent),
process() serialization under the case lock, the money-action rate-limit budget, the bounded
rate-limiter key map, and the webhook body cap."""
import json
import threading

import pytest

from app.config import Settings
from app.paypal_client import PayPalError
from app.ratelimit import RateLimiter
from app.workflow import PENDING_APPROVAL, REFUND_ERROR, REFUND_UNKNOWN
from tests.test_admin_and_guards import make
from tests.test_upgrade import case_from


# ---------------------------------------------------------------- refund error classification
def _approve_with_failure(wf, exc):
    case_id = wf.run_scenario("A")
    wf._paypal.refund_capture.side_effect = exc
    with pytest.raises(PayPalError):
        wf.approve(case_id)  # recorded on the case, then re-raised (the route layer turns it into a redirect)
    return case_id


def test_408_and_429_are_outcome_unknown(workflow):
    """408 is itself a timeout and 429 throttling: PayPal may have accepted the request, so the
    case must NOT say 'no money moved' (FAILURE_NOTE) — it goes to the UNKNOWN check instead."""
    for status in (408, 429):
        case_id = _approve_with_failure(workflow, PayPalError("slow down", status_code=status))
        case = workflow.db.get_case(case_id)
        assert case["status"] == REFUND_UNKNOWN, status
        assert (case.get("note") or {}).get("outcome") != "FAILURE_NOTE", status
        titles = [e["title"] for e in workflow.db.timeline(case_id)]
        assert any("outcome UNKNOWN" in t for t in titles), status


def test_plain_4xx_stays_refund_error(workflow):
    case_id = _approve_with_failure(workflow, PayPalError("nope", status_code=422))
    case = workflow.db.get_case(case_id)
    assert case["status"] == REFUND_ERROR
    assert (case.get("note") or {}).get("outcome") == "FAILURE_NOTE"


def test_locally_refunded_never_sent_is_refund_error_without_check(workflow):
    """sent=False: the request was refused before it reached PayPal (e.g. a sandbox guard), so the
    outcome is certain — no UNKNOWN background check, and the customer note may say no money moved."""
    case_id = _approve_with_failure(workflow, PayPalError("refused locally", sent=False))
    case = workflow.db.get_case(case_id)
    assert case["status"] == REFUND_ERROR
    assert (case.get("note") or {}).get("outcome") == "FAILURE_NOTE"
    titles = [e["title"] for e in workflow.db.timeline(case_id)]
    assert not any("Checked with PayPal after" in t for t in titles)


# ---------------------------------------------------------------- process serialization
def test_duplicate_process_run_skips_before_paying_twice(workflow):
    wf = workflow
    case_id = wf.run_scenario("A")
    before = wf.db.get_case(case_id)
    wf.process(case_id)  # a late duplicate of the Run
    after = wf.db.get_case(case_id)
    assert wf._paypal.create_order_with_card.call_count == 1  # no second order was paid for
    assert after["status"] == before["status"]
    titles = [e["title"] for e in wf.db.timeline(case_id)]
    assert any("Run skipped" in t for t in titles)


def test_concurrent_process_runs_serialize(workflow):
    wf = workflow
    case_id = wf.new_case("A")
    barrier = threading.Barrier(2)

    def run():
        barrier.wait()
        wf.process(case_id)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert wf._paypal.create_order_with_card.call_count == 1
    assert wf.db.get_case(case_id)["status"] == PENDING_APPROVAL


# ---------------------------------------------------------------- rate limits
def test_rate_limiter_drops_keys_whose_window_gone_empty():
    t = [0.0]
    rl = RateLimiter(per_minute=5, per_hour=30, global_per_hour=10 ** 9, clock=lambda: t[0])
    for i in range(6000):
        t[0] += 2  # every address hits once, two seconds apart
        assert rl.check(f"addr-{i}") is None
    assert len(rl._hits) <= 5000  # the map cannot grow without bound on rotating addresses
    assert "addr-0" not in rl._hits  # old windows are dropped, not just ignored


def test_money_endpoints_have_their_own_budget(settings):
    client, pp, wf = make(settings)
    case = case_from(client.post("/demo/run/A", follow_redirects=False))
    codes = [client.post(f"/cases/{case}/approve", follow_redirects=False).status_code for _ in range(31)]
    # one real approval (303), the rest refused on state (409) — and the 31st hits the money budget
    assert codes.count(303) == 1 and codes[-1] == 429
    assert pp.refund_capture.call_count == 1


def test_cf_connecting_ip_not_trusted_by_default():
    assert Settings().trust_cf_connecting_ip is False
    assert Settings.from_env().trust_cf_connecting_ip is False


# ---------------------------------------------------------------- webhook body cap
def test_webhook_rejects_oversized_bodies(settings):
    client, pp, wf = make(settings)
    big = json.dumps({"id": "WH-BIG", "event_type": "PAYMENT.CAPTURE.REFUNDED",
                      "resource": {"id": "R1", "status": "COMPLETED", "pad": "x" * 70000}}).encode()
    r = client.post("/webhooks/paypal", content=big,
                    headers={"PAYPAL-TRANSMISSION-SIG": "valid-mock-signature"})
    assert r.status_code == 400
    assert wf.db.webhook_events() == []  # nothing was written, not even an unverified row
    assert pp.refund_capture.call_count == 0
