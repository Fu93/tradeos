"""Autonomy decision for the post-purchase agent.

After the deterministic policy returns ELIGIBLE, this module decides whether
the case can be auto-approved (within merchant-configured limits) or must be
escalated to a human.

AI never decides money. This module only reads the policy result and the
merchant's settings:

* it cannot turn a REJECTED case into an approved one (a REJECTED policy is
  reported as BLOCK and the caller must not automate it),
* it cannot call PayPal — an AUTO decision only skips the "a person clicks
  Approve" step, and the refund still has to pass the same hard guard in
  ``Workflow._guard_refund`` as a human-approved one.

Because the decision is recorded on the case's hash chain (``approval_source``),
the audit says which of the two it was; nothing here writes "human" on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from .policy import PolicyResult

AutonomyDecision = Literal["AUTO", "HUMAN", "BLOCK"]


@dataclass(frozen=True)
class AutonomyResult:
    decision: AutonomyDecision
    reason: str


def decide_detailed(
    policy: PolicyResult,
    *,
    amount: Decimal,
    auto_enabled: bool,
    auto_refund_max_amount: Decimal,
    auto_exchange_enabled: bool,
    injection_suspected: bool,
    intent_is_unknown: bool,
    action: str | None,
) -> AutonomyResult:
    """The decision plus the reason a person can read in the audit timeline."""
    if not policy.eligible:
        return AutonomyResult("BLOCK", f"the policy decision is {policy.decision}; a rejected case is never automated")
    if not auto_enabled:
        return AutonomyResult("HUMAN", "AUTO_ENABLED is off — every refund needs a person")
    if injection_suspected:
        return AutonomyResult("HUMAN", "the message contains instruction-like text (heuristic check); a person reads it")
    if intent_is_unknown:
        return AutonomyResult("HUMAN", "the request could not be understood")
    if action == "REFUND":
        if amount > auto_refund_max_amount:
            return AutonomyResult("HUMAN", f"{amount} is above the automatic refund limit "
                                           f"{auto_refund_max_amount}")
        return AutonomyResult("AUTO", f"{amount} is within the automatic refund limit {auto_refund_max_amount}")
    if action == "EXCHANGE":
        if not auto_exchange_enabled:
            return AutonomyResult("HUMAN", "AUTO_EXCHANGE_ENABLED is off")
        return AutonomyResult("AUTO", "an exchange within the merchant's limits (no money moves)")
    return AutonomyResult("HUMAN", f"unsupported action {action!r}")


def decide(
    policy: PolicyResult,
    *,
    amount: Decimal,
    auto_enabled: bool,
    auto_refund_max_amount: Decimal,
    auto_exchange_enabled: bool,
    injection_suspected: bool,
    intent_is_unknown: bool,
    action: str | None,
) -> AutonomyDecision:
    """Return AUTO / HUMAN / BLOCK.

    BLOCK is only for explicit policy rejection (already handled upstream).
    This function is called only on ELIGIBLE cases.
    """
    return decide_detailed(
        policy,
        amount=amount,
        auto_enabled=auto_enabled,
        auto_refund_max_amount=auto_refund_max_amount,
        auto_exchange_enabled=auto_exchange_enabled,
        injection_suspected=injection_suspected,
        intent_is_unknown=intent_is_unknown,
        action=action,
    ).decision
