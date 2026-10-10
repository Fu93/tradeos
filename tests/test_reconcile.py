"""Item 3 (feat/paypal-reconcile): reconciliation against PayPal (GET capture + GET refund)."""
import json
from unittest.mock import MagicMock

from app.paypal_client import PayPalError
from app.paypal_mock import MockPayPalClient
from app.views import evidence_log, evidence_summary
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
    pp.complete_refund(wf.db.get_case(case_id)["refund_id"])  # PayPal settles the refund
    r = wf.reconcile(case_id)  # GET refund now reports COMPLETED
    case = wf.db.get_case(case_id)
    assert r["advanced"] and case["status"] == "REFUND_COMPLETED" and case["refund_status"] == "COMPLETED"
    assert case["note"]["outcome"] == "COMPLETED_NOTE"
    assert pp.refund_capture.call_count == 1


def test_pending_stays_pending_when_paypal_still_pending(settings):
    wf, pp, case_id = approved_a(settings, refund_status="PENDING")
    pp.get_refund.side_effect = lambda rid, timeout=None: {"id": rid, "status": "PENDING", "status_details": {"reason": "ECHECK"}}
    r = wf.reconcile(case_id)
    assert r["ok"] and wf.db.get_case(case_id)["status"] == "REFUND_PENDING"


def test_mismatch_is_flagged_never_downgrades(settings):
    wf, pp, case_id = approved_a(settings)
    pp.get_refund.side_effect = lambda rid, timeout=None: {"id": rid, "status": "PENDING", "amount": {"value": "49.99"}}
    r = wf.reconcile(case_id)
    case = wf.db.get_case(case_id)
    assert not r["ok"] and case["status"] == "REFUND_COMPLETED" and case["refund_status"] == "COMPLETED"
    row = [x for x in evidence_log(wf.db, case_id) if x["source"] == "reconcile"][-1]
    assert not row["ok"] and "refund.status: local COMPLETED vs PayPal PENDING" in row["status"]
    assert "MISMATCH" in row["what"]


def test_capture_mismatch_flagged(settings):
    wf, pp, case_id = approved_a(settings)
    pp.get_capture.side_effect = lambda cid, timeout=None: {"id": cid, "status": "COMPLETED", "amount": {"value": "49.99"}}
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
    pp.get_capture.side_effect = lambda cid, timeout=None: {**real(cid), "status": "REFUNDED"}
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


def test_view_does_not_reconcile_final_states(app_ctx):
    client, pp, wf = app_ctx
    case_id = case_from(client.post("/demo/run/A", follow_redirects=False))
    client.post(f"/cases/{case_id}/approve", follow_redirects=False)
    for _ in range(5):
        client.get(f"/?case={case_id}")
    pp.get_refund.assert_not_called()  # button-only for COMPLETED cases
    html = client.get(f"/?case={case_id}").text
    assert "Check against PayPal" in html and "not yet" in html
    client.post(f"/cases/{case_id}/refresh-refund", follow_redirects=False)
    assert pp.get_refund.call_count == 1 and pp.refund_capture.call_count == 1
    summary = {r["label"]: r for r in evidence_summary(wf.db, wf.db.get_case(case_id))}
    assert summary["Checked against PayPal"]["ok"] and summary["Checked against PayPal"]["value"].startswith("all match")


def test_view_reconciles_pending_at_most_every_30s(settings):
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app
    from tests.test_upgrade import FakeExtractor
    from app.notes import TemplateNoteWriter
    pp = MagicMock(wraps=MockPayPalClient(refund_status="PENDING"), is_mock=True)
    pp.get_refund.side_effect = lambda rid, timeout=None: {"id": rid, "status": "PENDING"}
    s = Settings(db_path=settings.db_path, rate_limit_per_minute=100, rate_limit_per_hour=100)
    app = create_app(settings=s, paypal=pp, extractor=FakeExtractor(), note_writer=TemplateNoteWriter())
    client = TestClient(app)
    case_id = case_from(client.post("/demo/run/A", follow_redirects=False))
    client.post(f"/cases/{case_id}/approve", follow_redirects=False)
    for _ in range(5):
        client.get(f"/?case={case_id}")
    assert pp.get_refund.call_count == 1
    assert pp.get_refund.call_args.kwargs["timeout"] == 5.0  # short read timeout


