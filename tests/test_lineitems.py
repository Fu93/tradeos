"""Money math for mixed orders: property-style fuzz (seeded stdlib random: no new dependency), edge cases, and the
'AI never sets an amount' rule. Everything here is pure code: no PayPal, no DB."""
import random
from datetime import date, timedelta

import pytest

from app import lineitems as li

TODAY = date(2026, 10, 18)
CURRENCIES = sorted(li.SUPPORTED_CURRENCIES)


def rand_order(rng, currency=None, max_lines=6):
    cur = currency or rng.choice(CURRENCIES)
    big = 10 ** 6 if li.exponent(cur) == 0 else 10 ** 5
    lines = tuple(li.Line(i + 1, f"SKU{i}", f"Item {i}", rng.randint(0, big), rng.randint(1, 4),
                          rng.randint(0, big // 10), rng.random() < 0.9) for i in range(rng.randint(1, max_lines)))
    return li.OrderModel(cur, lines, rng.randint(0, big // 5))


def rand_decisions(rng, order):
    out = []
    for ln in order.lines:
        res = rng.choice(["REFUND", "REFUND", "EXCHANGE", "REJECT", "NEEDS_HUMAN"])
        reason = rng.choice(sorted(li.REFUND_REASONS))
        out.append(li.LineDecision(ln.line_no, res, rng.randint(1, ln.qty), reason, "x"))
    return out


# ----------------------------------------------------------------------------------------------- currency
@pytest.mark.parametrize("cur,exp", [("USD", 2), ("EUR", 2), ("GBP", 2), ("JPY", 0), ("HUF", 0), ("TWD", 0)])
def test_exponents_follow_paypal_table(cur, exp):
    assert li.exponent(cur) == exp


@pytest.mark.parametrize("cur", ["BHD", "KWD", "XXX", "", "usd"])
def test_unknown_currency_fails_closed(cur):
    with pytest.raises(li.MoneyError):
        li.exponent(cur)


@pytest.mark.parametrize("value,cur,minor", [("49.99", "USD", 4999), ("0", "USD", 0), ("1500", "JPY", 1500),
                                              ("10", "USD", 1000), ("10.5", "USD", 1050), ("0.01", "EUR", 1)])
def test_to_minor_exact(value, cur, minor):
    assert li.to_minor(value, cur) == minor
    assert li.to_minor(li.to_str(minor, cur), cur) == minor


@pytest.mark.parametrize("value,cur", [("1500.5", "JPY"), ("1500.00", "JPY"), ("1.005", "USD"), ("-1", "USD"), ("",
                                                                                                                "USD"),
                                       ("1e3", "USD"), ("NaN", "USD"), ("Infinity", "USD"), ("1,00", "USD"),
                                       ("1..0", "USD"), (True, "USD"), ("0x10", "USD")])
def test_to_minor_rejects_inexact_or_malformed(value, cur):
    with pytest.raises(li.MoneyError):
        li.to_minor(value, cur)


def test_jpy_has_no_decimal_point_in_output():
    assert li.to_str(12345, "JPY") == "12345" and li.to_str(5, "USD") == "0.05"


def test_roundtrip_all_currencies_fuzz():
    rng = random.Random(1)
    for _ in range(2000):
        cur = rng.choice(CURRENCIES)
        minor = rng.randint(0, 10 ** 9)
        assert li.to_minor(li.to_str(minor, cur), cur) == minor


# ----------------------------------------------------------------------------------------------- allocation
def test_allocate_sums_exactly_fuzz():
    rng = random.Random(2)
    for _ in range(3000):
        weights = [rng.randint(0, 10 ** 6) for _ in range(rng.randint(1, 8))]
        total = rng.randint(0, 10 ** 7)
        shares = li.allocate(total, weights)
        assert sum(shares) == total and all(s >= 0 for s in shares) and len(shares) == len(weights)
        if sum(weights):  # a share never differs from the exact proportion by a whole unit
            for s, w in zip(shares, weights):
                assert abs(s - total * w / sum(weights)) < 1


def test_allocate_edge_cases():
    assert li.allocate(0, []) == []
    assert li.allocate(5, [0, 0]) == [5, 0]
    assert li.allocate(100, [1, 1, 1]) == [34, 33, 33]  # tie -> earliest position
    with pytest.raises(li.MoneyError):
        li.allocate(5, [])
    with pytest.raises(li.MoneyError):
        li.allocate(-1, [1])


# ----------------------------------------------------------------------------------------------- quote invariants
def test_fuzz_sum_of_refunds_plus_remaining_equals_capture_and_never_overrefunds():
    rng = random.Random(3)
    for _ in range(1500):
        order = rand_order(rng)
        decisions = rand_decisions(rng, order)
        policy = rng.choice(li.SHIPPING_POLICIES)
        try:
            q = li.quote_batch(order, decisions, li.Ledger(), shipping_policy=policy)
        except li.OverRefund:
            pytest.fail("a fresh ledger can never over-refund: the lines sum to the capture")
        assert q.total_minor + q.remaining_after_minor == order.total          # sum of refunds + remaining == capture
        assert 0 <= q.total_minor <= order.total                                # no over-refund
        assert q.total_minor == sum(x.item_minor + x.tax_minor + x.shipping_minor for x in q.refund_lines)
        for x in q.refund_lines:                                                # only from the order's own prices
            ln = order.line(x.line_no)
            assert x.item_minor == ln.unit_minor * x.qty and x.tax_minor == ln.tax_unit_minor * x.qty
            assert x.shipping_minor <= order.shipping_minor
        assert sum(x.shipping_minor for x in q.refund_lines) <= order.shipping_minor
        assert li.to_minor(li.to_str(q.total_minor, order.currency), order.currency) == q.total_minor


def test_fuzz_multiple_partials_never_exceed_capture_and_never_repeat_a_unit():
    rng = random.Random(4)
    for _ in range(600):
        order = rand_order(rng)
        decisions = rand_decisions(rng, order)
        refund_qty, exch_qty, released, committed = {}, {}, set(), 0
        for _batch in range(rng.randint(2, 5)):
            led = li.Ledger(dict(refund_qty), dict(exch_qty), frozenset(released), committed)
            q = li.quote_batch(order, decisions, led, shipping_policy="MERCHANT_ERROR")
            committed += q.total_minor
            assert committed <= order.total
            for x in q.refund_lines:
                refund_qty[x.line_no] = refund_qty.get(x.line_no, 0) + x.qty
                if x.shipping_minor:
                    assert x.line_no not in released  # shipping share is released once per line
                    released.add(x.line_no)
            for n, qty in q.exchange_lines:
                exch_qty[n] = exch_qty.get(n, 0) + qty
            for ln in order.lines:
                assert refund_qty.get(ln.line_no, 0) + exch_qty.get(ln.line_no, 0) <= ln.qty
        again = li.quote_batch(order, decisions, li.Ledger(dict(refund_qty), dict(exch_qty), frozenset(released),
                                                           committed))
        assert again.total_minor == 0  # nothing left to refund twice (second identical batch is empty)


def test_overrefund_attempts_raise():
    order = li.OrderModel("USD", (li.Line(1, "A", "A", 1000, 1, 100),), 500)
    d = [li.LineDecision(1, "REFUND", 1, "DAMAGED", "x")]
    with pytest.raises(li.OverRefund):
        li.quote_batch(order, d, li.Ledger(refunded_minor=order.total - 1))   # only 1 minor unit left
    with pytest.raises(li.OverRefund):
        li.quote_batch(order, d, li.Ledger(refunded_minor=order.total))        # nothing left
    ok = li.quote_batch(order, d, li.Ledger())
    assert ok.total_minor == 1000 + 100 + 500 and ok.remaining_after_minor == 0


def test_capture_must_equal_the_order_lines_total():
    order = li.OrderModel("USD", (li.Line(1, "A", "A", 1000, 1),), 0)
    with pytest.raises(li.MoneyError):
        li.quote_batch(order, [], li.Ledger(), capture_minor=1001)


def test_unknown_shipping_policy_fails_closed():
    order = li.OrderModel("USD", (li.Line(1, "A", "A", 1000, 1),), 0)
    with pytest.raises(li.MoneyError):
        li.quote_batch(order, [], li.Ledger(), shipping_policy="ALWAYS")


# ----------------------------------------------------------------------------------------------- shipping + tax rule
def mixed_demo():
    from app.mixed import demo_order
    return demo_order("USD")


def test_demo_order_numbers_and_paypal_shape():
    o = mixed_demo()
    assert (o.item_total, o.tax_total, o.shipping_minor, o.total) == (17149, 1372, 600, 19121)
    pp = o.to_paypal()
    assert pp["total"]["value"] == "191.21" and pp["breakdown"]["item_total"]["value"] == "171.49"
    assert pp["breakdown"]["tax_total"]["value"] == "13.72" and pp["breakdown"]["shipping"]["value"] == "6.00"
    assert all(i["quantity"] == "1" and i["unit_amount"]["currency_code"] == "USD" for i in pp["items"])


def decisions_demo():
    return [li.LineDecision(1, "REFUND", 1, "DAMAGED", ""), li.LineDecision(2, "REFUND", 1, "CHANGED_MIND", ""),
            li.LineDecision(3, "REFUND", 1, "NOT_AS_DESCRIBED", ""), li.LineDecision(4, "EXCHANGE", 1, "SIZE_MISMATCH", "")]


def test_three_refunded_one_exchanged_demo_quote():
    o = mixed_demo()
    q = li.quote_batch(o, decisions_demo(), li.Ledger())
    by = {x.line_no: x for x in q.refund_lines}
    assert set(by) == {1, 2, 3} and q.exchange_lines == ((4, 1),)
    assert by[2].shipping_minor == 0                 # changed mind: not a merchant error -> no shipping
    shares = o.shipping_shares()
    assert by[1].shipping_minor == shares[1] and by[3].shipping_minor == shares[3] and sum(shares.values()) == 600
    items = 4999 + 7900 + 1850
    taxes = 400 + 632 + 148
    assert q.total_minor == items + taxes + shares[1] + shares[3]
    assert li.summary_line(q) == f"Refund 3 items = {li.to_str(q.total_minor, 'USD')} USD; exchange 1 item, no refund"
    assert q.remaining_after_minor == o.total - q.total_minor


def test_shipping_never_policy_and_default():
    o = mixed_demo()
    never = li.quote_batch(o, decisions_demo(), li.Ledger(), shipping_policy="NEVER")
    assert all(x.shipping_minor == 0 for x in never.refund_lines)
    assert li.DEFAULT_SHIPPING_POLICY == "MERCHANT_ERROR"
    non_error = [li.LineDecision(1, "REFUND", 1, "CHANGED_MIND", ""), li.LineDecision(2, "REFUND", 1, "SIZE_MISMATCH", "")]
    assert all(x.shipping_minor == 0 for x in li.quote_batch(o, non_error, li.Ledger()).refund_lines)


def test_shipping_only_when_whole_line_refunded():
    o = li.OrderModel("USD", (li.Line(1, "A", "A", 1000, 3, 0),), 300)
    part = li.quote_batch(o, [li.LineDecision(1, "REFUND", 2, "DAMAGED", "")], li.Ledger())
    assert part.total_minor == 2000 and part.refund_lines[0].shipping_minor == 0
    rest = li.quote_batch(o, [li.LineDecision(1, "REFUND", 3, "DAMAGED", "")],
                          li.Ledger({1: 2}, {}, frozenset(), 2000))
    assert rest.total_minor == 1000 + 300 and rest.refund_lines[0].qty == 1   # the last unit releases the share


def test_partial_then_second_partial_demo():
    o = mixed_demo()
    d = decisions_demo()
    first = li.quote_batch(o, d[:1] + [li.LineDecision(n, "NEEDS_HUMAN", 1, "UNKNOWN", "") for n in (2, 3)] + d[3:], li.Ledger())
    assert [x.line_no for x in first.refund_lines] == [1] and first.exchange_lines == ((4, 1),)
    led = li.Ledger({1: 1}, {4: 1}, frozenset({1}), first.total_minor)
    second = li.quote_batch(o, d, led)
    assert [x.line_no for x in second.refund_lines] == [2, 3] and second.exchange_lines == ()
    assert first.total_minor + second.total_minor + second.remaining_after_minor == o.total


def test_jpy_zero_decimal_order():
    o = li.OrderModel("JPY", (li.Line(1, "A", "A", 1980, 2, 198), li.Line(2, "B", "B", 5000, 1, 500)), 700)
    q = li.quote_batch(o, [li.LineDecision(1, "REFUND", 2, "DAMAGED", ""), li.LineDecision(2, "EXCHANGE", 1, "X", "")],
                       li.Ledger())
    body = li.refund_amount_body(q)
    assert body == {"currency_code": "JPY", "value": str(q.total_minor)} and "." not in body["value"]
    assert o.to_paypal()["breakdown"]["item_total"]["value"] == str(1980 * 2 + 5000)


def test_order_validation():
    with pytest.raises(li.MoneyError):
        li.OrderModel("USD", ())
    with pytest.raises(li.MoneyError):
        li.OrderModel("USD", (li.Line(1, "A", "A", 1, 1), li.Line(1, "B", "B", 1, 1)))
    with pytest.raises(li.MoneyError):
        li.OrderModel("USD", (li.Line(1, "A", "A", 1, 0),))
    with pytest.raises(li.MoneyError):
        li.OrderModel("USD", (li.Line(1, "A", "A", -1, 1),))
    with pytest.raises(li.MoneyError):
        li.OrderModel("ZZZ", (li.Line(1, "A", "A", 1, 1),))
    with pytest.raises(li.MoneyError):
        li.OrderModel("USD", (li.Line(1, "A", "A", 1, 1),), -5)
    with pytest.raises(li.MoneyError):
        li.OrderModel("USD", (li.Line(1, "A", "A", 1, 1),)).line(9)


# ----------------------------------------------------------------------------------------------- idempotency
def test_request_id_is_deterministic_and_item_specific():
    o = mixed_demo()
    d = decisions_demo()
    q1, q2 = li.quote_batch(o, d, li.Ledger()), li.quote_batch(o, d, li.Ledger())
    h1, h2 = li.items_hash("M-ABCDEF0123456789", q1), li.items_hash("M-ABCDEF0123456789", q2)
    assert h1 == h2 and li.request_id("M-ABCDEF0123456789", h1) == li.request_id("M-ABCDEF0123456789", h2)
    assert len(li.request_id("M-ABCDEF0123456789", h1)) <= 38
    other = li.quote_batch(o, d[:2] + [li.LineDecision(3, "NEEDS_HUMAN", 1, "", "")] + d[3:], li.Ledger())
    assert li.items_hash("M-ABCDEF0123456789", other) != h1
    assert li.items_hash("M-ABCDEF0123456789", q1, attempt=1) != h1       # a retry after FAILED gets a new id
    assert li.items_hash("M-0000000000000000", q1) != h1                 # per case


# ----------------------------------------------------------------------------------------------- AI cannot set money
def test_llm_output_cannot_set_amounts():
    o = mixed_demo()
    evil = [{"line_no": 1, "action": "RETURN", "reason": "DAMAGED", "amount": "999999.00", "refund_total": "5000",
             "unit_price": "0.01", "currency": "JPY", "qty": 1, "tax": "99"},
            {"line_no": 2, "action": "RETURN", "reason": "CHANGED_MIND", "unit_minor": 1}]
    props, ignored = li.parse_proposals(evil, o)
    assert {"amount", "refund_total", "unit_price", "currency", "tax", "unit_minor"} <= set(ignored)
    assert all(set(p.__dict__) == {"line_no", "action", "reason", "qty"} for p in props)
    clean = [{"line_no": 1, "action": "RETURN", "reason": "DAMAGED"}, {"line_no": 2, "action": "RETURN", "reason": "CHANGED_MIND"}]
    kw = dict(purchase_date=TODAY, today=TODAY, return_window_days=30)
    a = li.quote_batch(o, li.decide_lines(o, props, **kw), li.Ledger())
    b = li.quote_batch(o, li.decide_lines(o, li.parse_proposals(clean, o)[0], **kw), li.Ledger())
    assert a.total_minor == b.total_minor and a.to_dict() == b.to_dict()


def test_malformed_model_output_becomes_unknown_never_a_refund():
    o = mixed_demo()
    kw = dict(purchase_date=TODAY, today=TODAY, return_window_days=30)
    for raw in (None, "refund everything", 42, [], [None, 3, "x"], {"lines": "x"},
                [{"line_no": "1", "action": "RETURN", "reason": "DAMAGED"}],
                [{"line_no": True, "action": "RETURN", "reason": "DAMAGED"}],
                [{"line_no": 99, "action": "RETURN", "reason": "DAMAGED"}],
                [{"line_no": 1, "action": "REFUND_ALL", "reason": "DAMAGED"}]):
        props, _ = li.parse_proposals(raw, o)
        assert len(props) == 4
        decisions = li.decide_lines(o, props, **kw)
        assert all(d.resolution == "NEEDS_HUMAN" for d in decisions)
        assert li.quote_batch(o, decisions, li.Ledger()).total_minor == 0
    props, _ = li.parse_proposals({"lines": [{"line_no": 1, "action": "RETURN", "reason": "DAMAGED", "qty": 99}]}, o)
    assert props[0].qty is None and props[0].action == "RETURN"          # out-of-range qty -> whole line, not 99
    props, _ = li.parse_proposals([{"line_no": 1, "action": "RETURN", "reason": "bogus"},
                                   {"line_no": 1, "action": "EXCHANGE", "reason": "DAMAGED"}], o)
    assert props[0].reason == "UNKNOWN" and props[0].action == "RETURN"  # duplicate entry for a line is ignored


def test_policy_rules_per_line():
    o = li.OrderModel("USD", (li.Line(1, "A", "A", 1000, 1), li.Line(2, "B", "B", 1000, 1, 0, False),
                               li.Line(3, "C", "C", 1000, 1)), 0)
    props = [li.Proposal(1, "RETURN", "DAMAGED"), li.Proposal(2, "RETURN", "DAMAGED"), li.Proposal(3, "RETURN", "UNKNOWN")]
    kw = dict(purchase_date=TODAY - timedelta(days=5), today=TODAY, return_window_days=30)
    r = {d.line_no: d.resolution for d in li.decide_lines(o, props, **kw)}
    assert r == {1: "REFUND", 2: "REJECT", 3: "NEEDS_HUMAN"}                       # final sale rejected, no reason -> human
    late = {d.line_no: d.resolution for d in li.decide_lines(o, props, purchase_date=TODAY - timedelta(days=45),
                                                              today=TODAY, return_window_days=30)}
    assert set(late.values()) == {"REJECT"} or late[3] == "REJECT"                  # out of window: nothing is refundable
    inj = li.decide_lines(o, props, injection_suspected=True, **kw)
    assert all(d.resolution == "NEEDS_HUMAN" for d in inj)
    ex = li.decide_lines(o, [li.Proposal(1, "EXCHANGE", "SIZE_MISMATCH")], **kw)
    assert ex[0].resolution == "EXCHANGE" and li.quote_batch(o, ex, li.Ledger()).total_minor == 0


def test_quote_refuses_a_total_one_minor_unit_over_the_remaining_balance():
    o = mixed_demo()
    q = li.quote_batch(o, decisions_demo(), li.Ledger())
    # a ledger that leaves exactly total-1 refundable must refuse; exactly total must pass
    with pytest.raises(li.OverRefund):
        li.quote_batch(o, decisions_demo(), li.Ledger(refunded_minor=o.total - q.total_minor + 1))
    ok = li.quote_batch(o, decisions_demo(), li.Ledger(refunded_minor=o.total - q.total_minor))
    assert ok.remaining_after_minor == 0


def test_to_minor_rejects_extra_decimals_in_decimal_input_instead_of_truncating():
    from decimal import Decimal
    with pytest.raises(li.MoneyError):
        li.to_minor(Decimal("49.999"), "USD")
    with pytest.raises(li.MoneyError):
        li.to_minor(Decimal("10.5"), "JPY")
