
import pytest

from app.db import Database
from app.intent import Extraction, IntentResult, KeywordIntentExtractor
from app.paypal_client import PayPalError
from app.paypal_mock import MockPayPalClient
from app.inbox import _next_step
from app.views import evidence_a, evidence_summary, paypal_proves, pipeline, result_card
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
    assert case["intent"] == {"intent": "REFUND_REQUEST", "reason": "NOT_AS_DESCRIBED", "requested_action": "REFUND"}
    assert case["supplier_reply"] is None and case["supplier_draft"] is None  # a return never contacts the supplier
    paypal.get_capture.assert_called_once_with(case["capture_id"])  # policy fed by PayPal data
    paypal.refund_capture.assert_not_called()  # no money moves before a human says yes

    workflow.approve(case_id)
    case = workflow.db.get_case(case_id)
    paypal.refund_capture.assert_called_once_with(
        case["capture_id"], f"tradeos-refund-{case_id}", note_to_payer=case["payer_note"]["text"],
        amount={"currency_code": case["currency"], "value": case["amount"]}, custom_id=case_id)
    assert case["payer_note"]["outcome"] == "REFUND_NOTE" and case["payer_note"]["text"].startswith("This refund of 49.99 USD")
    assert case["note"]["outcome"] == "COMPLETED_NOTE"  # final note only after PayPal COMPLETED
    assert case["status"] == "REFUND_COMPLETED"
    assert case["refund_status"] == "COMPLETED" and case["refund_id"].startswith("MOCK-REFUND")
    assert case["human_decision"] == "APPROVED"
    assert stages(workflow, case_id) == ["payment", "request", "intent", "policy", "human", "note",
                                       "human", "policy", "human", "note", "paypal", "note"]


@pytest.mark.parametrize("change", [
    {"status": "PARTIALLY_REFUNDED"},
    {"status": "REFUNDED"},
    {"status": "REVERSED"},
    {"amount": {"value": "99.99", "currency_code": "USD"}},
    {"amount": {"value": "49.99", "currency_code": "EUR"}},
    {"id": "MOCK-OTHER-CAPTURE"},
])
def test_approval_refuses_changed_paypal_capture(workflow, paypal, change):
    case_id = workflow.run_scenario("A")
    case = workflow.db.get_case(case_id)
    paypal._mock_wraps.captures[case["capture_id"]].update(change)

    with pytest.raises(RefundNotAllowed, match="manual review"):
        workflow.approve(case_id)

    after = workflow.db.get_case(case_id)
    assert after["status"] == "NEEDS_HUMAN" and after["decision"] == "NEEDS_HUMAN"
    assert after["human_decision"] is None and after["refund_request_id"] is None
    assert workflow.db.verify_chain(case_id)["ok"]
    assert after["policy"]["preflight_blocked"] is True
    assert "Refund re-check blocked" in result_card(workflow.db, after)["title"]
    assert "PayPal capture or refund policy changed" in _next_step(after)[1]
    assert "PayPal capture or policy changed" in next(
        step["detail"] for step in pipeline(workflow.db, after) if step["key"] == "policy")
    assert any("Refund API NOT CALLED — capture or policy changed" in e["title"]
               for e in workflow.db.timeline(case_id))
    paypal.refund_capture.assert_not_called()
    assert workflow.db.paypal_calls(case_id, "refund_capture") == []


def test_approval_recheck_unavailable_preserves_pending_case(workflow, paypal):
    case_id = workflow.run_scenario("A")
    paypal.get_capture.side_effect = PayPalError("temporary PayPal outage", 503)
    with pytest.raises(RefundNotAllowed, match="Could not re-check"):
        workflow.approve(case_id)
    case = workflow.db.get_case(case_id)
    assert case["status"] == "PENDING_APPROVAL" and case["human_decision"] is None
    paypal.refund_capture.assert_not_called()
    paypal.get_capture.side_effect = None
    workflow.approve(case_id)
    assert workflow.db.get_case(case_id)["status"] == "REFUND_COMPLETED"


def test_external_partial_refund_after_preflight_cannot_change_sent_amount(workflow, paypal):
    case_id = workflow.run_scenario("A")
    original = paypal._mock_wraps.refund_capture

    def external_refund_first(capture_id, request_id, **kwargs):
        original(capture_id, "external-after-preflight",
                 amount={"currency_code": "USD", "value": "10.00"})
        return original(capture_id, request_id, **kwargs)

    paypal.refund_capture.side_effect = external_refund_first
    with pytest.raises(PayPalError, match="exceeds what is left"):
        workflow.approve(case_id)
    case = workflow.db.get_case(case_id)
    assert case["status"] == "REFUND_ERROR" and case["refund_id"] is None
    assert set(paypal._mock_wraps.refunds_by_request) == {"external-after-preflight"}
    assert workflow.db.verify_chain(case_id)["ok"]


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
    workflow.db.update_case(case_id, force=True, human_decision="APPROVED")  # simulate a bug / tampering
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


