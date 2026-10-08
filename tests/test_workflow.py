from unittest.mock import MagicMock

import pytest

from app.db import Database
from app.intent import Extraction, IntentResult, KeywordIntentExtractor
from app.paypal_client import PayPalError
from app.paypal_mock import MockPayPalClient
from app.workflow import RefundNotAllowed, Workflow


def stages(wf, case_id):
    out = []
    for e in wf.db.timeline(case_id):
        if not out or out[-1] != e["stage"]:
            out.append(e["stage"])
    return out


def test_case_a_full_loop(workflow, paypal):
    case_id = workflow.run_scenario("A")
    case = workflow.db.get_case(case_id)
    assert case["status"] == "PENDING_APPROVAL"
    assert case["decision"] == "ELIGIBLE"
    assert case["order_id"].startswith("MOCK-ORDER") and case["capture_id"].startswith("MOCK-CAPTURE")
    assert case["intent"] == {"intent": "EXCHANGE_REQUEST", "reason": "SIZE_MISMATCH", "requested_action": "EXCHANGE"}
    assert case["supplier_reply"] == "REPLACEMENT_APPROVED"
    assert "Replacement request" in case["supplier_draft"]
    paypal.get_capture.assert_called_once_with(case["capture_id"])  # policy fed by PayPal data
    paypal.refund_capture.assert_not_called()  # no money moves before a human says yes

    workflow.approve(case_id)
    case = workflow.db.get_case(case_id)
    paypal.refund_capture.assert_called_once_with(case["capture_id"], f"tradeos-refund-{case_id}",
                                                  note_to_payer=case["payer_note"]["text"])
    assert case["payer_note"]["outcome"] == "REFUND_NOTE" and case["payer_note"]["text"].startswith("This refund of 49.99 USD")
    assert case["note"]["outcome"] == "COMPLETED_NOTE"  # final note only after PayPal COMPLETED
    assert case["status"] == "REFUND_COMPLETED"
    assert case["refund_status"] == "COMPLETED" and case["refund_id"].startswith("MOCK-REFUND")
    assert case["human_decision"] == "APPROVED"
    assert stages(workflow, case_id) == ["payment", "request", "intent", "policy", "supplier", "policy", "note", "human",
                                       "note", "paypal", "note"]


def test_case_a_double_approve_is_refused_and_refund_is_idempotent(workflow, paypal):
    case_id = workflow.run_scenario("A")
    workflow.approve(case_id)
    with pytest.raises(RefundNotAllowed):
        workflow.approve(case_id)
    workflow.execute_refund(case_id)  # retry returns existing refund, no second call
    assert paypal.refund_capture.call_count == 1


def test_case_b_rejected_and_refund_never_called(workflow, paypal):
    case_id = workflow.run_scenario("B")
    case = workflow.db.get_case(case_id)
    assert case["status"] == "REJECTED" and case["decision"] == "REJECTED"
    assert case["order_id"]  # order exists
    assert case["purchase_date_seeded"]  # seeded demo data, labelled in UI
    assert any("return window exceeded" in r for r in case["policy"]["reasons"])
    assert "45 days" in case["policy"]["reasons"][0]
    assert case["supplier_reply"] is None  # rejected before supplier contact

    with pytest.raises(RefundNotAllowed):
        workflow.approve(case_id)
    with pytest.raises(RefundNotAllowed):
        workflow.execute_refund(case_id)
    paypal.refund_capture.assert_not_called()
    assert workflow.db.paypal_calls(case_id, "refund_capture") == []
    assert workflow.db.get_case(case_id)["refund_id"] is None


def test_case_b_refund_refused_even_if_human_approval_is_forged(workflow, paypal):
    case_id = workflow.run_scenario("B")
    workflow.db.update_case(case_id, human_decision="APPROVED")  # simulate a bug / tampering
    with pytest.raises(RefundNotAllowed, match="REJECTED"):
        workflow.execute_refund(case_id)
    paypal.refund_capture.assert_not_called()


class LyingExtractor:
    """An AI that tries to push a refund through. It cannot."""
    name = "malicious"

    def extract(self, message):
        return Extraction(result=IntentResult(intent="EXCHANGE_REQUEST", reason="DAMAGED", requested_action="EXCHANGE"),
                          extractor=self.name)


def test_ai_cannot_override_policy_no(settings, paypal):
    db = Database(settings.db_path)
    db.init(reset=True)
    wf = Workflow(db, settings, LyingExtractor(), paypal=paypal)
    wf.seed_demo()
    case_id = wf.run_scenario("B")
    assert db.get_case(case_id)["decision"] == "REJECTED"
    paypal.refund_capture.assert_not_called()


def test_eligible_case_still_needs_human(workflow, paypal):
    case_id = workflow.run_scenario("A")
    with pytest.raises(RefundNotAllowed, match="Human approval"):
        workflow.execute_refund(case_id)
    paypal.refund_capture.assert_not_called()


def test_decline_never_calls_refund(workflow, paypal):
    case_id = workflow.run_scenario("A")
    workflow.decline(case_id)
    assert workflow.db.get_case(case_id)["status"] == "DECLINED_BY_HUMAN"
    with pytest.raises(RefundNotAllowed):
        workflow.execute_refund(case_id)
    paypal.refund_capture.assert_not_called()


def test_pending_refund_is_not_success_until_completed(settings):
    db = Database(settings.db_path)
    db.init(reset=True)
    pp = MockPayPalClient(refund_status="PENDING")
    wf = Workflow(db, settings, KeywordIntentExtractor(), paypal=pp)
    wf.seed_demo()
    case_id = wf.run_scenario("A")
    wf.approve(case_id)
    assert db.get_case(case_id)["status"] == "REFUND_PENDING"
    wf.refresh_refund(case_id)
    assert db.get_case(case_id)["status"] == "REFUND_COMPLETED"


def test_refund_error_is_recorded_and_visible(settings):
    db = Database(settings.db_path)
    db.init(reset=True)
    wf = Workflow(db, settings, KeywordIntentExtractor(), paypal=MockPayPalClient(fail_refund=True))
    wf.seed_demo()
    case_id = wf.run_scenario("A")
    with pytest.raises(PayPalError):
        wf.approve(case_id)
    case = db.get_case(case_id)
    assert case["status"] == "REFUND_ERROR" and "Refund failed" in case["error"]
    assert case["refund_id"] is None


def test_card_unavailable_falls_back_to_buyer_approval(settings):
    db = Database(settings.db_path)
    db.init(reset=True)
    wf = Workflow(db, settings, KeywordIntentExtractor(), paypal=MockPayPalClient(card_capture=False))
    wf.seed_demo()
    case_id = wf.run_scenario("A")
    case = db.get_case(case_id)
    assert case["status"] == "AWAITING_BUYER_APPROVAL" and case["approve_url"]
    wf.complete_buyer_approval(case_id)
    assert db.get_case(case_id)["status"] == "PENDING_APPROVAL"


def test_missing_credentials_is_a_visible_error(settings):
    db = Database(settings.db_path)
    db.init(reset=True)
    wf = Workflow(db, settings, KeywordIntentExtractor())  # no creds, no mock
    wf.seed_demo()
    case_id = wf.run_scenario("A")
    case = db.get_case(case_id)
    assert case["status"] == "ERROR" and "not configured" in case["error"]
