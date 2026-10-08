"""Illustrative case economics (plan §6). Assumptions are configurable; nothing here is measured."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .config import CostAssumptions

LABEL = "Illustrative cost model — assumptions configurable."
CENT = Decimal("0.01")


def _money(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def _num(x: Decimal) -> str:
    return format(x.normalize(), "f")


def case_economics(order_amount: str, a: CostAssumptions) -> dict:
    per_minute = a.human_hourly_rate_usd / Decimal(60)
    labour = _money(a.human_minutes_per_case * per_minute)
    review = _money(a.human_review_minutes * per_minute)
    ai = _money(a.ai_api_cost_per_case_usd)
    tradeos = ai + review
    saving = labour - tradeos
    rows = [
        ("Order / refund", f"${Decimal(order_amount):.2f} USD"),
        ("Human labour estimate",
         f"{_num(a.human_minutes_per_case)} min × ${_num(a.human_hourly_rate_usd)}/hour = ${labour}"),
        ("AI / API cost", f"${ai}"),
        ("Human review", f"{_num(a.human_review_minutes)} min = ${review}"),
        ("TradeOS estimated cost", f"${tradeos}"),
        ("Estimated saving", f"${saving}"),
    ]
    return {
        "label": LABEL,
        "rows": rows,
        "labour": labour,
        "review": review,
        "ai": ai,
        "tradeos": tradeos,
        "saving": saving,
    }
