"""Item 2 (feat/paypal-evidence): per-case PayPal evidence timeline."""
import json
from unittest.mock import MagicMock

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.paypal_client import PayPalClient
from app.paypal_mock import MockPayPalClient
from app.views import evidence_log, evidence_summary, status_words
from tests.test_upgrade import FakeExtractor, app_ctx, case_from, refund_event  # noqa: F401
from app.notes import TemplateNoteWriter

SECRETS = ("Bearer", "access_token", "client_secret", "PAYPAL_CLIENT_SECRET", "WH-TEST", "transmission_sig")


def run_a(client):
    case_id = case_from(client.post("/demo/run/A", follow_redirects=False))
    client.post(f"/cases/{case_id}/approve", follow_redirects=False)
    return case_id


def test_success_calls_record_debug_id_request_id_and_ids(app_ctx):
    client, _, wf = app_ctx
    case_id = run_a(client)
    calls = {c["operation"]: c for c in wf.db.paypal_calls(case_id)}
    refund = calls["refund_capture"]
    assert refund["ok"] == 1 and refund["debug_id"].startswith("mock-debug-")
    assert refund["request_id"] == f"tradeos-refund-{case_id}"
    ev = json.loads(refund["evidence_json"])
    case = wf.db.get_case(case_id)
    assert ev["id"] == case["refund_id"] and ev["status"] == "COMPLETED"
    order = json.loads(calls["create_order_with_card"]["evidence_json"])
    assert order["capture_id"] == case["capture_id"] and order["capture_status"] == "COMPLETED"
    assert calls["create_order_with_card"]["request_id"]
    # debug ids are not carried over to a call that did not produce one
    assert calls["get_capture"]["debug_id"] in (None, "")


def test_log_is_in_call_order_and_summary_is_short(app_ctx):
    client, _, wf = app_ctx
    case_id = run_a(client)
    rid = wf.db.get_case(case_id)["refund_id"]
    for _ in range(2):
        client.post("/webhooks/paypal", content=json.dumps(refund_event(rid)),
                    headers={"PAYPAL-TRANSMISSION-SIG": "valid-mock-signature"})
    rows = evidence_log(wf.db, case_id)
    assert [r["what"] for r in rows][:3] == ["Create order (Orders v2, card)", "Get capture details", "Refund capture"]
    assert rows[-1]["source"] == "webhook" and [r["seq"] for r in rows] == sorted(r["seq"] for r in rows)
    assert not any(r["source"] == "tradeos" for r in rows)  # decisions live in the case timeline
    summary = {r["label"]: r["value"] for r in evidence_summary(wf.db, wf.db.get_case(case_id))}
    assert len(summary) <= 4
    assert summary["PayPal refund"].startswith(rid) and "COMPLETED" in summary["PayPal refund"]
    assert summary["PayPal trace ID"].startswith("mock-debug-")
    assert summary["Signed PayPal notice"].startswith("signature verified by PayPal's API")
    assert "1 duplicate ignored" in summary["Signed PayPal notice"]
    html = client.get(f"/?case={case_id}").text
    assert "PayPal evidence" in html and "Show details" in html and f"tradeos-refund-{case_id}" in html
    assert "MOCK PayPal" in html and "What PayPal itself reported for this case" in html
    section = html[html.index('id="evidence"'):html.index('<!-- AI understanding -->')]
    for s in SECRETS:
        assert s not in section


def test_same_second_rows_follow_call_order_not_kind(app_ctx):
    """Regression: a reconciliation-style GET capture after the refund must not sort before it."""
    client, _, wf = app_ctx
    case_id = run_a(client)
    wf._pp(case_id, "get_capture", wf.db.get_case(case_id)["capture_id"])  # same second, after refund
    whats = [r["what"] for r in evidence_log(wf.db, case_id)]
    assert whats.index("Refund capture") < len(whats) - 1 and whats[-1] == "Get capture details"


def test_blocked_case_shows_no_refund_call(app_ctx):
    client, _, wf = app_ctx
    case_id = case_from(client.post("/demo/run/B", follow_redirects=False))
    rows = evidence_log(wf.db, case_id)
    assert not any(r["what"] == "Refund capture" for r in rows)
    summary = evidence_summary(wf.db, wf.db.get_case(case_id))
    assert summary[0]["value"] == "No refund requested from PayPal"


def test_failed_refund_shows_debug_id_and_issue(app_ctx):
    client, _, wf = app_ctx
    case_id = case_from(client.post("/demo/run/R", follow_redirects=False))
    client.post(f"/cases/{case_id}/approve", follow_redirects=False)
    bad = [r for r in evidence_log(wf.db, case_id) if r["what"] == "Refund capture" and not r["ok"]]
    assert bad and bad[0]["debug_id"] == "mock-debug" and "HTTP 422" in bad[0]["status"]
    summary = evidence_summary(wf.db, wf.db.get_case(case_id))
    assert summary[0]["value"].startswith("Refund call failed") and "mock-debug" in summary[1]["value"]
    assert bad[0]["request_id"] == f"tradeos-refund-{case_id}"


def test_status_wording_echeck_and_cancelled_vs_failed():
    assert "ECHECK (eCheck; settles in a few days)" in status_words("PENDING", {"reason": "ECHECK"})
    c, f = status_words("CANCELLED"), status_words("FAILED")
    assert c != f and "CANCELLED at PayPal" in c and "needs a human" in c and "could not complete" in f


def test_pending_echeck_refund_shows_reason(settings):
    pp = MagicMock(wraps=MockPayPalClient(refund_status="PENDING"), is_mock=True)
    s = Settings(db_path=settings.db_path, rate_limit_per_minute=100, rate_limit_per_hour=100)
    app = create_app(settings=s, paypal=pp, extractor=FakeExtractor(), note_writer=TemplateNoteWriter())
    client = TestClient(app)
    orig = pp._mock_wraps.refund_capture

    def with_reason(*a, **k):
        r = orig(*a, **k)
        r["status_details"] = {"reason": "ECHECK"}
        return r
    pp.refund_capture.side_effect = with_reason
    case_id = run_a(client)
    row = [r for r in evidence_log(app.state.workflow.db, case_id) if r["what"] == "Refund capture"][0]
    assert row["status"].startswith("PENDING") and "ECHECK" in row["status"]
    summary = evidence_summary(app.state.workflow.db, app.state.workflow.db.get_case(case_id))
    assert "PENDING" in summary[0]["value"] and "eCheck" in summary[0]["value"] and summary[0]["ok"] is None


def test_real_client_keeps_success_debug_id_never_token():
    def handler(request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "SECRET-TOKEN", "expires_in": 3600})
        return httpx.Response(200, json={"id": "R1", "status": "COMPLETED"}, headers={"paypal-debug-id": "dbg123"})

    pp = PayPalClient("id", "s", "https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    assert pp.get_refund("R1")["status"] == "COMPLETED"
    assert pp.last_debug_id == "dbg123"


def test_reason_not_shown_once_completed():
    assert status_words("COMPLETED", {"reason": "ECHECK"}).startswith("COMPLETED") and "ECHECK" not in status_words("COMPLETED", {"reason": "ECHECK"})
