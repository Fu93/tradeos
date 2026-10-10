"""Autonomy decision for the post-purchase agent.

After the deterministic policy returns ELIGIBLE, this module decides whether
the case can be auto-approved (within merchant-configured limits) or must be
escalated to a human.

AI never decides money. This only reads the policy result + settings.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from .policy import PolicyResult

AutonomyDecision = Literal["AUTO", "HUMAN", "BLOCK"]


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
    if not auto_enabled:
        return "HUMAN"
    if injection_suspected or intent_is_unknown:
        return "HUMAN"
    if action == "REFUND":
        if amount > auto_refund_max_amount:
            return "HUMAN"
        return "AUTO"
    if action == "EXCHANGE":
        return "AUTO" if auto_exchange_enabled else "HUMAN"
    return "HUMAN"
