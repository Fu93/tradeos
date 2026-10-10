"""Item 1 (feat/paypal-depth): verified PayPal webhooks may move a PENDING refund to COMPLETED.

Rules under test: only VERIFIED events change state; verified event ids are processed once;
unverified, unknown, mismatched, stale and duplicate deliveries are logged with no state change.
"""
import json

from tests.test_upgrade import app_ctx, case_from, refund_event  # noqa: F401  (fixture re-export)

SIG_OK = {"PAYPAL-TRANSMISSION-SIG": "valid-mock-signature", "Content-Type": "application/json"}
SIG_BAD = {"PAYPAL-TRANSMISSION-SIG": "forged", "Content-Type": "application/json"}


def event(refund_id, event_id="WH-EVT-1", status="COMPLETED", capture_id="C-unknown"):
    e = refund_event(refund_id, capture_id)
    e["id"] = event_id
    e["resource"]["status"] = status
    return e


def post(client, ev, headers=SIG_OK):
    r = client.post("/webhooks/paypal", content=json.dumps(ev), headers=headers)
    assert r.status_code == 200
    return r.json()


def pending_case(client, wf):
    """Case A approved and refunded, then forced to the PENDING state PayPal can return (e.g. eCheck)."""
    case_id = case_from(client.post("/demo/run/A", follow_redirects=False))
    client.post(f"/cases/{case_id}/approve", follow_redirects=False)
    case = wf.db.get_case(case_id)
    refund = {**case["refund"], "status": "PENDING", "status_details": {"reason": "ECHECK"}}
    wf.db.update_case(case_id, refund_status="PENDING", status="REFUND_PENDING", refund_json=json.dumps(refund))
    return case_id, case["refund_id"]


def outcomes(wf, case_id=None):
    return [e["outcome"] for e in wf.db.webhook_events(case_id)]


def refund_calls(pp):
    return pp.refund_capture.call_count


def test_verified_completed_moves_pending_to_completed(app_ctx):
    client, pp, wf = app_ctx
    case_id, refund_id = pending_case(client, wf)
    calls = refund_calls(pp)
    assert post(client, event(refund_id))["verified"] is True
    case = wf.db.get_case(case_id)
    assert case["status"] == "REFUND_COMPLETED" and case["refund_status"] == "COMPLETED"
    assert case["webhook_status"] == "VERIFIED" and case["refund_id"] == refund_id
    assert (case["note"] or {}).get("outcome") == "COMPLETED_NOTE"
    assert refund_calls(pp) == calls  # no new money movement
    assert outcomes(wf, case_id) == ["PENDING_TO_COMPLETED"]
    titles = [e["title"] for e in wf.db.timeline(case_id)]
    assert "Verified PayPal webhook moved refund PENDING → COMPLETED" in titles


def test_unverified_completed_changes_nothing(app_ctx):
    client, pp, wf = app_ctx
    case_id, refund_id = pending_case(client, wf)
    assert post(client, event(refund_id), SIG_BAD)["verified"] is False
    case = wf.db.get_case(case_id)
    assert case["status"] == "REFUND_PENDING" and case["refund_status"] == "PENDING"
    assert outcomes(wf, case_id) == ["UNVERIFIED_IGNORED"]


def test_unverified_never_overwrites_verified(app_ctx):
    client, _, wf = app_ctx
    case_id, refund_id = pending_case(client, wf)
    post(client, event(refund_id, "WH-A"))
    post(client, event(refund_id, "WH-B", status="PENDING"), SIG_BAD)
    case = wf.db.get_case(case_id)
    assert case["webhook_status"] == "VERIFIED" and case["webhook"]["event_id"] == "WH-A"
    assert case["status"] == "REFUND_COMPLETED"


def test_forged_event_id_cannot_block_real_event(app_ctx):
    client, _, wf = app_ctx
    case_id, refund_id = pending_case(client, wf)
    post(client, event(refund_id, "WH-SAME"), SIG_BAD)
    post(client, event(refund_id, "WH-SAME"))
    assert wf.db.get_case(case_id)["status"] == "REFUND_COMPLETED"


def test_duplicate_verified_delivery_is_noop(app_ctx):
    client, _, wf = app_ctx
    case_id, refund_id = pending_case(client, wf)
    post(client, event(refund_id))
    before = wf.db.get_case(case_id)
    notes_before = len(wf.db.timeline(case_id))
    r = post(client, event(refund_id))
    assert r["case"] == case_id
    after = wf.db.get_case(case_id)
    assert after["refund_json"] == before["refund_json"] and after["status"] == "REFUND_COMPLETED"
    assert outcomes(wf, case_id) == ["PENDING_TO_COMPLETED", "DUPLICATE_IGNORED"]
    titles = [e["title"] for e in wf.db.timeline(case_id)][notes_before:]
    assert titles == ["Duplicate PayPal webhook delivery ignored (event already processed)"]


