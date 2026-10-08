from decimal import Decimal

from app.config import CostAssumptions
from app.economics import LABEL, case_economics


def test_plan_numbers():
    e = case_economics("49.99", CostAssumptions())
    assert LABEL == "Illustrative cost model — assumptions configurable."
    assert (e["labour"], e["ai"], e["review"], e["tradeos"], e["saving"]) == (
        Decimal("2.67"), Decimal("0.06"), Decimal("0.33"), Decimal("0.39"), Decimal("2.28"))
    assert e["rows"][0] == ("Order / refund", "$49.99 USD")
    assert e["rows"][1][1] == "8 min × $20/hour = $2.67"


def test_assumptions_are_configurable():
    e = case_economics("49.99", CostAssumptions(human_minutes_per_case=Decimal("12"), human_hourly_rate_usd=Decimal("30")))
    assert e["labour"] == Decimal("6.00")
