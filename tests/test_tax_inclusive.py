"""VAT-inclusive (tax-inclusive) prices on a mixed order: refund amounts are already correct, the VAT split is not shown.

The PayPal-recommended way to send a VAT-inclusive shop's order is the GROSS price as `unit_amount` and no item tax
(only tax that is NOT already in the price goes into `tax_total`; sending the included VAT again would count it twice).
TradeOS refunds `unit * qty + tax_unit * qty (+ shipping share)` in integer minor units, so for such an order every
refund is gross price x returned units: the VAT is refunded inside the amount, at the rate of the original sale.
What TradeOS does NOT do: show the VAT part on the approval screen or in the ledger (see docs/partial-refunds.md).
The `vat_inside` helper below exists only in this test file, as the worked example's arithmetic; the app has no such code.

Pure code + mock PayPal only. Not live Sandbox proof.
"""
from decimal import ROUND_HALF_UP, Decimal

import pytest

from app import lineitems as li
from app import mixed as mx
from app.config import Settings
from tests.helpers import make_wf

VAT_RATE = Decimal("0.20")  # UK standard rate; VAT fraction of a gross price = rate / (1 + rate) = 1/6


def gbp(value: str) -> int:
    return li.to_minor(value, "GBP")


# Gross (VAT-inclusive) prices, no item tax: how a UK shop with VAT-inclusive prices sends the order to PayPal.
GROSS_ORDER = li.OrderModel("GBP", (
    li.Line(1, "UK-TRAINER-42", "Trainers, EU 42", gbp("49.99"), 1, 0),
    li.Line(2, "UK-JACKET-M", "Rain jacket, M", gbp("79.00"), 1, 0),
    li.Line(3, "UK-SOCKS", "Wool socks", gbp("6.00"), 3, 0),
    li.Line(4, "UK-TEE-M", "T-shirt, M", gbp("24.00"), 1, 0),
), gbp("4.99"))  # shipping, also VAT-inclusive