def test_mismatched_refund_id_is_logged_without_change(app_ctx):
    client, _, wf = app_ctx
    case_id, _ = pending_case(client, wf)
    capture_id = wf.db.get_case(case_id)["capture_id"]
    r = post(client, event("R-NOT-OURS", capture_id=capture_id))
    assert r["case"] == case_id
    case = wf.db.get_case(case_id)
    assert case["status"] == "REFUND_PENDING" and not case["webhook_status"]
    assert outcomes(wf, case_id) == ["MISMATCH_IGNORED"]


def test_event_before_refund_exists_is_ignored(app_ctx):
    client, pp, wf = app_ctx
    case_id = case_from(client.post("/demo/run/A", follow_redirects=False))  # awaiting approval, no refund
    capture_id = wf.db.get_case(case_id)["capture_id"]
    post(client, event("R-EARLY", capture_id=capture_id))
    case = wf.db.get_case(case_id)
    assert case["status"] == "PENDING_APPROVAL" and case["refund_id"] is None
    pp.refund_capture.assert_not_called()


def test_unknown_refund_is_logged_unmatched(app_ctx):
    client, _, wf = app_ctx
    assert post(client, event("R-UNKNOWN"))["case"] is None
    assert outcomes(wf) == ["UNMATCHED"]


def test_out_of_order_pending_after_completed_does_not_downgrade(app_ctx):
    client, _, wf = app_ctx
    case_id, refund_id = pending_case(client, wf)
    post(client, event(refund_id, "WH-2", status="COMPLETED"))
    post(client, event(refund_id, "WH-1", status="PENDING"))  # older event delivered late
    case = wf.db.get_case(case_id)
    assert case["status"] == "REFUND_COMPLETED" and case["refund_status"] == "COMPLETED"
    assert case["webhook"]["event_id"] == "WH-2"
    assert outcomes(wf, case_id) == ["PENDING_TO_COMPLETED", "NO_CHANGE"]


def test_verified_pending_event_keeps_pending(app_ctx):
    client, _, wf = app_ctx
    case_id, refund_id = pending_case(client, wf)
    post(client, event(refund_id, status="PENDING"))
    assert wf.db.get_case(case_id)["status"] == "REFUND_PENDING"


def test_already_completed_is_confirmation_only(app_ctx):
    client, pp, wf = app_ctx
    case_id = case_from(client.post("/demo/run/A", follow_redirects=False))
    client.post(f"/cases/{case_id}/approve", follow_redirects=False)
    before = wf.db.get_case(case_id)
    post(client, event(before["refund_id"]))
    after = wf.db.get_case(case_id)
    assert after["refund_json"] == before["refund_json"] and after["status"] == "REFUND_COMPLETED"
    assert after["webhook_status"] == "VERIFIED" and outcomes(wf, case_id) == ["CONFIRMED"]
    assert pp.refund_capture.call_count == 1


def test_unverified_on_fresh_case_changes_no_display(app_ctx):
    client, _, wf = app_ctx
    case_id, refund_id = pending_case(client, wf)
    post(client, event(refund_id), SIG_BAD)
    case = wf.db.get_case(case_id)
    assert case["webhook_status"] is None and case["webhook"] is None


def test_failure_midway_releases_event_for_retry(app_ctx, monkeypatch):
    client, _, wf = app_ctx
    case_id, refund_id = pending_case(client, wf)
    real = wf._record_refund

    def boom(*a, **k):
        raise RuntimeError("db hiccup")
    monkeypatch.setattr(wf, "_record_refund", boom)
    r = client.post("/webhooks/paypal", content=json.dumps(event(refund_id)), headers=SIG_OK)
    assert r.status_code == 500 and r.json()["retry"] is True  # PayPal will retry
    assert wf.db.get_case(case_id)["status"] == "REFUND_PENDING"
    monkeypatch.setattr(wf, "_record_refund", real)
    assert post(client, event(refund_id))["verified"] is True  # the retry is processed, not a duplicate
    assert wf.db.get_case(case_id)["status"] == "REFUND_COMPLETED"
    assert outcomes(wf, case_id) == ["FAILED_WILL_RETRY", "PENDING_TO_COMPLETED"]


def test_webhook_handler_does_not_block_event_loop():
    import inspect
    from app import main
    src = inspect.getsource(main)
    assert "run_in_threadpool(handle)" in src
