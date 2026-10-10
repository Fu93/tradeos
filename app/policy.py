"""Deterministic policy engine. Pure Python, no I/O, no AI.

"Use AI where language is ambiguous. Use code where money is at stake."

The intent produced by the AI is only one input. It can turn a case into a NO
(unsupported or UNKNOWN request), but it can never turn a NO into a YES: every
other check is computed from PayPal data and the merchant's own records.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

from .intent import IntentResult

Decision = Literal["ELIGIBLE", "REJECTED"]

# Two automated paths (and only these):
#   return for a refund -> REFUND  (policy -> human approval -> PayPal refund)
#   size exchange       -> EXCHANGE (supplier replacement, human approval, NO refund; Refund API never called)
SUPPORTED_INTENTS = {("REFUND_REQUEST", "REFUND"): "REFUND", ("EXCHANGE_REQUEST", "EXCHANGE"): "EXCHANGE"}
# A refund needs a stated reason; OTHER / UNKNOWN goes to a human.
REFUND_REASONS = {"SIZE_MISMATCH", "DAMAGED", "WRONG_ITEM", "NOT_AS_DESCRIBED", "CHANGED_MIND"}
REPLACEMENT_APPROVED = "REPLACEMENT_APPROVED"


def action_for(intent: IntentResult) -> str | None:
    """REFUND / EXCHANGE for a supported request, else None."""
    return SUPPORTED_INTENTS.get((intent.intent, intent.requested_action))


@dataclass(frozen=True)
class PolicyInput:
    capture_status: str | None  # from PayPal GET /v2/payments/captures/{id}
    captured_amount: Decimal | None  # from PayPal capture
    capture_currency: str | None
    expected_currency: str
    requested_refund: Decimal
    already_refunded: Decimal
    purchase_date: date
    today: date
    return_window_days: int
    product_returnable: bool
    product_name: str
    intent: IntentResult
    supplier_status: str | None = None
    require_supplier: bool = True
    injection_suspected: bool = False  # heuristic pattern check on the raw message (code, not AI)


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class PolicyResult:
    decision: Decision
    checks: list[Check] = field(default_factory=list)
    stage: str = "final"
    action: str | None = None  # REFUND / EXCHANGE

    @property
    def reasons(self) -> list[str]:
        return [c.detail for c in self.checks if not c.passed]

    @property
    def eligible(self) -> bool:
        return self.decision == "ELIGIBLE"

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "stage": self.stage,
            "action": self.action,
            "checks": [asdict(c) for c in self.checks],
            "reasons": self.reasons,
        }


def evaluate(inp: PolicyInput) -> PolicyResult:
    checks: list[Check] = []
    action = action_for(inp.intent)

    # 1. Request understood and supported by this automated workflow (return-for-refund or exchange).
    supported = action is not None and (action != "REFUND" or inp.intent.reason in REFUND_REASONS)
    why = ""
    if action is None:
        why = " — not supported by the automated workflow; route to a human"
    elif not supported:
        why = " — a refund needs a stated reason (size, damaged, wrong item, not as described, changed mind)"
    checks.append(Check("request_supported", supported,
                        f"Request understood as {inp.intent.intent} / {inp.intent.requested_action}"
                        f" (reason {inp.intent.reason})" + why))

    # 1b. Heuristic injection markers in the message: never automated, a human reads it.
    if inp.injection_suspected:
        checks.append(Check("no_injection_markers", False,
                            "Message contains instruction-like text (heuristic check) — sent to a human"))

    # 2. Payment really captured (PayPal is the source of truth).
    paid = inp.capture_status == "COMPLETED"
    checks.append(
        Check(
            "payment_captured",
            paid,
            f"PayPal capture status is {inp.capture_status or 'missing'}"
            + ("" if paid else " (must be COMPLETED)"),
        )
    )

    # 3. Return window (applies to returns and exchanges).
    days = (inp.today - inp.purchase_date).days
    in_window = 0 <= days <= inp.return_window_days
    checks.append(
        Check(
            "return_window",
            in_window,
            f"Purchased {days} days ago; window is {inp.return_window_days} days"
            + ("" if in_window else " — return window exceeded"),
        )
    )

    # 4. Product eligibility.
    what = "exchange" if action == "EXCHANGE" else "return"
    checks.append(
        Check(
            "product_eligible",
            inp.product_returnable,
            f"{inp.product_name} is " + (f"eligible for {what}" if inp.product_returnable else "final sale / not eligible"),
        )
    )

    stage = "final"
    if action == "EXCHANGE":
        # 5x. Exchange: no money moves. Only the supplier must confirm a replacement (once contacted).
        stage = "pre-supplier"
        if inp.require_supplier:
            stage = "final"
            ok = inp.supplier_status == REPLACEMENT_APPROVED
            checks.append(Check("supplier_confirmed", ok, f"Supplier status: {inp.supplier_status or 'none'}"
                                + ("" if ok else " (needs REPLACEMENT_APPROVED)")))
    else:
        # 5. Refundable amount (computed from PayPal capture amount). No supplier step for a refund.
        captured = inp.captured_amount or Decimal("0")
        refundable = captured - inp.already_refunded
        currency_ok = inp.capture_currency == inp.expected_currency
        amount_ok = currency_ok and Decimal("0") < inp.requested_refund <= refundable
        checks.append(
            Check(
                "refundable_amount",
                amount_ok,
                f"Requested {inp.requested_refund} {inp.expected_currency}; refundable "
                f"{refundable} {inp.capture_currency or '?'}"
                + ("" if amount_ok else " — amount or currency not refundable"),
            )
        )

    decision: Decision = "ELIGIBLE" if all(c.passed for c in checks) else "REJECTED"
    return PolicyResult(decision=decision, checks=checks, stage=stage, action=action)
