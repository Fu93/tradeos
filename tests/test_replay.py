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
