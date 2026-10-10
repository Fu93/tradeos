"""Webhook replay window on paypal-transmission-time."""
import json
from datetime import datetime, timedelta, timezone

from tests.test_hardening import SIG, app_with, pending_case, refund_event, run_a


def ts(delta_s):
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_s)).strftime("%Y-%m-%dT%H:%M:%SZ")


def send(client, ev, ttime):
    h = dict(SIG)
    if ttime is not None:
        h["paypal-transmission-time"] = ttime
    return client.post("/webhooks/paypal", content=json.dumps(ev), headers=h)


def outcomes(wf, case_id):
    return [e["outcome"] for e in wf.db.webhook_events(case_id)]


def test_fresh_event_processed_normally(settings):
    client, pp, wf, case_id, rid = pending_case(settings)
    send(client, refund_event(rid), ts(-30))
    assert wf.db.get_case(case_id)["refund_status"] == "COMPLETED"
    assert outcomes(wf, case_id) == ["PENDING_TO_COMPLETED"]


def test_replay_of_processed_event_with_old_time_rejected(settings):
    client, pp, wf, case_id, rid = pending_case(settings)
    old = ts(-3600)
    send(client, refund_event(rid, "PAYMENT.REFUND.PENDING", "PENDING", eid="E1"), ts(-5))
    r = send(client, refund_event(rid, "PAYMENT.REFUND.PENDING", "PENDING", eid="E1"), old)
    assert r.status_code == 200
    assert outcomes(wf, case_id) == ["PENDING_CONFIRMED", "STALE_REPLAY_REJECTED"]
    assert any("stale/replay" in e["title"] for e in wf.db.timeline(case_id))


def test_future_dated_event_rejected_without_claiming_event_id(settings):
    client, pp, wf, case_id, rid = pending_case(settings)
    r = send(client, refund_event(rid, eid="E2"), ts(+3600))
    assert r.status_code == 200
    assert wf.db.get_case(case_id)["refund_status"] == "PENDING"
    send(client, refund_event(rid, eid="E2"), ts(-1))  # the legitimate delivery still works
    assert outcomes(wf, case_id) == ["STALE_REPLAY_REJECTED", "PENDING_TO_COMPLETED"]


def test_small_future_skew_allowed(settings):
    client, pp, wf, case_id, rid = pending_case(settings)
    send(client, refund_event(rid), ts(+60))
    assert wf.db.get_case(case_id)["refund_status"] == "COMPLETED"


def test_old_unseen_event_uses_paypal_get_not_payload(settings):
    """Late legit retry: accepted, but the state follows PayPal's GET, not the old payload."""
    client, pp, wf, case_id, rid = pending_case(settings)
    # Payload claims FAILED; PayPal (GET) still says PENDING -> no change.
    pp.get_refund.side_effect = lambda r, timeout=None: {"id": r, "status": "PENDING"}
    send(client, refund_event(rid, "PAYMENT.REFUND.FAILED", "FAILED", eid="E3"), ts(-7200))
    assert wf.db.get_case(case_id)["refund_status"] == "PENDING"
    assert outcomes(wf, case_id) == ["STALE_GET_CHECK"]
    assert pp.get_refund.call_count >= 1 and pp.refund_capture.call_count == 1
    # PayPal completes it; a late COMPLETED event now advances via the GET result.
    pp.get_refund.side_effect = lambda r, timeout=None: {"id": r, "status": "COMPLETED"}
    send(client, refund_event(rid, eid="E4"), ts(-7200))
    assert wf.db.get_case(case_id)["refund_status"] == "COMPLETED"
    assert pp.refund_capture.call_count == 1


def test_old_event_without_state_change_still_processed(settings):
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    rid = wf.db.get_case(case_id)["refund_id"]
    send(client, refund_event(rid, "PAYMENT.REFUND.FAILED", "FAILED", eid="E5"), ts(-7200))
    assert wf.db.get_case(case_id)["refund_status"] == "COMPLETED"
    assert outcomes(wf, case_id) == ["NO_CHANGE"]