def test_eligible_case_still_needs_an_approval(workflow, paypal):
    case_id = workflow.run_scenario("A")
    with pytest.raises(RefundNotAllowed, match="approval is required"):
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
    wf.refresh_refund(case_id)  # PayPal still PENDING: no change
    assert db.get_case(case_id)["status"] == "REFUND_PENDING"
    pp.complete_refund(db.get_case(case_id)["refund_id"])
    wf.refresh_refund(case_id)
    assert db.get_case(case_id)["status"] == "REFUND_COMPLETED"


@pytest.mark.parametrize("returned_amount", [
    {"value": "5.00", "currency_code": "USD"},
    {"value": "49.99", "currency_code": "EUR"},
    None,
])
def test_completed_refund_requires_matching_amount_before_success(workflow, paypal, returned_amount):
    case_id = workflow.run_scenario("A")
    original = paypal._mock_wraps.refund_capture

    def altered_response(*args, **kwargs):
        refund = original(*args, **kwargs)
        if returned_amount is None:
            refund.pop("amount", None)
        else:
            refund["amount"] = returned_amount
        return refund

    paypal.refund_capture.side_effect = altered_response
    workflow.approve(case_id)
    case = workflow.db.get_case(case_id)
    assert case["status"] == "REFUND_AMOUNT_REVIEW"
    assert case["refund_status"] == "COMPLETED" and case["refund_id"]
    assert (case.get("note") or {}).get("outcome") != "COMPLETED_NOTE"
    assert result_card(workflow.db, case)["kind"] == "warn"
    assert next(s for s in pipeline(workflow.db, case) if s["key"] == "paypal")["state"] == "waiting"
    assert next(e for e in evidence_a(workflow.db, case) if e["label"] == "Refund")["ok"] is False
    assert next(e for e in evidence_summary(workflow.db, case) if e["label"] == "PayPal refund")["ok"] is None
    assert paypal_proves(workflow.db, case)["refund"]["ok"] is None
    assert _next_step(case)[0] == "needs_you"
    assert workflow.db.verify_chain(case_id)["ok"]
    workflow.execute_refund(case_id)  # existing PayPal ID, no second money-moving call
    assert paypal.refund_capture.call_count == 1

    # A fresh PayPal GET with the exact amount can resolve the review without another refund call.
    result = workflow.reconcile(case_id)
    assert result["ok"] and result["advanced"]
    case = workflow.db.get_case(case_id)
    assert case["status"] == "REFUND_COMPLETED"
    assert case["note"]["outcome"] == "COMPLETED_NOTE"
    assert paypal.refund_capture.call_count == 1
    assert workflow.db.verify_chain(case_id)["ok"]


def test_pending_refund_with_wrong_completed_amount_stays_under_review(settings):
    db = Database(settings.db_path)
    db.init(reset=True)
    pp = MockPayPalClient(refund_status="PENDING")
    wf = Workflow(db, settings, KeywordIntentExtractor(), paypal=pp)
    wf.seed_demo()
    case_id = wf.run_scenario("A")
    wf.approve(case_id)
    refund_id = db.get_case(case_id)["refund_id"]
    pp.complete_refund(refund_id)
    refund = next(r for r in pp.refunds_by_request.values() if r["id"] == refund_id)
    refund["amount"] = {"value": "5.00", "currency_code": "USD"}
    result = wf.reconcile(case_id)
    assert not result["ok"] and not result["advanced"]
    assert db.get_case(case_id)["status"] == "REFUND_AMOUNT_REVIEW"
    assert (db.get_case(case_id).get("note") or {}).get("outcome") != "COMPLETED_NOTE"


def test_status_only_webhook_cannot_clear_wrong_amount_review(workflow, paypal):
    case_id = workflow.run_scenario("A")
    original = paypal._mock_wraps.refund_capture

    def altered_response(*args, **kwargs):
        refund = original(*args, **kwargs)
        refund["amount"] = {"value": "5.00", "currency_code": "USD"}
        return refund

    paypal.refund_capture.side_effect = altered_response
    workflow.approve(case_id)
    refund_id = workflow.db.get_case(case_id)["refund_id"]
    workflow.record_webhook({"id": "WH-AMOUNT-REVIEW", "event_type": "PAYMENT.CAPTURE.REFUNDED",
                             "resource": {"id": refund_id, "status": "COMPLETED"}}, "SUCCESS")
    case = workflow.db.get_case(case_id)
    assert case["status"] == "REFUND_AMOUNT_REVIEW"
    assert case["webhook_status"] == "VERIFIED"
    assert (case.get("note") or {}).get("outcome") != "COMPLETED_NOTE"
    assert workflow.db.verify_chain(case_id)["ok"]


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