def test_case_b_unaffected_no_reconcile_without_refund(app_ctx):
    client, pp, wf = app_ctx
    case_id = case_from(client.post("/demo/run/B", follow_redirects=False))
    client.get(f"/?case={case_id}")
    pp.get_refund.assert_not_called()
    assert client.post(f"/cases/{case_id}/approve", follow_redirects=False).status_code == 409
    pp.refund_capture.assert_not_called()


def test_mismatch_does_not_overwrite_local_capture_status(settings):
    wf, pp, case_id = approved_a(settings)
    wf.db.update_case(case_id, capture_status="REFUNDED")
    pp.get_capture.side_effect = lambda cid, timeout=None: {"id": cid, "status": "COMPLETED"}
    assert not wf.reconcile(case_id)["ok"]
    assert wf.db.get_case(case_id)["capture_status"] == "REFUNDED"


def test_cancelled_at_paypal_needs_human(settings):
    wf, pp, case_id = approved_a(settings)
    pp.get_refund.side_effect = lambda rid, timeout=None: {"id": rid, "status": "CANCELLED"}
    r = wf.reconcile(case_id)
    assert r["needs_human"] == "PayPal reports the refund CANCELLED"
    assert wf.db.get_case(case_id)["status"] == "REFUND_COMPLETED"  # never downgraded automatically
    row = evidence_summary(wf.db, wf.db.get_case(case_id))[-1]
    assert "needs a human" in row["value"] and row["ok"] is False


def test_partially_refunded_unknown_amount_says_needs_human(settings):
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    wf, _ = make_wf(settings, paypal=pp)
    real = pp._mock_wraps.get_capture
    pp.get_capture.side_effect = lambda cid, timeout=None: {**real(cid), "status": "PARTIALLY_REFUNDED"}
    case_id = wf.run_scenario("A")
    assert wf.db.get_case(case_id)["status"] == "REJECTED"
    titles = [e["title"] for e in wf.db.timeline(case_id)]
    assert any("PARTIALLY_REFUNDED" in x and "needs a human" in x for x in titles)
    pp.refund_capture.assert_not_called()


def test_retry_on_finished_case_is_a_clear_409(app_ctx):
    client, pp, wf = app_ctx
    case_id = case_from(client.post("/demo/run/A", follow_redirects=False))
    client.post(f"/cases/{case_id}/approve", follow_redirects=False)
    r = client.post(f"/cases/{case_id}/refund", follow_redirects=False)
    assert r.status_code == 409 and "Nothing to retry" in r.text and "already COMPLETED" in r.text
    assert pp.refund_capture.call_count == 1


def test_reconcile_does_not_hold_lock_while_waiting_on_paypal(settings):
    """Regression for the review race: a slow PayPal GET must not delay a webhook for the same case."""
    import threading
    import time
    wf, pp, case_id = approved_a(settings, refund_status="PENDING")
    real = pp._mock_wraps.get_capture
    started = threading.Event()

    def slow(cid, timeout=None):
        started.set()
        time.sleep(1.5)
        return real(cid)
    pp.get_capture.side_effect = slow
    t = threading.Thread(target=wf.reconcile, args=(case_id,))
    t.start()
    started.wait(2)
    rid = wf.db.get_case(case_id)["refund_id"]
    t0 = time.monotonic()
    wf.record_webhook({"id": "WH-RACE", "event_type": "PAYMENT.CAPTURE.REFUNDED",
                       "resource": {"id": rid, "status": "COMPLETED"}}, "SUCCESS")
    assert time.monotonic() - t0 < 0.5
    t.join()
    case = wf.db.get_case(case_id)
    assert case["status"] == "REFUND_COMPLETED" and pp.refund_capture.call_count == 1


