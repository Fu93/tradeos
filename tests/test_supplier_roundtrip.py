from app.supplier import route_for_reason
from app.workflow import RefundNotAllowed


def test_route_table_only_size_mismatch_asks_supplier():
    assert route_for_reason("SIZE_MISMATCH") == "SUPPLIER_REQUIRED"
    for reason in ("DAMAGED", "WRONG_ITEM", "NOT_AS_DESCRIBED", "CHANGED_MIND", "OTHER", "UNKNOWN", None):
        assert route_for_reason(reason) == "HUMAN"


def test_supplier_round_trip_decline_cannot_refund(workflow, paypal):
    case_id = workflow.run_scenario("S")
    case = workflow.db.get_case(case_id)
    assert case["status"] == "AWAITING_SUPPLIER"
    assert case["supplier_reply"] is None
    assert "尚未寄出" in case["supplier_draft"]
    assert "請確認能否補寄此尺寸（42 → 43）" in case["supplier_draft"]
    assert "Replacement request" in case["supplier_draft"]
    try:
        workflow.approve(case_id)
        raise AssertionError("approve should be refused before a supplier reply")
    except RefundNotAllowed:
        pass
    paypal.refund_capture.assert_not_called()

    workflow.supplier_reply(case_id, "decline")
    case = workflow.db.get_case(case_id)
    assert case["status"] == "REJECTED"
    assert case["supplier_reply"] == "REPLACEMENT_DECLINED"
    assert case["decision"] == "REJECTED"
    paypal.refund_capture.assert_not_called()
    try:
        workflow.approve(case_id)
        raise AssertionError("approve should stay refused after a decline")
    except RefundNotAllowed:
        pass


def test_supplier_round_trip_agree_still_needs_a_human(workflow, paypal):
    case_id = workflow.run_scenario("S")
    workflow.supplier_reply(case_id, "approve")
    case = workflow.db.get_case(case_id)
    assert case["status"] == "PENDING_APPROVAL"
    assert case["supplier_reply"] == "REPLACEMENT_APPROVED"
    paypal.refund_capture.assert_not_called()
    workflow.approve(case_id)
    case = workflow.db.get_case(case_id)
    assert case["status"] == "REFUND_COMPLETED"
    paypal.refund_capture.assert_called_once()


def test_non_size_reason_does_not_open_supplier(workflow, paypal):
    case_id = workflow.new_case("S", message="I was charged twice. Please refund the duplicate.")
    workflow.process(case_id)
    case = workflow.db.get_case(case_id)
    assert case["status"] == "REJECTED"
    assert case["supplier_draft"] is None
    assert case["supplier_reply"] is None
    paypal.refund_capture.assert_not_called()
    try:
        workflow.approve(case_id)
        raise AssertionError("non-size route must not be approvable")
    except RefundNotAllowed:
        pass


def test_case_a_still_auto_replies(workflow):
    case_id = workflow.run_scenario("A")
    case = workflow.db.get_case(case_id)
    assert case["status"] == "PENDING_APPROVAL"
    assert case["supplier_reply"] == "REPLACEMENT_APPROVED"
