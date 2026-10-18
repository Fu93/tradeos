"""Per-line-item return / exchange / refund math for a mixed order. Pure Python: no I/O, no AI, no floats.

"AI understands, rules decide, humans approve, PayPal proves."

* The AI (or a human reading the message) may only PROPOSE, per line, an action (RETURN / EXCHANGE / UNKNOWN),
  a reason code and a quantity. ``parse_proposals`` drops every other key, so an "amount" smuggled into model
  output never reaches the money path.
* ``decide_lines`` turns proposals into a per-line resolution with deterministic rules.
* ``quote_batch`` computes the refund amount ONLY from the order's own line prices, in integer minor units,
  with the currency's PayPal exponent. It can never exceed the remaining refundable balance of the capture.
* ``request_id`` is derived deterministically from case + items (+ attempt), so a retry is idempotent.

Currency rules come from PayPal's currency-codes page: JPY, HUF and TWD do not support decimals ("If you
pass a decimal amount, an error occurs"); every other supported code is two-decimal. Unknown codes fail closed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

# PayPal currency-codes reference (developer.paypal.com/api/rest/reference/currency-codes/).
ZERO_DECIMAL = frozenset({"JPY", "HUF", "TWD"})
TWO_DECIMAL = frozenset({"AUD", "BRL", "CAD", "CNY", "CZK", "DKK", "EUR", "HKD", "ILS", "MYR", "MXN", "NZD", "NOK",
                         "PHP", "PLN", "GBP", "RUB", "SGD", "SEK", "CHF", "THB", "USD"})
SUPPORTED_CURRENCIES = ZERO_DECIMAL | TWO_DECIMAL

Resolution = Literal["REFUND", "EXCHANGE", "REJECT", "NEEDS_HUMAN"]
RESOLUTIONS = ("REFUND", "EXCHANGE", "REJECT", "NEEDS_HUMAN")
ACTIONS = ("RETURN", "EXCHANGE", "UNKNOWN")
# Same reason vocabulary as policy.REFUND_REASONS (kept literal here so this module has no imports from the app).
REFUND_REASONS = frozenset({"SIZE_MISMATCH", "DAMAGED", "WRONG_ITEM", "NOT_AS_DESCRIBED", "CHANGED_MIND"})
# The merchant got it wrong (damaged / wrong item / not as described): the only reasons that may release shipping.
MERCHANT_ERROR_REASONS = frozenset({"DAMAGED", "WRONG_ITEM", "NOT_AS_DESCRIBED"})
EXCHANGE_REASONS = frozenset({"SIZE_MISMATCH", "DAMAGED", "WRONG_ITEM", "NOT_AS_DESCRIBED", "CHANGED_MIND"})
# NEVER: no shipping refund. MERCHANT_ERROR: only for a line returned for a merchant-error reason.
# WITHDRAWAL_FULL (default): MERCHANT_ERROR, plus the order's shipping when the refund completes a whole-order return
# (UK Consumer Contracts Regs 2013 reg 34 / EU Directive 2011/83 art 13: original standard delivery is reimbursed on
# withdrawal from the contract; a partial return refunds no delivery). See docs/partial-refunds.md.
SHIPPING_POLICIES = ("NEVER", "MERCHANT_ERROR", "WITHDRAWAL_FULL")
DEFAULT_SHIPPING_POLICY = "WITHDRAWAL_FULL"
MAX_LINES = 50
MAX_QTY = 1000


class MoneyError(ValueError):
    """Invalid amount / currency / quantity. Always fail closed."""


class OverRefund(MoneyError):
    """A refund would exceed the remaining refundable balance of the capture."""


# --------------------------------------------------------------------------------------------- currency
def exponent(currency: str) -> int:
    if currency in ZERO_DECIMAL:
        return 0
    if currency in TWO_DECIMAL:
        return 2
    raise MoneyError(f"unsupported currency {currency!r}")


def to_minor(value: str | int | Decimal, currency: str) -> int:
    """Exact conversion of a PayPal money string to integer minor units. Extra decimals are an error
    (never rounded silently), as are negatives, NaN/Infinity, exponents and a decimal point on zero-decimal currencies."""
    exp = exponent(currency)
    if isinstance(value, bool):
        raise MoneyError("bad amount")
    if isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, Decimal):
        d = value
    else:
        text = str(value).strip()
        if not text or any(ch not in "0123456789." for ch in text) or text.count(".") > 1:
            raise MoneyError(f"bad amount {value!r}")
        if "." in text and (exp == 0 or len(text.split(".")[1]) > exp or text.endswith(".")):
            # PayPal: JPY/HUF/TWD "do not support decimals; if you pass a decimal amount, an error occurs".
            raise MoneyError(f"{value!r} is not a valid {currency} amount ({exp} decimals)")
        try:
            d = Decimal(text)
        except InvalidOperation:
            raise MoneyError(f"bad amount {value!r}")
    if not d.is_finite() or d < 0:
        raise MoneyError(f"bad amount {value!r}")
    scaled = d.scaleb(exp)
    if scaled != scaled.to_integral_value():
        raise MoneyError(f"{value!r} has more decimals than {currency} allows ({exp})")
    return int(scaled)


def to_str(minor: int, currency: str) -> str:
    """Integer minor units -> PayPal money string (JPY '1500', USD '12.30')."""
    exp = exponent(currency)
    if minor < 0:
        raise MoneyError("negative amount")
    if exp == 0:
        return str(minor)
    q, r = divmod(minor, 10 ** exp)
    return f"{q}.{r:0{exp}d}"


def allocate(total: int, weights: list[int]) -> list[int]:
    """Largest-remainder split of ``total`` minor units over ``weights``: shares sum to ``total`` EXACTLY, no
    float, ties broken by position (deterministic). All-zero weights -> everything on the first slot."""
    if total < 0 or any(w < 0 for w in weights):
        raise MoneyError("negative allocation input")
    if not weights:
        if total:
            raise MoneyError("nothing to allocate to")
        return []
    s = sum(weights)
    if s == 0:
        return [total] + [0] * (len(weights) - 1)
    base = [total * w // s for w in weights]
    rem = [total * w % s for w in weights]
    left = total - sum(base)
    for i in sorted(range(len(weights)), key=lambda k: (-rem[k], k))[:left]:
        base[i] += 1
    return base


# --------------------------------------------------------------------------------------------- order model
@dataclass(frozen=True)
class Line:
    line_no: int
    sku: str
    name: str
    unit_minor: int
    qty: int
    tax_unit_minor: int = 0   # PayPal items[].tax is PER UNIT; tax_total = sum(tax * quantity)
    returnable: bool = True

    @property
    def item_minor(self) -> int:
        return self.unit_minor * self.qty

    @property
    def tax_minor(self) -> int:
        return self.tax_unit_minor * self.qty


@dataclass(frozen=True)
class OrderModel:
    currency: str
    lines: tuple[Line, ...]
    shipping_minor: int = 0

    def __post_init__(self) -> None:
        exponent(self.currency)
        if not self.lines or len(self.lines) > MAX_LINES:
            raise MoneyError("an order needs 1..%d lines" % MAX_LINES)
        if len({ln.line_no for ln in self.lines}) != len(self.lines):
            raise MoneyError("duplicate line numbers")
        for ln in self.lines:
            if not (1 <= ln.qty <= MAX_QTY) or ln.unit_minor < 0 or ln.tax_unit_minor < 0:
                raise MoneyError(f"invalid line {ln.line_no}")
        if self.shipping_minor < 0:
            raise MoneyError("negative shipping")

    @property
    def item_total(self) -> int:
        return sum(ln.item_minor for ln in self.lines)

    @property
    def tax_total(self) -> int:
        return sum(ln.tax_minor for ln in self.lines)

    @property
    def total(self) -> int:
        return self.item_total + self.tax_total + self.shipping_minor

    def line(self, line_no: int) -> Line:
        for ln in self.lines:
            if ln.line_no == line_no:
                return ln
        raise MoneyError(f"no line {line_no}")

    def shipping_shares(self) -> dict[int, int]:
        """Shipping spread over the lines by item value (largest remainder: shares sum to shipping exactly)."""
        shares = allocate(self.shipping_minor, [ln.item_minor for ln in self.lines])
        return {ln.line_no: s for ln, s in zip(self.lines, shares)}

    def to_paypal(self) -> dict:
        """Orders v2 shape: purchase_units[].items[] + amount.breakdown, from the same integers the refund math uses."""
        c = self.currency

        def money(minor: int) -> dict:
            return {"currency_code": c, "value": to_str(minor, c)}

        breakdown: dict[str, Any] = {"item_total": money(self.item_total)}
        if self.tax_total:
            breakdown["tax_total"] = money(self.tax_total)
        if self.shipping_minor:
            breakdown["shipping"] = money(self.shipping_minor)
        items = []
        for ln in self.lines:
            it: dict[str, Any] = {"name": ln.name[:127], "sku": ln.sku[:127], "quantity": str(ln.qty),
                                  "unit_amount": money(ln.unit_minor), "category": "PHYSICAL_GOODS"}
            if ln.tax_unit_minor:
                it["tax"] = money(ln.tax_unit_minor)
            items.append(it)
        return {"items": items, "breakdown": breakdown, "total": money(self.total)}

    def to_dict(self) -> dict:
        return {"currency": self.currency, "shipping_minor": self.shipping_minor,
                "lines": [{"line_no": ln.line_no, "sku": ln.sku, "name": ln.name, "unit_minor": ln.unit_minor,
                           "qty": ln.qty, "tax_unit_minor": ln.tax_unit_minor, "returnable": ln.returnable}
                          for ln in self.lines]}


# --------------------------------------------------------------------------------------------- proposals
@dataclass(frozen=True)
class Proposal:
    """What the AI (or a human) may say about one line. Deliberately has no amount field."""
    line_no: int
    action: str = "UNKNOWN"          # RETURN / EXCHANGE / UNKNOWN
    reason: str = "UNKNOWN"
    qty: int | None = None           # None = the whole line


ALLOWED_PROPOSAL_KEYS = frozenset({"line_no", "action", "reason", "qty"})


def parse_proposals(raw: Any, order: OrderModel) -> tuple[list[Proposal], list[str]]:
    """Untrusted model output -> Proposals. Returns (proposals, ignored_fields).

    Every key outside line_no/action/reason/qty is dropped and reported (so an "amount", "refund_total" or
    "unit_price" in model output is visible in the audit trail and has no effect). Malformed entries become UNKNOWN
    (a human decides). A line with no entry gets an UNKNOWN proposal: silence is never a refund."""
    ignored: list[str] = []
    found: dict[int, Proposal] = {}
    if isinstance(raw, dict) and isinstance(raw.get("lines"), list):
        raw = raw["lines"]
    if isinstance(raw, list):
        for entry in raw[:MAX_LINES]:
            if not isinstance(entry, dict):
                continue
            for k in entry:
                if k not in ALLOWED_PROPOSAL_KEYS:
                    ignored.append(str(k)[:40])
            ln = entry.get("line_no")
            if isinstance(ln, bool) or not isinstance(ln, int) or ln in found:
                continue
            if not any(x.line_no == ln for x in order.lines):
                continue
            action = str(entry["action"]) if entry.get("action") in ACTIONS else "UNKNOWN"
            reason = str(entry["reason"]) if isinstance(entry.get("reason"), str) else "UNKNOWN"
            qty = entry.get("qty")
            if isinstance(qty, bool) or not isinstance(qty, int) or not (1 <= qty <= order.line(ln).qty):
                qty = None
            found[ln] = Proposal(ln, action, reason if reason in REFUND_REASONS else "UNKNOWN", qty)
    return [found.get(ln.line_no, Proposal(ln.line_no)) for ln in order.lines], sorted(set(ignored))


# --------------------------------------------------------------------------------------------- decisions
@dataclass(frozen=True)
class LineDecision:
    line_no: int
    resolution: str                 # REFUND / EXCHANGE / REJECT / NEEDS_HUMAN
    qty: int                        # units the resolution applies to
    reason: str                     # the proposed reason code (for shipping / audit)
    detail: str                     # why, in words

    @property
    def merchant_error(self) -> bool:
        return self.reason in MERCHANT_ERROR_REASONS

    def to_dict(self) -> dict:
        return {"line_no": self.line_no, "resolution": self.resolution, "qty": self.qty, "reason": self.reason,
                "detail": self.detail}


def decide_lines(order: OrderModel, proposals: list[Proposal], *, purchase_date: date, today: date,
                 return_window_days: int, injection_suspected: bool = False) -> list[LineDecision]:
    """Deterministic per-line policy. The proposal can only turn a line INTO a refund if every rule passes;
    UNKNOWN, a missing reason, an instruction-like message or a non-returnable product can never become one."""
    by_line = {p.line_no: p for p in proposals}
    days = (today - purchase_date).days
    in_window = 0 <= days <= return_window_days
    out: list[LineDecision] = []
    for ln in order.lines:
        p = by_line.get(ln.line_no, Proposal(ln.line_no))
        qty = p.qty or ln.qty
        if injection_suspected:
            out.append(LineDecision(ln.line_no, "NEEDS_HUMAN", qty, p.reason,
                                    "Message contains instruction-like text (heuristic) — a human reads it"))
        elif p.action not in ("RETURN", "EXCHANGE"):
            out.append(LineDecision(ln.line_no, "NEEDS_HUMAN", qty, p.reason,
                                    "Request for this item not understood — a human decides"))
        elif not in_window:
            out.append(LineDecision(ln.line_no, "REJECT", qty, p.reason,
                                    f"Purchased {days} days ago; window is {return_window_days} days"))
        elif not ln.returnable:
            out.append(LineDecision(ln.line_no, "REJECT", qty, p.reason, f"{ln.name} is final sale / not returnable"))
        elif p.action == "RETURN" and p.reason not in REFUND_REASONS:
            out.append(LineDecision(ln.line_no, "NEEDS_HUMAN", qty, p.reason,
                                    "A refund needs a stated reason (size, damaged, wrong item, not as described, "
                                    "changed mind)"))
        elif p.action == "RETURN":
            out.append(LineDecision(ln.line_no, "REFUND", qty, p.reason,
                                    f"Return for a refund ({p.reason}); window and product checks passed"))
        else:
            out.append(LineDecision(ln.line_no, "EXCHANGE", qty, p.reason,
                                    "Exchange: supplier replacement, no refund; window and product checks passed"))
    return out


# --------------------------------------------------------------------------------------------- pricing
@dataclass(frozen=True)
class Ledger:
    """What earlier (live) batches already reserved. Derived from stored batches, never from the model."""
    refund_qty: dict[int, int] = field(default_factory=dict)       # line_no -> units already in a refund batch
    exchange_qty: dict[int, int] = field(default_factory=dict)     # line_no -> units already in an exchange
    shipping_released: frozenset[int] = frozenset()                # lines whose shipping share was already refunded
    refunded_minor: int = 0                                        # money already committed on the capture


@dataclass(frozen=True)
class QuoteLine:
    line_no: int
    qty: int
    item_minor: int
    tax_minor: int
    shipping_minor: int

    @property
    def total_minor(self) -> int:
        return self.item_minor + self.tax_minor + self.shipping_minor


@dataclass(frozen=True)
class Quote:
    currency: str
    refund_lines: tuple[QuoteLine, ...]
    exchange_lines: tuple[tuple[int, int], ...]   # (line_no, qty)
    total_minor: int
    capture_minor: int
    remaining_after_minor: int
    shipping_policy: str

    @property
    def refund_units(self) -> int:
        return sum(q.qty for q in self.refund_lines)

    @property
    def exchange_units(self) -> int:
        return sum(q for _, q in self.exchange_lines)

    @property
    def empty(self) -> bool:
        return not self.refund_lines and not self.exchange_lines

    def to_dict(self) -> dict:
        return {"currency": self.currency, "total_minor": self.total_minor, "capture_minor": self.capture_minor,
                "remaining_after_minor": self.remaining_after_minor, "shipping_policy": self.shipping_policy,
                "refund_lines": [{"line_no": q.line_no, "qty": q.qty, "item_minor": q.item_minor,
                                  "tax_minor": q.tax_minor, "shipping_minor": q.shipping_minor}
                                 for q in self.refund_lines],
                "exchange_lines": [{"line_no": n, "qty": q} for n, q in self.exchange_lines]}


def quote_batch(order: OrderModel, decisions: list[LineDecision], ledger: Ledger, *,
                shipping_policy: str = DEFAULT_SHIPPING_POLICY, capture_minor: int | None = None) -> Quote:
    """THE refund computation. Inputs are the order's own prices + code-made decisions + the ledger.

    Per refunded line: item = unit * qty, tax = tax_unit * qty (PayPal item tax is per unit, so this is the item's own
    tax, exactly proportional, no rounding). Shipping: released under MERCHANT_ERROR/WITHDRAWAL_FULL for a line refunded for a
    merchant-error reason, only once the line is fully refunded across batches, only once per line, share =
    largest-remainder allocation of shipping by item value. Raises OverRefund if total > capture - already refunded."""
    if shipping_policy not in SHIPPING_POLICIES:
        raise MoneyError(f"unknown shipping policy {shipping_policy!r}")
    capture = order.total if capture_minor is None else capture_minor
    if capture != order.total:
        raise MoneyError("capture amount does not equal the order lines total — needs a human")
    shares = order.shipping_shares()
    refund_lines: list[QuoteLine] = []
    exchange_lines: list[tuple[int, int]] = []
    for d in sorted(decisions, key=lambda x: x.line_no):
        ln = order.line(d.line_no)
        used_r = ledger.refund_qty.get(ln.line_no, 0)
        used_x = ledger.exchange_qty.get(ln.line_no, 0)
        free = ln.qty - used_r - used_x
        if d.resolution == "REFUND":
            qty = min(d.qty - used_r, free)      # the decision's units minus those an earlier batch already took
            if qty <= 0:
                continue
            ship = 0
            if (shipping_policy in ("MERCHANT_ERROR", "WITHDRAWAL_FULL") and d.merchant_error
                    and ln.line_no not in ledger.shipping_released and used_r + qty == ln.qty):
                ship = shares[ln.line_no]
            refund_lines.append(QuoteLine(ln.line_no, qty, ln.unit_minor * qty, ln.tax_unit_minor * qty, ship))
        elif d.resolution == "EXCHANGE":
            qty = min(d.qty - used_x, free)
            if qty > 0:
                exchange_lines.append((ln.line_no, qty))
    if shipping_policy == "WITHDRAWAL_FULL" and refund_lines:
        refund_lines = _release_shipping_on_full_return(order, refund_lines, exchange_lines, ledger, shares)
    total = sum(q.total_minor for q in refund_lines)
    remaining = capture - ledger.refunded_minor
    if total > remaining:
        raise OverRefund(f"refund {total} exceeds the remaining refundable balance {remaining}")
    return Quote(order.currency, tuple(refund_lines), tuple(exchange_lines), total, capture, remaining - total,
                 shipping_policy)


def _release_shipping_on_full_return(order: OrderModel, refund_lines: list[QuoteLine],
                                     exchange_lines: list[tuple[int, int]], ledger: Ledger,
                                     shares: dict[int, int]) -> list[QuoteLine]:
    """WITHDRAWAL_FULL: if this batch completes a return of EVERY unit of EVERY line (nothing exchanged, rejected or
    still open), the consumer withdrew from the whole order, so the order's shipping is released: each line in this
    batch gets its own share (if not yet released) and the shares of lines refunded in earlier batches that never
    got one are added to this batch's last line. Never more than the order's shipping in total."""
    if exchange_lines or ledger.exchange_qty:
        return refund_lines
    in_batch = {q.line_no: q for q in refund_lines}
    for ln in order.lines:
        got = in_batch[ln.line_no].qty if ln.line_no in in_batch else 0
        if ledger.refund_qty.get(ln.line_no, 0) + got != ln.qty:
            return refund_lines
    out: list[QuoteLine] = []
    leftover = sum(shares[ln.line_no] for ln in order.lines
                   if ln.line_no not in in_batch and ln.line_no not in ledger.shipping_released)
    last = max(in_batch)
    for q in refund_lines:
        ship = q.shipping_minor
        if not ship and q.line_no not in ledger.shipping_released:
            ship = shares[q.line_no]
        if q.line_no == last:
            ship += leftover
        out.append(QuoteLine(q.line_no, q.qty, q.item_minor, q.tax_minor, ship))
    return out


def items_hash(case_id: str, quote: Quote, attempt: int = 0) -> str:
    """Stable fingerprint of exactly what a batch refunds / exchanges (case, currency, per-line amounts, attempt)."""
    payload = {"case": case_id, "attempt": attempt, "quote": quote.to_dict()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def request_id(case_id: str, digest: str) -> str:
    """Deterministic PayPal-Request-Id: same case + same items + same attempt -> same id (idempotent retries);
    different items -> different id. <= 38 chars for a 16-hex case id (PayPal's UUID-length guidance)."""
    return f"tos-mx-{case_id}-{digest[:10]}"


def refund_amount_body(quote: Quote) -> dict:
    return {"currency_code": quote.currency, "value": to_str(quote.total_minor, quote.currency)}


def summary_line(quote: Quote) -> str:
    """The sentence the approval screen shows, e.g. 'Refund 3 items = 147.49 USD; exchange 1 item, no refund'."""
    c = quote.currency
    parts = []
    if quote.refund_lines:
        n = quote.refund_units
        parts.append(f"Refund {n} item{'s' if n != 1 else ''} = {to_str(quote.total_minor, c)} {c}")
    if quote.exchange_lines:
        n = quote.exchange_units
        parts.append(f"exchange {n} item{'s' if n != 1 else ''}, no refund")
    return "; ".join(parts) if parts else "Nothing to refund or exchange"