def test_webhook_endpoint_fast_while_background_reconcile_is_slow(settings):
    import time
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app
    from tests.test_upgrade import FakeExtractor
    from app.notes import TemplateNoteWriter
    mock = MockPayPalClient(refund_status="PENDING")
    s = Settings(db_path=settings.db_path, rate_limit_per_minute=100, rate_limit_per_hour=100,
                 paypal_webhook_id="WH-TEST", reconcile_in_background=True)
    app = create_app(settings=s, paypal=mock, extractor=FakeExtractor(), note_writer=TemplateNoteWriter())
    client = TestClient(app)
    case_id = case_from(client.post("/demo/run/A", follow_redirects=False))
    client.post(f"/cases/{case_id}/approve", follow_redirects=False)
    rid = app.state.workflow.db.get_case(case_id)["refund_id"]
    real = mock.get_capture
    mock.get_capture = lambda cid, timeout=None: (time.sleep(2), real(cid))[1]
    client.get(f"/?case={case_id}")  # starts the background reconcile (slow GET)
    time.sleep(0.2)
    t0 = time.monotonic()
    r = client.post("/webhooks/paypal", content=json.dumps({"id": "W1", "event_type": "PAYMENT.CAPTURE.REFUNDED",
                    "resource": {"id": rid, "status": "COMPLETED"}}), headers={"paypal-transmission-sig": "valid-mock-signature"})
    assert time.monotonic() - t0 < 0.5 and r.json()["verified"] is True
    assert app.state.workflow.db.get_case(case_id)["status"] == "REFUND_COMPLETED"
    time.sleep(2.2)  # let the background thread finish; it must not downgrade
    assert app.state.workflow.db.get_case(case_id)["status"] == "REFUND_COMPLETED"


def test_mock_pending_demo_completes_on_reconcile_after_delay(app_ctx):
    client, pp, wf = app_ctx
    pp._mock_wraps.pending_demo_seconds = 0.3
    case_id = case_from(client.post("/demo/run/P", follow_redirects=False))
    client.post(f"/cases/{case_id}/approve", follow_redirects=False)
    case = wf.db.get_case(case_id)
    assert case["status"] == "REFUND_PENDING" and case["refund"]["status_details"]["reason"] == "ECHECK"
    html = client.get(f"/?case={case_id}").text
    assert "Simulate signed PayPal webhook (MOCK)" in html and "Pending refund (MOCK)" in html
    import time
    time.sleep(0.4)
    client.post(f"/cases/{case_id}/refresh-refund", follow_redirects=False)
    assert wf.db.get_case(case_id)["status"] == "REFUND_COMPLETED"
    assert pp.refund_capture.call_count == 1


def test_mock_pending_demo_completes_via_signed_mock_webhook(app_ctx):
    client, pp, wf = app_ctx
    case_id = case_from(client.post("/demo/run/P", follow_redirects=False))
    client.post(f"/cases/{case_id}/approve", follow_redirects=False)
    assert wf.db.get_case(case_id)["status"] == "REFUND_PENDING"
    client.post(f"/demo/mock-webhook/{case_id}", follow_redirects=False)
    case = wf.db.get_case(case_id)
    assert case["status"] == "REFUND_COMPLETED" and case["webhook_status"] == "VERIFIED"
    assert [e["outcome"] for e in wf.db.webhook_events(case_id)] == ["PENDING_TO_COMPLETED"]


def test_pending_demo_and_mock_webhook_unavailable_outside_mock(settings):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.intent import KeywordIntentExtractor
    client = TestClient(create_app(settings=settings, extractor=KeywordIntentExtractor()))
    assert client.post("/demo/run/P", follow_redirects=False).status_code == 404
    assert client.post("/demo/mock-webhook/A-XXXX", follow_redirects=False).status_code == 404


def test_reconcile_throttle_map_is_bounded_and_reset_clears_it(app_ctx, monkeypatch):
    import app.workflow as w
    client, _, wf = app_ctx
    monkeypatch.setattr(w, "MAX_TRACKED_CASES", 3)
    for i in range(10):
        wf._reconciled[f"X{i}"] = float(i)
    case_id = case_from(client.post("/demo/run/P", follow_redirects=False))
    client.post(f"/cases/{case_id}/approve", follow_redirects=False)
    client.get(f"/?case={case_id}")  # PENDING -> view trigger records the case
    assert len(wf._reconciled) <= 3 and case_id in wf._reconciled
    client.post("/demo/reset", follow_redirects=False)
    assert wf._reconciled == {}
