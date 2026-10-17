"""Display-only 'PayPal proves' panel: debug IDs, webhook signature result/method, reconcile status."""
import json

from app.views import paypal_proves
from tests.helpers import app_ctx, case_from  # noqa: F401
from tests.test_evidence import run_a
from tests.test_upgrade import refund_event


def panel_html(html: str) -> str:
    return html[html.index('id="paypal-proves"'):html.index('<details class="ev-log">')]


def test_proves_panel_before_any_webhook_or_reconcile(app_ctx):
    client, _, wf = app_ctx
    case_id = run_a(client)
    p = paypal_proves(wf.db, wf.db.get_case(case_id))
    assert p["refund"]["status"] == "COMPLETED" and p["refund"]["ok"] is True
    assert [d["operation"] for d in p["debug_ids"]][-1] == "Refund capture"
    assert all(d["debug_id"].startswith("mock-debug-") for d in p["debug_ids"])
    assert p["webhook"]["state"] == "waiting" and p["webhook"]["ok"] is None
    assert p["reconcile"] == {"done": False, "ok": None, "text": "not yet — press “Check against PayPal”", "time": None}
    html = panel_html(client.get(f"/?case={case_id}").text)
    assert "PayPal proves" in html and "PayPal-Debug-Id (" in html and "Not verified yet" in html
    assert "Not checked yet" in html and "MOCK mode" in html  # never presents mock IDs as real PayPal


def test_proves_panel_shows_verified_method_event_and_reconcile(app_ctx):
    client, _, wf = app_ctx
    case_id = run_a(client)
    rid = wf.db.get_case(case_id)["refund_id"]
    ev = refund_event(rid)
    for _ in range(2):
        client.post("/webhooks/paypal", content=json.dumps(ev), headers={"PAYPAL-TRANSMISSION-SIG": "valid-mock-signature"})
    client.post(f"/cases/{case_id}/refresh-refund", follow_redirects=False)
    p = paypal_proves(wf.db, wf.db.get_case(case_id))
    w = p["webhook"]
    assert w["state"] == "verified" and w["ok"] is True and w["method_key"] == "postback"
    assert "verify-webhook-signature API" in w["method"] and w["event_id"] and w["duplicates"] == 1
    assert p["reconcile"]["done"] and p["reconcile"]["ok"] and p["reconcile"]["text"].startswith("all match")
    html = panel_html(client.get(f"/?case={case_id}").text)
    assert "Verified ✓" in html and "verify-webhook-signature API" in html and w["event_id"] in html
    assert "1 duplicate delivery ignored" in html and "Checked" in html
    for d in p["debug_ids"]:
        assert d["debug_id"] in html


def test_proves_panel_unverified_webhook_is_not_shown_as_proof(app_ctx):
    client, _, wf = app_ctx
    case_id = run_a(client)
    rid = wf.db.get_case(case_id)["refund_id"]
    client.post("/webhooks/paypal", content=json.dumps(refund_event(rid)), headers={"PAYPAL-TRANSMISSION-SIG": "forged"})
    p = paypal_proves(wf.db, wf.db.get_case(case_id))
    assert p["webhook"]["state"] == "waiting" and p["webhook"]["ok"] is None and p["webhook"]["unverified"] >= 1
    html = panel_html(client.get(f"/?case={case_id}").text)
    assert "Verified ✓" not in html and "rejected as unverified" in html


def test_proves_panel_no_refund_and_secrets_absent(app_ctx):
    client, _, wf = app_ctx
    case_id = case_from(client.post("/demo/run/B", follow_redirects=False))  # rejected by the return window
    p = paypal_proves(wf.db, wf.db.get_case(case_id))
    assert p["refund"] is None
    html = panel_html(client.get(f"/?case={case_id}").text)
    assert "No refund has been requested from PayPal" in html
    for s in ("Bearer", "access_token", "client_secret", "transmission_sig"):
        assert s not in html
