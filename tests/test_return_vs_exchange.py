"""Return -> refund; exchange -> supplier replacement with NO refund (Refund API never called)."""
import json
import re
from dataclasses import replace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.intent import KeywordIntentExtractor
from app.main import create_app
from app.notes import TemplateNoteWriter, makes_completion_claim
from app.paypal_mock import MockPayPalClient
from app.presets import BY_KEY, PRESETS
from app.views import evidence_log, evidence_summary, pipeline, result_card
from app.workflow import DEMO_MESSAGE, EXCHANGE_MESSAGE, RefundNotAllowed, Workflow

ORIGIN = {"origin": "http://testserver"}


def mk(settings, **kw):
    db = Database(settings.db_path)
    db.init(reset=True)
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    wf = Workflow(db, replace(settings, **kw), KeywordIntentExtractor(), paypal=pp)
    wf.seed_demo()
    return wf, pp


def test_case_a_is_a_return_and_refunds_once(settings):
    wf, pp = mk(settings)
    cid = wf.run_scenario("A")
    case = wf.db.get_case(cid)
    assert case["customer_message"] == DEMO_MESSAGE
    assert case["intent"]["requested_action"] == "REFUND" and case["decision"] == "ELIGIBLE"
    assert case["supplier_draft"] is None  # supplier not involved in a return
    wf.approve(cid)
    assert wf.db.get_case(cid)["status"] == "REFUND_COMPLETED"
    assert pp.refund_capture.call_count == 1


def test_exchange_arranged_without_any_refund(settings):
    wf, pp = mk(settings)
    cid = wf.run_free_text(EXCHANGE_MESSAGE)
    case = wf.db.get_case(cid)
    assert case["status"] == "PENDING_APPROVAL" and case["decision"] == "EXCHANGE_ELIGIBLE"
    assert case["supplier_reply"] == "REPLACEMENT_APPROVED" and "Replacement request" in case["supplier_draft"]
    assert result_card(wf.db, case)["title"] == "Awaiting human approval of the exchange"
    with pytest.raises(RefundNotAllowed):  # the refund gate refuses an exchange outright
        wf.execute_refund(cid)
    wf.approve(cid)
    case = wf.db.get_case(cid)
    assert case["status"] == "EXCHANGE_ARRANGED" and case["human_decision"] == "APPROVED"
    pp.refund_capture.assert_not_called()
    assert not wf.db.paypal_calls(cid, "refund_capture") and case["refund_id"] is None
    titles = [e["title"] for e in wf.db.timeline(cid)]
    assert "Human approved the exchange" in titles
    assert any(t.startswith("Refund API NOT CALLED — exchange arranged") for t in titles)
    card = result_card(wf.db, case)
    assert card["title"] == "Exchange arranged — no refund" and ("Refund API calls", "0") in card["rows"]
    assert {s["key"]: s["state"] for s in pipeline(wf.db, case)}["paypal"] == "skipped"
    assert case["note"]["outcome"] == "EXCHANGE_NOTE" and "refund" in case["note"]["text"]
    assert not makes_completion_claim(case["note"]["text"].replace("approved", ""))  # never "refunded"


def test_exchange_is_idempotent_and_never_refunds(settings):
    wf, pp = mk(settings)
    cid = wf.run_free_text(EXCHANGE_MESSAGE)
    wf.approve(cid)
    for action in (wf.approve, wf.execute_refund, wf.replay_refund_request, wf.retry_failed_refund):
        with pytest.raises(RefundNotAllowed):
            action(cid)
    pp.refund_capture.assert_not_called()
    assert len([e for e in wf.db.timeline(cid) if e["title"] == "Human approved the exchange"]) == 1


def test_exchange_audit_chain(settings):
    wf, _ = mk(settings)
    cid = wf.run_free_text(EXCHANGE_MESSAGE)
    wf.approve(cid)
    chain = wf.db.verify_chain(cid)
    st = wf.db.chained_case_state(cid)
    assert chain["ok"] and st["decision"] == "EXCHANGE_ELIGIBLE" and st["human_decision"] == "APPROVED"
    assert st["status"] == "EXCHANGE_ARRANGED" and st.get("refund_id") is None