def test_unparseable_time_treated_as_stale(settings):
    client, pp, wf, case_id, rid = pending_case(settings)
    pp.get_refund.side_effect = lambda r, timeout=None: {"id": r, "status": "PENDING"}
    send(client, refund_event(rid, "PAYMENT.REFUND.FAILED", "FAILED", eid="E6"), "not-a-time")
    assert wf.db.get_case(case_id)["refund_status"] == "PENDING"
    assert outcomes(wf, case_id) == ["STALE_GET_CHECK"]


def test_window_is_configurable(settings):
    client, pp, wf, case_id, rid = pending_case(settings)
    import dataclasses
    wf.settings = dataclasses.replace(wf.settings, webhook_max_age_s=10 * 24 * 3600)
    send(client, refund_event(rid), ts(-3 * 24 * 3600))
    assert outcomes(wf, case_id) == ["PENDING_TO_COMPLETED"]


def test_unverified_old_event_still_just_unverified(settings):
    client, pp, wf, case_id, rid = pending_case(settings)
    client.post("/webhooks/paypal", content=json.dumps(refund_event(rid)),
                headers={"paypal-transmission-sig": "bad", "paypal-transmission-time": ts(-7200)})
    assert outcomes(wf, case_id) == ["UNVERIFIED_IGNORED"]


# ---------------------------------------------------------------- review gates (PR #14)
import threading

import pytest

from app.paypal_client import PayPalError


def test_late_event_get_failure_no_body_trust_no_success_id_not_consumed(settings):
    client, pp, wf, case_id, rid = pending_case(settings)
    pp.get_capture.side_effect = PayPalError("Could not reach PayPal: ReadTimeout")
    r = send(client, refund_event(rid, eid="E-LATE"), ts(-7200))  # body says COMPLETED
    assert r.status_code == 500 and r.json()["retry"] is True     # not acknowledged -> PayPal retries
    case = wf.db.get_case(case_id)
    assert case["refund_status"] == "PENDING" and case["status"] == "REFUND_PENDING"
    assert case["webhook_status"] is None
    assert not wf.db.webhook_event_seen("E-LATE")
    assert "Refund COMPLETED" not in client.get(f"/?case={case_id}").text
    # PayPal recovers: the retried (still old) delivery is processed via GET, not rejected as a replay.
    pp.get_capture.side_effect = None
    pp.get_refund.side_effect = lambda r_, timeout=None: {"id": r_, "status": "COMPLETED"}
    assert send(client, refund_event(rid, eid="E-LATE"), ts(-7200)).status_code == 200
    assert wf.db.get_case(case_id)["refund_status"] == "COMPLETED"
    assert outcomes(wf, case_id)[-1] == "STALE_GET_CHECK"
    assert pp.refund_capture.call_count == 1


def test_late_get_never_downgrades_completed(settings):
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    pp.get_refund.side_effect = lambda r_, timeout=None: {"id": r_, "status": "PENDING"}
    wf.reconcile(case_id)
    assert wf.db.get_case(case_id)["refund_status"] == "COMPLETED"


def test_terminal_failed_not_overwritten_by_old_completed_event(settings):
    client, pp, wf, case_id, rid = pending_case(settings)
    send(client, refund_event(rid, "PAYMENT.REFUND.FAILED", "FAILED", eid="F1"), ts(-5))
    assert wf.db.get_case(case_id)["refund_status"] == "FAILED"
    for age in (-5, -7200):
        send(client, refund_event(rid, eid=f"C{age}"), ts(age))
    assert wf.db.get_case(case_id)["refund_status"] == "FAILED"
    assert outcomes(wf, case_id)[-2:] == ["NEEDS_HUMAN", "NEEDS_HUMAN"]


def test_state_moved_while_get_in_flight_is_rechecked_under_lock(settings):
    """GET said PENDING (late/stale answer) while a webhook completed the refund: no downgrade."""
    client, pp, wf, case_id, rid = pending_case(settings)

    def slow_pending(r_, timeout=None):
        send(client, refund_event(rid, eid="W-FRESH"), ts(-1))  # completes it meanwhile
        return {"id": r_, "status": "PENDING"}
    pp.get_refund.side_effect = slow_pending
    wf.reconcile(case_id)
    assert wf.db.get_case(case_id)["refund_status"] == "COMPLETED"


