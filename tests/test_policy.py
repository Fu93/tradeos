from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.intent import IntentResult
from app.policy import PolicyInput, evaluate

TODAY = date(2026, 10, 8)
EXCHANGE = IntentResult(intent="EXCHANGE_REQUEST", reason="SIZE_MISMATCH", requested_action="EXCHANGE")


def make(**over):
    base = dict(
        capture_status="COMPLETED", captured_amount=Decimal("49.99"), capture_currency="USD",
        expected_currency="USD", requested_refund=Decimal("49.99"), already_refunded=Decimal("0"),
        purchase_date=TODAY, today=TODAY, return_window_days=30, product_returnable=True,
        product_name="Trail Runner", intent=EXCHANGE, supplier_status="REPLACEMENT_APPROVED",
        require_supplier=True,
    )
    base.update(over)
    return PolicyInput(**base)


def failed(result):
    return {c.name for c in result.checks if not c.passed}


def test_case_a_is_eligible():
    r = evaluate(make())
    assert r.decision == "ELIGIBLE"
    assert r.reasons == []


def test_case_b_45_days_is_rejected_for_return_window():
    r = evaluate(make(purchase_date=TODAY - timedelta(days=45)))
    assert r.decision == "REJECTED"
    assert failed(r) == {"return_window"}
    assert "45 days" in r.reasons[0] and "exceeded" in r.reasons[0]


@pytest.mark.parametrize("days,decision", [(0, "ELIGIBLE"), (30, "ELIGIBLE"), (31, "REJECTED"), (-1, "REJECTED")])
def test_return_window_boundaries(days, decision):
    assert evaluate(make(purchase_date=TODAY - timedelta(days=days))).decision == decision


@pytest.mark.parametrize("status", [None, "PENDING", "DECLINED", "REFUNDED", "PARTIALLY_REFUNDED"])
def test_capture_must_be_completed(status):
    r = evaluate(make(capture_status=status))
    assert r.decision == "REJECTED" and "payment_captured" in failed(r)


def test_product_not_eligible():
    assert failed(evaluate(make(product_returnable=False))) == {"product_eligible"}


@pytest.mark.parametrize("over", [
    {"requested_refund": Decimal("50.00")},
    {"already_refunded": Decimal("10.00")},
    {"capture_currency": "EUR"},
    {"captured_amount": None},
    {"requested_refund": Decimal("0")},
])
def test_refundable_amount(over):
    assert "refundable_amount" in failed(evaluate(make(**over)))


def test_supplier_confirmation_required_in_final_stage():
    assert failed(evaluate(make(supplier_status=None))) == {"supplier_confirmed"}
    pre = evaluate(make(supplier_status=None, require_supplier=False))
    assert pre.decision == "ELIGIBLE" and pre.stage == "pre-supplier"


@pytest.mark.parametrize("intent", [
    IntentResult(intent="UNKNOWN", reason="UNKNOWN", requested_action="UNKNOWN"),
    IntentResult(intent="REFUND_REQUEST", reason="CHANGED_MIND", requested_action="REFUND"),
    IntentResult(intent="ORDER_STATUS", reason="OTHER", requested_action="INFO"),
])
def test_unsupported_or_unknown_intent_is_rejected(intent):
    assert "request_supported" in failed(evaluate(make(intent=intent)))


def test_no_ai_output_can_override_a_no():
    """Whatever the model says, an out-of-window purchase stays REJECTED."""
    from typing import get_args

    from app.intent import Intent, Reason, RequestedAction

    for i in get_args(Intent):
        for reason in get_args(Reason):
            for action in get_args(RequestedAction):
                r = evaluate(make(intent=IntentResult(intent=i, reason=reason, requested_action=action),
                                  purchase_date=TODAY - timedelta(days=45)))
                assert r.decision == "REJECTED"