def vat_inside(gross_minor: int, rate: Decimal = VAT_RATE) -> int:
    """VAT contained in a gross amount (test-only arithmetic for the worked example; rounded once, half up)."""
    return int((Decimal(gross_minor) * rate / (1 + rate)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(line_no, resolution, qty, reason="SIZE_MISMATCH"):
    return li.LineDecision(line_no, resolution, qty, reason, "test")


def test_gross_prices_go_to_paypal_without_item_tax_and_the_breakdown_adds_up():
    body = GROSS_ORDER.to_paypal()
    assert all("tax" not in it for it in body["items"])           # no per-item tax: VAT is inside unit_amount
    assert "tax_total" not in body["breakdown"]                     # nothing counted twice
    assert body["breakdown"]["item_total"]["value"] == "170.99"     # 49.99 + 79.00 + 3 x 6.00 + 24.00
    assert body["breakdown"]["shipping"]["value"] == "4.99"
    assert body["total"]["value"] == "175.98" == li.to_str(GROSS_ORDER.item_total + GROSS_ORDER.shipping_minor, "GBP")


def test_worked_example_refund_is_gross_times_returned_units_and_contains_the_original_vat():
    # Trainers returned (wrong size), 1 of 3 socks returned (changed mind), T-shirt exchanged, jacket still open.
    q = li.quote_batch(GROSS_ORDER, [dec(1, "REFUND", 1), dec(2, "NEEDS_HUMAN", 1), dec(3, "REFUND", 1, "CHANGED_MIND"),
                                     dec(4, "EXCHANGE", 1)], li.Ledger(), shipping_policy="NEVER")
    assert [(r.line_no, r.qty, r.item_minor, r.tax_minor) for r in q.refund_lines] == [(1, 1, 4999, 0), (3, 1, 600, 0)]
    assert q.total_minor == gbp("55.99")                            # 49.99 + 1 x 6.00: the price the customer paid
    assert q.exchange_lines == ((4, 1),)
    # The VAT inside the refund (shown here, NOT by the app): 49.99 -> 8.33, 6.00 -> 1.00; 9.33 in total.
    assert vat_inside(4999) == 833 and vat_inside(600) == 100
    assert vat_inside(q.total_minor) == 933 == vat_inside(4999) + vat_inside(600)
    assert q.remaining_after_minor == GROSS_ORDER.total - gbp("55.99")


def test_default_policy_merchant_error_refund_adds_a_gross_shipping_share():
    # Damaged trainers (merchant error, fully returned) release their share of the VAT-inclusive shipping.
    q = li.quote_batch(GROSS_ORDER, [dec(1, "REFUND", 1, "DAMAGED")], li.Ledger())
    share = GROSS_ORDER.shipping_shares()[1]
    assert share == 146                                             # 4.99 by item value: 1.46 for the trainers
    assert q.total_minor == 4999 + 146 == gbp("51.45")


def test_full_return_over_several_batches_refunds_exactly_the_capture_no_penny_drift():
    order, ledger, total = GROSS_ORDER, li.Ledger(), 0
    plan = [[dec(3, "REFUND", 1, "CHANGED_MIND")], [dec(1, "REFUND", 1, "CHANGED_MIND"), dec(3, "REFUND", 2, "CHANGED_MIND")],
            [dec(2, "REFUND", 1, "CHANGED_MIND"), dec(4, "REFUND", 1, "CHANGED_MIND")]]
    refund_qty: dict[int, int] = {}
    shipped: set[int] = set()
    for decisions in plan:
        # decisions carry the CUMULATIVE units per line, as stored decisions do
        cum = [dec(d.line_no, d.resolution, refund_qty.get(d.line_no, 0) + d.qty, d.reason) for d in decisions]
        q = li.quote_batch(order, cum, ledger)
        total += q.total_minor
        for r in q.refund_lines:
            refund_qty[r.line_no] = refund_qty.get(r.line_no, 0) + r.qty
            if r.shipping_minor:
                shipped.add(r.line_no)
        ledger = li.Ledger(refund_qty=dict(refund_qty), shipping_released=frozenset(shipped), refunded_minor=total)
    # Withdrawal from the whole order: every unit back, so the VAT-inclusive shipping is released too.
    assert total == order.total == gbp("175.98")
    assert ledger.refunded_minor == order.total
    with pytest.raises(li.OverRefund):
        li.quote_batch(order, [dec(1, "REFUND", 1)], li.Ledger(refunded_minor=order.total))


@pytest.mark.parametrize("gross", ["49.99", "79.00", "6.00", "24.00", "0.01", "0.05", "9.99", "1234.57"])
def test_net_plus_per_unit_vat_representation_refunds_the_same_gross_amount(gross):
    """A shop that back-calculates net + VAT per unit (tax = gross - net, so they always add back up) gets the same
    refund as one that sends the gross price; drift would only come from a split that does not add back up."""
    g = gbp(gross)
    net = int((Decimal(g) / (1 + VAT_RATE)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    split = li.OrderModel("GBP", (li.Line(1, "X", "x", net, 3, g - net),))
    whole = li.OrderModel("GBP", (li.Line(1, "X", "x", g, 3, 0),))
    for qty in (1, 2, 3):
        a = li.quote_batch(split, [dec(1, "REFUND", qty)], li.Ledger(), shipping_policy="NEVER")
        b = li.quote_batch(whole, [dec(1, "REFUND", qty)], li.Ledger(), shipping_policy="NEVER")
        assert a.total_minor == b.total_minor == g * qty


def test_vat_inclusive_gbp_mixed_order_end_to_end_on_mock_paypal(settings, monkeypatch):
    monkeypatch.setattr(mx, "demo_order", lambda currency, shipping_policy=None: GROSS_ORDER)
    monkeypatch.setattr(mx, "DEMO_PROPOSALS", [
        {"line_no": 1, "action": "RETURN", "reason": "DAMAGED"},
        {"line_no": 2, "action": "UNKNOWN", "reason": "UNKNOWN"},
        {"line_no": 3, "action": "RETURN", "reason": "CHANGED_MIND", "qty": 1},
        {"line_no": 4, "action": "EXCHANGE", "reason": "SIZE_MISMATCH"},
    ])
    wf, pp = make_wf(Settings(db_path=settings.db_path, currency="GBP"))
    cid = wf.run_scenario("M")
    assert wf.db.get_case(cid)["amount"] == "175.98"                # what PayPal captured: gross prices + shipping
    b = wf.db.get_batch(f"{cid}-B1")
    assert [(r["line_no"], r["qty"], r["tax_minor"]) for r in b["quote"]["refund_lines"]] == [(1, 1, 0), (3, 1, 0)]
    assert b["amount_minor"] == 4999 + 146 + 600                    # trainers + their shipping share + one pair of socks
    assert not [c for c in pp.method_calls if c[0] == "refund_capture"]   # nothing before a person approves
    wf.mixed.approve_batch(cid, b["id"], li.to_str(b["amount_minor"], "GBP"), b["items_hash"])
    calls = [c for c in pp.method_calls if c[0] == "refund_capture"]
    assert len(calls) == 1 and calls[0].kwargs["amount"] == {"currency_code": "GBP", "value": "57.45"}
    assert wf.db.get_batch(f"{cid}-B1")["status"] == "COMPLETED"