@pytest.mark.parametrize("bad", [{"id": "OTHER-REFUND", "status": "COMPLETED"},
                                 {"status": "COMPLETED", "links": [{"rel": "up",
                                  "href": "https://api.sandbox.paypal.com/v2/payments/captures/OTHERCAP"}]}])
def test_get_result_must_belong_to_this_case(settings, bad):
    client, pp, wf, case_id, rid = pending_case(settings)
    pp.get_refund.side_effect = lambda r_, timeout=None: {"id": r_, **bad} if "id" not in bad else dict(bad)
    res = wf.reconcile(case_id)
    assert res["ok"] is False and not res["advanced"]
    assert wf.db.get_case(case_id)["refund_status"] == "PENDING"


def test_capture_id_mismatch_flagged_no_change(settings):
    client, pp, wf, case_id, rid = pending_case(settings)
    pp.get_capture.side_effect = lambda c, timeout=None: {"id": "OTHERCAP", "status": "COMPLETED"}
    pp.get_refund.side_effect = lambda r_, timeout=None: {"id": r_, "status": "COMPLETED"}
    res = wf.reconcile(case_id)
    assert res["ok"] is False
    assert any(c["field"] == "capture.id" for c in res["checks"])


def test_event_for_unknown_refund_with_only_a_status_changes_nothing(settings):
    client, pp, wf, case_id, rid = pending_case(settings)
    send(client, {"id": "E-NOID", "event_type": "PAYMENT.CAPTURE.REFUNDED", "resource": {"status": "COMPLETED"}}, ts(-1))
    assert wf.db.get_case(case_id)["refund_status"] == "PENDING"


@pytest.mark.parametrize("age", [-1, -7200])
def test_concurrent_duplicates_one_side_effect(settings, age):
    client, pp, wf, case_id, rid = pending_case(settings)
    pp.get_refund.side_effect = lambda r_, timeout=None: {"id": r_, "status": "COMPLETED"}
    calls = []
    real = wf._record_refund
    wf._record_refund = lambda *a, **k: (calls.append(1), real(*a, **k))
    go = threading.Barrier(6)

    def worker():
        go.wait()
        send(client, refund_event(rid, eid="E-DUP"), ts(age))
    ths = [threading.Thread(target=worker) for _ in range(6)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    outs = outcomes(wf, case_id)
    claimed = [o for o in outs if o in ("PENDING_TO_COMPLETED", "STALE_GET_CHECK")]
    assert len(claimed) == 1 and outs.count("DUPLICATE_IGNORED") + outs.count("STALE_REPLAY_REJECTED") == 5
    assert len(calls) == 1 and wf.db.get_case(case_id)["refund_status"] == "COMPLETED"
    assert pp.refund_capture.call_count == 1


@pytest.mark.parametrize("ttime,expected", [
    (None, "unknown"), ("", "unknown"), ("garbage", "stale"), ("1696950000", "stale"),
    ("2026-13-40T99:00:00Z", "stale")])
def test_malformed_times(settings, ttime, expected):
    client, pp, wf = app_with(settings)
    assert wf.transmission_age(ttime) == expected


def test_skew_boundaries_and_offsets(settings):
    client, pp, wf = app_with(settings)
    assert wf.transmission_age(ts(+100)) == "fresh"
    assert wf.transmission_age(ts(+200)) == "future"
    assert wf.transmission_age(ts(-500)) == "fresh"
    assert wf.transmission_age(ts(-700)) == "stale"
    local = (datetime.now(timezone.utc) + timedelta(hours=-7)).strftime("%Y-%m-%dT%H:%M:%S-07:00")
    assert wf.transmission_age(local) == "fresh"
    assert wf.transmission_age(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")) == "fresh"  # naive = UTC