def test_exchange_evidence_panel_has_no_refund_calls(settings):
    wf, _ = mk(settings)
    cid = wf.run_free_text(EXCHANGE_MESSAGE)
    wf.approve(cid)
    ops = [r.get("operation") or r.get("kind") for r in evidence_log(wf.db, cid)]
    assert "refund_capture" not in json.dumps(evidence_log(wf.db, cid))
    assert ops  # order + capture + GET capture are there
    text = json.dumps(evidence_summary(wf.db, wf.db.get_case(cid)))
    assert "refund_capture" not in text


def test_out_of_stock_needs_a_human_and_never_refunds(settings):
    wf, pp = mk(settings, mock_supplier_out_of_stock=True)
    cid = wf.run_free_text(EXCHANGE_MESSAGE)
    case = wf.db.get_case(cid)
    assert case["status"] == "NEEDS_HUMAN" and case["supplier_reply"] == "OUT_OF_STOCK"
    assert result_card(wf.db, case)["title"].startswith("Needs a human: replacement out of stock — offer a refund?")
    for action in (wf.approve, wf.execute_refund):
        with pytest.raises(RefundNotAllowed):
            action(cid)
    pp.refund_capture.assert_not_called()
    assert wf.db.verify_chain(cid)["ok"]


def test_out_of_stock_only_affects_exchanges(settings):
    wf, pp = mk(settings, mock_supplier_out_of_stock=True)
    cid = wf.run_scenario("A")  # a return never asks the supplier
    wf.approve(cid)
    assert wf.db.get_case(cid)["status"] == "REFUND_COMPLETED" and pp.refund_capture.call_count == 1


def test_case_b_still_409_over_http(settings):
    s = replace(settings, rate_limit_per_minute=100, rate_limit_per_hour=100)
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    app = create_app(settings=s, paypal=pp, extractor=KeywordIntentExtractor(), note_writer=TemplateNoteWriter())
    client = TestClient(app)
    r = client.post("/demo/run/B", headers=ORIGIN, follow_redirects=False)
    cid = re.search(r"case=([A-Z]-[0-9A-F]+)", r.headers["location"]).group(1)
    assert client.post(f"/cases/{cid}/approve", headers=ORIGIN).status_code == 409
    pp.refund_capture.assert_not_called()


def test_exchange_page_and_http_refund_refused(settings):
    s = replace(settings, rate_limit_per_minute=100, rate_limit_per_hour=100)
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    app = create_app(settings=s, paypal=pp, extractor=KeywordIntentExtractor(), note_writer=TemplateNoteWriter())
    client, wf = TestClient(app), app.state.workflow
    cid = wf.run_free_text(EXCHANGE_MESSAGE)
    assert "Approve exchange (no refund)" in client.get(f"/?case={cid}").text
    client.post(f"/cases/{cid}/approve", headers=ORIGIN)
    html = client.get(f"/?case={cid}").text
    assert "Exchange arranged — no refund" in html and "MOCK" in html
    assert client.post(f"/cases/{cid}/refund", headers=ORIGIN).status_code == 409
    pp.refund_capture.assert_not_called()


def test_presets_mix_returns_and_exchanges():
    paths = {p["key"]: p.get("path") for p in PRESETS}
    assert paths["zh"] == "exchange" and "42" in BY_KEY["zh"]["message"] and "43" in BY_KEY["zh"]["message"]
    assert list(paths.values()).count("refund") >= 2 and list(paths.values()).count("exchange") >= 1
    kw = KeywordIntentExtractor()
    assert kw.extract(BY_KEY["en"]["message"]).result.requested_action == "REFUND"
    assert kw.extract(BY_KEY["late"]["message"]).result.requested_action == "REFUND"


def test_late_and_injection_presets_still_rejected(settings):
    wf, pp = mk(settings)
    late = wf.run_free_text(BY_KEY["late"]["message"], late=True)
    inj = wf.run_free_text(BY_KEY["injection"]["message"])
    assert wf.db.get_case(late)["status"] == "REJECTED" and wf.db.get_case(inj)["status"] == "REJECTED"
    pp.refund_capture.assert_not_called()
    _ = Settings
