"""Mixed orders: several line items, each resolved on its own (return -> partial refund, exchange -> supplier
replacement with no refund, reject, needs a human), refunded as PayPal PARTIAL refunds.

AI understands, rules decide, humans approve, PayPal proves:
  * per-line PROPOSALS (action + reason + qty, never an amount) are the only AI/human-language input;
  * ``lineitems.decide_lines`` / ``quote_batch`` (pure code) decide and price, in integer minor units;
  * a human approves ONE batch, seeing the exact total; the approval + the proposal are hash-chained;
  * the refund goes out with an explicit amount and a deterministic PayPal-Request-Id, and the amount PayPal reports
    back must equal the computed amount.

A batch is one PayPal partial refund (plus the exchange lines approved with it). A case can have several batches
(partial, then a second partial for lines a human resolved later) as long as their sum stays within the capture.

Nothing here runs without a human click: there is no autonomy path for mixed orders.
"""

from __future__ import annotations

import json
import threading
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from . import lineitems as li
from .intent import looks_like_injection
from .safety import assess as safety_assess
from .paypal_client import PayPalError, first_capture

if TYPE_CHECKING:  # pragma: no cover
    from .workflow import Workflow

MIXED = "MIXED"                        # cases.decision of a mixed order (the legacy refund gate refuses it)
DEMO_BADGE = "DEMO-DATA"

# Case statuses of a mixed order. None of them is in db.TERMINAL_CASE_STATUSES: a second partial refund must stay possible.
S_PENDING = "MIXED_PENDING_APPROVAL"
S_PROGRESS = "MIXED_REFUND_PENDING"
S_NEEDS = "MIXED_NEEDS_HUMAN"
S_ATTENTION = "MIXED_ATTENTION"
S_UNKNOWN = "MIXED_OUTCOME_UNKNOWN"
S_DONE = "MIXED_DONE"
MIXED_STATUSES = (S_PENDING, S_PROGRESS, S_NEEDS, S_ATTENTION, S_UNKNOWN, S_DONE)

# Batch statuses
PROPOSED, APPROVED, COMPLETED, PENDING = "PROPOSED", "APPROVED", "COMPLETED", "PENDING"
FAILED, ERROR, UNKNOWN, DECLINED, MISMATCH = "FAILED", "ERROR", "UNKNOWN", "DECLINED", "AMOUNT_MISMATCH"
RELEASED = (DECLINED, FAILED)          # these hold neither quantity nor money

# ----------------------------------------------------------------------------------------- demo order (seeded)
DEMO_LINES = (
    # sku, name, unit price, tax per unit, qty
    ("MX-SNEAKER-42", "Trail Runner sneakers, EU 42", "49.99", "4.00", 1),
    ("MX-JACKET-M", "Rain jacket, size M", "79.00", "6.32", 1),
    ("MX-SOCKS-3", "Merino socks, 3-pack", "18.50", "1.48", 1),
    ("MX-TSHIRT-M", "Cotton T-shirt, size M", "24.00", "1.92", 1),
)
DEMO_SHIPPING = "6.00"
DEMO_MESSAGE = (
    "I ordered four things. The sneakers arrived damaged, the rain jacket and the socks are not what I wanted, "
    "so I'd like to return those three for a refund. The T-shirt is too small: please exchange it for size L."
)
# "Case M2" (two-step): same seeded order, but the customer is only sure about the sneakers (return) and the T-shirt
# (exchange). The jacket and socks stay UNKNOWN, so code leaves them with a human. A person resolves them one at a time,
# which creates a SECOND batch (and a third) on the SAME capture; the ledger caps the cumulative refund at the capture.
TWO_STEP_MESSAGE = (
    "I ordered four things. The sneakers arrived damaged, please refund them. The T-shirt is too small: please "
    "exchange it for size L. I haven't decided about the rain jacket and the socks yet - I'll tell you later."
)
TWO_STEP_PROPOSALS = [
    {"line_no": 1, "action": "RETURN", "reason": "DAMAGED"},
    {"line_no": 2, "action": "UNKNOWN", "reason": "UNKNOWN"},
    {"line_no": 3, "action": "UNKNOWN", "reason": "UNKNOWN"},
    {"line_no": 4, "action": "EXCHANGE", "reason": "SIZE_MISMATCH"},
]
# Stand-in for the AI extractor's per-line reading of DEMO_MESSAGE (the per-line extractor is NOT built; see
# docs/partial-refunds.md). It contains only what a model may say: no amount.
DEMO_PROPOSALS = [
    {"line_no": 1, "action": "RETURN", "reason": "DAMAGED"},
    {"line_no": 2, "action": "RETURN", "reason": "CHANGED_MIND"},
    {"line_no": 3, "action": "RETURN", "reason": "NOT_AS_DESCRIBED"},
    {"line_no": 4, "action": "EXCHANGE", "reason": "SIZE_MISMATCH"},
]


def demo_order(currency: str, shipping_policy: str | None = None) -> li.OrderModel:
    if li.exponent(currency) != 2:
        raise li.MoneyError(f"the seeded demo order is priced in a two-decimal currency, not {currency}")
    return li.OrderModel(currency, tuple(
        li.Line(i, sku, name, li.to_minor(price, currency), qty, li.to_minor(tax, currency))
        for i, (sku, name, price, tax, qty) in enumerate(DEMO_LINES, 1)), li.to_minor(DEMO_SHIPPING, currency))


def money_label(minor: int, currency: str) -> str:
    value = li.to_str(minor, currency)
    return f"${value}" if currency == "USD" else f"{value} {currency}"


class MixedOrders:
    def __init__(self, wf: "Workflow") -> None:
        self.wf = wf
        self.db = wf.db

    # ------------------------------------------------------------------ helpers
    @property
    def policy(self) -> str:
        return getattr(self.wf.settings, "shipping_policy", li.DEFAULT_SHIPPING_POLICY)

    def order(self, case_id: str) -> li.OrderModel:
        case = self.wf._case(case_id)
        rows = self.db.get_items(case_id)
        shipping = int(case.get("shipping_minor") or 0)
        return li.OrderModel(case["currency"], tuple(
            li.Line(r["line_no"], r["sku"], r["name"], r["unit_minor"], r["qty"], r["tax_unit_minor"], r["returnable"])
            for r in rows), shipping)

    def decisions(self, case_id: str) -> list[li.LineDecision]:
        out = []
        for r in self.db.get_items(case_id):
            if r["resolution"]:
                out.append(li.LineDecision(r["line_no"], r["resolution"], r["resolution_qty"] or r["qty"],
                                           (r["proposal"] or {}).get("reason", "UNKNOWN"),
                                           r["resolution_detail"] or ""))
        return out

    def ledger(self, case_id: str, exclude: str | None = None) -> li.Ledger:
        refund_qty: dict[int, int] = {}
        exch_qty: dict[int, int] = {}
        released: set[int] = set()
        money = 0
        for b in self.db.list_batches(case_id):
            if b["id"] == exclude or b["status"] in RELEASED:
                continue
            money += b["amount_minor"]
            for q in (b["quote"] or {}).get("refund_lines", []):
                refund_qty[q["line_no"]] = refund_qty.get(q["line_no"], 0) + q["qty"]
                if q["shipping_minor"]:
                    released.add(q["line_no"])
            for q in (b["quote"] or {}).get("exchange_lines", []):
                exch_qty[q["line_no"]] = exch_qty.get(q["line_no"], 0) + q["qty"]
        return li.Ledger(refund_qty, exch_qty, frozenset(released), money)

    def _purchase_date(self, case: dict) -> date:
        if case.get("purchase_date_seeded"):
            return date.fromisoformat(case["purchase_date_seeded"])
        ts = case.get("capture_time")
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).date() if ts else self.wf.today()

    def effective_refund_status(self, case: dict) -> str | None:
        """For the disputes view: did money move (or may it have) on any batch of this order?"""
        if case.get("decision") != MIXED:
            return case.get("refund_status")
        live = {b["status"] for b in self.db.list_batches(case["id"])}
        if live & {COMPLETED, PENDING, UNKNOWN, MISMATCH}:
            return "COMPLETED" if COMPLETED in live else "PENDING"
        return None

    # ------------------------------------------------------------------ create + process
    def create_case(self, message: str | None = None, label: str | None = None, case_id: str | None = None) -> str:
        import uuid
        s = self.wf.settings
        model = demo_order(s.currency)
        for ln in model.lines:
            self.db.upsert_product(ln.sku, ln.name, "apparel", True, li.to_str(ln.unit_minor, s.currency),
                                   "Stride Footwear Co. (fictional demo supplier)")
        case_id = case_id or f"M-{uuid.uuid4().hex[:16].upper()}"
        self.db.insert_case(
            id=case_id, scenario="M", label=label or "Case M — mixed order (DEMO-DATA)", status="NEW",
            customer_name="Priya (demo customer)", customer_message=message or DEMO_MESSAGE,
            product_sku=model.lines[0].sku, amount=li.to_str(model.total, s.currency), currency=s.currency,
            shipping_minor=str(model.shipping_minor))
        self.db.insert_items(case_id, [{"line_no": ln.line_no, "sku": ln.sku, "name": ln.name,
                                        "unit_minor": ln.unit_minor, "qty": ln.qty,
                                        "tax_unit_minor": ln.tax_unit_minor, "returnable": ln.returnable}
                                       for ln in model.lines])
        self.db.audit(case_id, "request", "Mixed order created (seeded DEMO-DATA order lines; the PayPal order and "
                      "capture will be a real Sandbox transaction)",
                      {"lines": len(model.lines), "shipping_minor": model.shipping_minor,
                       "total_minor": model.total, "currency": s.currency, "demo": True})
        return case_id

    def process(self, case_id: str) -> None:
        wf = self.wf
        case = wf._case(case_id)
        model = self.order(case_id)
        c = model.currency
        try:
            order = wf._pp(case_id, "create_order_with_card", li.to_str(model.total, c), c, case_id,
                           f"TradeOS mixed demo {case_id}", f"tradeos-order-{case_id}", order_lines=model.to_paypal())
            self.db.update_case(case_id, order_id=order["id"], order_status=order.get("status"))
            self.db.audit(case_id, "payment", "PayPal order created (items[] + amount breakdown)",
                          {"order_id": order["id"], "status": order.get("status"),
                           "amount": f"{li.to_str(model.total, c)} {c}", "shipping_minor": model.shipping_minor,
                           "item_total_minor": model.item_total, "tax_total_minor": model.tax_total})
            capture = first_capture(order)
            if not capture:
                raise PayPalError("Card capture unavailable: a mixed order needs an immediate sandbox capture")
            wf._record_capture(case_id, order, capture)
        except PayPalError as exc:
            wf._fail(case_id, "payment", exc)
            return
        self.db.audit(case_id, "request", "Customer request received",
                      {"customer": case["customer_name"], "message": case["customer_message"]})
        gate = safety_assess(case["customer_message"], None, None)
        gate, ai_info = wf.safety_screen(gate, case["customer_message"], None)
        if gate.flagged:  # Safety Gate first: no policy lines, no batch, no refund, whatever the per-line reading says
            wf._route_to_safety_review(case_id, gate, None, ai_info)
            return
        self.evaluate(case_id)

    def evaluate(self, case_id: str) -> None:
        wf = self.wf
        case = wf._case(case_id)
        model = self.order(case_id)
        try:
            capture = wf._pp(case_id, "get_capture", case["capture_id"])
        except PayPalError as exc:
            wf._fail(case_id, "policy", exc)
            return
        amount = capture.get("amount") or {}
        problem = None
        if capture.get("status") != "COMPLETED":
            problem = f"PayPal capture status is {capture.get('status') or 'missing'} (must be COMPLETED)"
        elif amount.get("currency_code") != model.currency or amount.get("value") != li.to_str(model.total, model.currency):
            problem = (f"Captured {amount.get('value')} {amount.get('currency_code')} differs from the order lines "
                       f"total {li.to_str(model.total, model.currency)} {model.currency}")
        if problem:
            self.db.update_case(case_id, decision=MIXED, status=S_NEEDS)
            self.db.audit(case_id, "policy", "Mixed order: capture does not match the order lines — needs a human; "
                          "Refund API NOT CALLED", {"problem": problem, "refund_id": None})
            return
        proposals, ignored = li.parse_proposals(TWO_STEP_PROPOSALS if case.get("customer_message") == TWO_STEP_MESSAGE else DEMO_PROPOSALS, model)
        self.db.audit(case_id, "intent", "Per-line proposals recorded (DEMO-DATA stand-in for the AI reading; "
                      "proposals carry no amount)",
                      {"proposals": [p.__dict__ for p in proposals], "ignored_fields": ignored})
        decisions = li.decide_lines(model, proposals, purchase_date=self._purchase_date(case), today=wf.today(),
                                    return_window_days=wf.settings.return_window_days,
                                    injection_suspected=looks_like_injection(case.get("customer_message") or ""))
        self.db.update_case(case_id, decision=MIXED)
        self._store_decisions(case_id, proposals, decisions, "Policy decided line")
        self.propose_batch(case_id)

    def _store_decisions(self, case_id: str, proposals: list[li.Proposal], decisions: list[li.LineDecision],
                         title: str) -> None:
        by_p = {p.line_no: p for p in proposals}
        for d in decisions:
            p = by_p.get(d.line_no, li.Proposal(d.line_no))
            self.db.update_item(case_id, d.line_no, proposal_json=json.dumps(
                {"action": p.action, "reason": p.reason, "qty": p.qty}), resolution=d.resolution,
                resolution_qty=d.qty, resolution_detail=d.detail)
            self.db.audit(case_id, "policy", f"{title} {d.line_no}: {d.resolution}",
                          {"line_no": d.line_no, "resolution": d.resolution, "qty": d.qty, "reason": d.reason,
                           "detail": d.detail, "decided_by": "deterministic policy code"})

    # ------------------------------------------------------------------ batches
    def propose_batch(self, case_id: str) -> dict | None:
        """Price the lines that are decided REFUND / EXCHANGE and not yet in a live batch. Pure code. Idempotent:
        the same items return the same open batch."""
        wf = self.wf
        with wf._lock(case_id):
            case = wf._case(case_id)
            if case.get("decision") != MIXED:
                raise wf_refused("not a mixed order")
            model = self.order(case_id)
            try:
                quote = li.quote_batch(model, self.decisions(case_id), self.ledger(case_id), shipping_policy=self.policy)
            except li.MoneyError as exc:
                self.db.audit(case_id, "policy", "Mixed order: refund could not be computed — needs a human; "
                              "Refund API NOT CALLED", {"reason": str(exc), "refund_id": None})
                self._sync(case_id)
                return None
            if quote.empty:
                self._sync(case_id)
                return next((b for b in self.db.list_batches(case_id) if b["status"] == PROPOSED), None)
            existing = self.db.list_batches(case_id)
            attempt = 0
            while True:
                digest = li.items_hash(case_id, quote, attempt)
                same = [b for b in existing if b["items_hash"] == digest]
                if not same:
                    break
                if any(b["status"] not in RELEASED for b in same):
                    return same[0]
                attempt += 1
            batch_no = max((b["batch_no"] for b in existing), default=0) + 1
            batch_id = f"{case_id}-B{batch_no}"
            summary = li.summary_line(quote)
            self.db.insert_batch(id=batch_id, case_id=case_id, batch_no=batch_no, attempt=attempt, items_hash=digest,
                                 status=PROPOSED, amount_minor=quote.total_minor, currency=quote.currency,
                                 request_id=li.request_id(case_id, digest) if quote.total_minor else None,
                                 quote_json=json.dumps(quote.to_dict()), summary=summary)
            self.db.audit(case_id, "policy", f"Batch {batch_no} proposed by code: {summary}",
                          {"batch_id": batch_id, "items_hash": digest, "amount_minor": quote.total_minor,
                           "currency": quote.currency, "summary": summary, "quote": quote.to_dict(),
                           "shipping_policy": quote.shipping_policy,
                           "computed_by": "deterministic policy code from order line prices; no AI value is an input"})
            self.db.audit(case_id, "human", f"Waiting for human approval of batch {batch_no}",
                          {"batch_id": batch_id, "summary": summary})
            self._sync(case_id)
            return self.db.get_batch(batch_id)

    def approve_batch(self, case_id: str, batch_id: str, expected_total: str | None = None,
                      expected_hash: str | None = None, approver: str = "merchant") -> dict:
        """A person approves ONE batch. The page submits the total and fingerprint it displayed; if either no longer
        matches what code recomputes now, nothing is approved (stale screen / tampered form)."""
        wf = self.wf
        try:
            with wf._money_op(), wf._lock(case_id):
                case, batch = self._load(case_id, batch_id)
                wf._refuse_if_safety(case)
                if batch["status"] != PROPOSED:
                    raise wf_refused(f"Batch {batch['batch_no']} is {batch['status']}, not awaiting approval "
                                     "(a second approval does nothing).")
                shown = li.to_str(batch["amount_minor"], batch["currency"])
                if expected_total is None or expected_hash is None:
                    raise wf_refused("The approval must carry the total and fingerprint shown on screen.")
                if expected_total != shown or expected_hash != batch["items_hash"]:
                    raise wf_refused("The screen is out of date: the batch differs from what you were shown. "
                                     "Reload and review again.")
                quote = self._recompute(case_id, batch)
                if li.items_hash(case_id, quote, batch["attempt"]) != batch["items_hash"]:
                    raise wf_refused("The order state changed since this batch was proposed — reload and review.")
                now = wf._now()
                self.db.update_batch(batch_id, status=APPROVED, approved_by=approver, approved_at=now)
                self.db.audit(case_id, "human", f"Human approved batch {batch['batch_no']}: {batch['summary']}",
                              {"batch_id": batch_id, "items_hash": batch["items_hash"],
                               "amount_minor": batch["amount_minor"], "currency": batch["currency"],
                               "approver": approver, "source": "human"})
                if quote.exchange_lines:
                    names = {ln.line_no: ln.name for ln in self.order(case_id).lines}
                    self.db.audit(case_id, "supplier", "Exchange arranged (replacement via the MOCK supplier) — no "
                                  "refund for these lines", {"batch_id": batch_id, "refund_id": None, "lines": [
                                      {"line_no": n, "name": names[n], "qty": q} for n, q in quote.exchange_lines]})
                if batch["amount_minor"] == 0:
                    self.db.update_batch(batch_id, status=COMPLETED)
                    self.db.audit(case_id, "paypal", "Refund API NOT CALLED — exchange only, no refund in this batch",
                                  {"batch_id": batch_id, "refund_id": None})
                    self._sync(case_id)
                else:
                    self._execute(case_id, batch_id)
        finally:
            self._after_money(case_id)
        return self.db.get_batch(batch_id) or {}

    def decline_batch(self, case_id: str, batch_id: str, approver: str = "merchant") -> None:
        wf = self.wf
        with wf._lock(case_id):
            case, batch = self._load(case_id, batch_id)
            if batch["status"] not in (PROPOSED, ERROR, APPROVED) or batch["refund_id"]:
                raise wf_refused(f"Batch {batch['batch_no']} is {batch['status']} and cannot be declined.")
            self.db.update_batch(batch_id, status=DECLINED)
            self.db.audit(case_id, "human", f"Human declined batch {batch['batch_no']} — Refund API not called for it",
                          {"batch_id": batch_id, "approver": approver, "prior_status": batch["status"]})
            self._sync(case_id)

    def retry_batch(self, case_id: str, batch_id: str) -> dict:
        """After ERROR (PayPal refused, no money moved), UNKNOWN (no answer) or an approved batch that never got sent:
        the same PayPal-Request-Id again (same guard, same amount)."""
        wf = self.wf
        try:
            with wf._money_op(), wf._lock(case_id):
                case, batch = self._load(case_id, batch_id)
                if batch["status"] not in (ERROR, UNKNOWN, APPROVED) or batch["refund_id"]:
                    raise wf_refused(f"Batch {batch['batch_no']} is {batch['status']}; nothing to retry.")
                prior = batch["status"]
                if prior != APPROVED:  # the money gate wants APPROVED; the chained human approval is still re-verified
                    self.db.update_batch(batch_id, status=APPROVED)
                try:
                    self._execute(case_id, batch_id)
                except wf_refused_type():
                    self.db.update_batch(batch_id, status=prior)
                    raise
        finally:
            self._after_money(case_id)
        return self.db.get_batch(batch_id) or {}

    def repropose(self, case_id: str) -> dict | None:
        """Human asks for a fresh batch of whatever is open (e.g. after PayPal reported a refund FAILED)."""
        with self.wf._lock(case_id):
            if any(b["status"] == PROPOSED for b in self.db.list_batches(case_id)):
                raise wf_refused("A batch is already awaiting approval.")
        return self.propose_batch(case_id)

    def resolve_line(self, case_id: str, line_no: int, action: str, reason: str, approver: str = "merchant") -> dict | None:
        """A human reads a NEEDS_HUMAN line and PROPOSES an action/reason for it. The rules still decide and price it."""
        wf = self.wf
        if action not in ("RETURN", "EXCHANGE", "REJECT") or reason not in li.REFUND_REASONS | {"UNKNOWN"}:
            raise wf_refused("Unknown action or reason.")
        with wf._lock(case_id):
            case = wf._case(case_id)
            rows = {r["line_no"]: r for r in self.db.get_items(case_id)}
            row = rows.get(line_no)
            if case.get("decision") != MIXED or row is None or row["resolution"] != "NEEDS_HUMAN":
                raise wf_refused("Only a line that needs a human can be resolved this way.")
            model = self.order(case_id)
            if action == "REJECT":
                dec = li.LineDecision(line_no, "REJECT", row["qty"], reason, "Rejected by a human reviewer")
                prop = li.Proposal(line_no, "UNKNOWN", reason)
            else:
                prop = li.Proposal(line_no, action, reason)
                decided = li.decide_lines(model, [prop], purchase_date=self._purchase_date(case), today=wf.today(),
                                          return_window_days=wf.settings.return_window_days)
                dec = next(d for d in decided if d.line_no == line_no)
            self.db.audit(case_id, "human", f"Human reviewer proposed {action} ({reason}) for line {line_no}; the "
                          "policy rules decide and price it", {"line_no": line_no, "action": action, "reason": reason,
                                                               "approver": approver})
            self._store_decisions(case_id, [prop], [dec], "Policy decided (after human review) line")
        return self.propose_batch(case_id)

    # ------------------------------------------------------------------ guards + execution
    def _load(self, case_id: str, batch_id: str) -> tuple[dict, dict]:
        case = self.wf._case(case_id)
        batch = self.db.get_batch(batch_id)
        if case.get("decision") != MIXED or batch is None or batch["case_id"] != case_id:
            raise wf_refused("No such batch on this mixed order.")
        return case, batch

    def _recompute(self, case_id: str, batch: dict) -> li.Quote:
        try:
            return li.quote_batch(self.order(case_id), self.decisions(case_id),
                                  self.ledger(case_id, exclude=batch["id"]), shipping_policy=self.policy)
        except li.MoneyError as exc:
            raise wf_refused(f"Refund no longer computable: {exc}")

    def _guard(self, case_id: str, batch: dict) -> None:
        """The money gate. Reads the audit chain, not just the row: the proposal (what the human was shown) and the
        human approval of exactly this batch fingerprint + amount must both be chained, and the chain must verify."""
        self.wf._refuse_if_safety(self.wf._case(case_id))
        if batch["status"] != APPROVED:
            raise wf_refused(f"Batch {batch['batch_no']} is {batch['status']}; refund refused.")
        if not batch.get("approved_by"):
            raise wf_refused("An approval is required before any refund.")
        chain = self.db.verify_chain(case_id)
        if not chain["ok"]:
            raise wf_refused(f"Audit trail BROKEN at entry {chain['broken_at']}; refund refused.")
        proposed = approved = False
        for e in self.db.chain_entries(case_id):
            if not e["type"].startswith("audit:"):
                continue
            payload = json.loads(e["payload_json"])
            d = payload.get("detail") or {}
            if (d.get("batch_id") == batch["id"] and d.get("items_hash") == batch["items_hash"]
                    and d.get("amount_minor") == batch["amount_minor"] and d.get("currency") == batch["currency"]):
                if payload.get("title", "").startswith("Batch ") and "proposed by code" in payload["title"]:
                    proposed = True
                elif payload.get("title", "").startswith("Human approved batch") and d.get("source") == "human":
                    approved = True
        if not (proposed and approved):
            raise wf_refused("No chained proposal + human approval for this exact batch and amount; refund refused.")
        quote = self._recompute(case_id, batch)
        if (li.items_hash(case_id, quote, batch["attempt"]) != batch["items_hash"]
                or quote.total_minor != batch["amount_minor"]):
            raise wf_refused("The batch no longer matches the recomputed amount; refund refused.")

    def _note(self, batch: dict) -> str:
        n = sum(q["qty"] for q in (batch["quote"] or {}).get("refund_lines", []))
        return f"Partial refund for {n} returned item{'s' if n != 1 else ''} from your order."[:255]

    def _execute(self, case_id: str, batch_id: str) -> None:
        wf = self.wf
        case = wf._case(case_id)
        batch = self.db.get_batch(batch_id) or {}
        self._guard(case_id, batch)
        cur = batch["currency"]
        # PayPal proves the precondition: the capture is read afresh, and must be the one the lines add up to.
        try:
            capture = wf._pp(case_id, "get_capture", case["capture_id"])
        except PayPalError as exc:
            self.db.audit(case_id, "paypal", "Could not read the capture before refunding — nothing sent",
                          {**exc.to_dict(), "batch_id": batch_id})
            raise
        amount = capture.get("amount") or {}
        if capture.get("status") not in ("COMPLETED", "PARTIALLY_REFUNDED") or amount.get("currency_code") != cur:
            self.db.audit(case_id, "paypal", f"Refund API NOT CALLED — capture is {capture.get('status')}, needs a human",
                          {"batch_id": batch_id, "capture_status": capture.get("status"), "refund_id": None})
            raise wf_refused(f"PayPal reports the capture as {capture.get('status')}; refund refused, needs a human.")
        cap_minor = li.to_minor(amount.get("value") or "0", cur)
        if cap_minor - self.ledger(case_id, exclude=batch_id).refunded_minor < batch["amount_minor"]:
            raise wf_refused("The refund would exceed the remaining refundable balance of the capture; refused.")
        body_amount = {"currency_code": cur, "value": li.to_str(batch["amount_minor"], cur)}
        try:
            refund = wf._pp(case_id, "refund_capture", case["capture_id"], batch["request_id"],
                            note_to_payer=self._note(batch), amount=body_amount, custom_id=f"{case_id}-B{batch['batch_no']}")
        except PayPalError as exc:
            certain = (not exc.sent) or (exc.status_code is not None and exc.status_code < 500
                                         and exc.status_code not in (408, 429))
            if certain:
                self.db.update_batch(batch_id, status=ERROR, error=str(exc))
                self.db.audit(case_id, "paypal", "Partial refund failed — PayPal refused it, no money moved",
                              {**exc.to_dict(), "batch_id": batch_id, "paypal_request_id": batch["request_id"]})
            else:
                self.db.update_batch(batch_id, status=UNKNOWN, error=str(exc))
                self.db.audit(case_id, "paypal", "Partial refund outcome UNKNOWN — no reply from PayPal; checking",
                              {**exc.to_dict(), "batch_id": batch_id, "paypal_request_id": batch["request_id"]})
                wf._needs_check.add(case_id)
            self._sync(case_id)
            raise
        self._record(case_id, batch_id, refund, via="refund_api")

    def _debug_id(self, case_id: str, request_id: str | None) -> str | None:
        for c in reversed(self.db.paypal_calls(case_id, "refund_capture")):
            if c["request_id"] == request_id and c["ok"]:
                return c.get("debug_id")
        return None

    def _record(self, case_id: str, batch_id: str, refund: dict, via: str) -> None:
        wf = self.wf
        batch = self.db.get_batch(batch_id) or {}
        cur = batch["currency"]
        status = refund.get("status")
        reported = refund.get("amount")
        if not reported or reported.get("value") is None:  # minimal response: PayPal's GET is the proof
            try:
                got = wf._pp(case_id, "get_refund", refund["id"], timeout=5.0)
                reported = got.get("amount")
                refund = {**refund, **got}
            except PayPalError:
                reported = None
        paypal_amount = (f"{reported['value']} {reported.get('currency_code')}"
                         if reported and reported.get("value") else None)
        computed = f"{li.to_str(batch['amount_minor'], cur)} {cur}"
        try:
            same = (reported is not None and li.to_minor(reported["value"], cur) == batch["amount_minor"]
                    and reported.get("currency_code") == cur)
        except li.MoneyError:
            same = False
        new_status = {"COMPLETED": COMPLETED, "PENDING": PENDING}.get(status or "", FAILED)
        if not same and new_status != FAILED:
            new_status = MISMATCH
        fields: dict[str, Any] = dict(refund_id=refund.get("id"), refund_status=status, refund_json=json.dumps(refund),
                                      paypal_amount=paypal_amount, status=new_status, error=None)
        dbg = self._debug_id(case_id, batch["request_id"])
        if dbg:
            fields["debug_id"] = dbg
        self.db.update_batch(batch_id, **fields)
        title = f"PayPal partial refund {status} (batch {batch['batch_no']})"
        if new_status == MISMATCH:
            title = (f"PayPal reports {paypal_amount or 'no amount'} but TradeOS computed {computed} — "
                     "AMOUNT MISMATCH, needs a human")
        self.db.audit(case_id, "paypal", title,
                      {"batch_id": batch_id, "refund_id": refund.get("id"), "status": status, "via": via,
                       "computed_amount": computed, "paypal_amount": paypal_amount, "amounts_equal": same,
                       "debug_id": dbg, "paypal_request_id": batch["request_id"],
                       "create_time": refund.get("create_time"), "status_details": refund.get("status_details")})
        self._sync(case_id)

    # ------------------------------------------------------------------ unknown outcome, reconcile, webhook
    def _after_money(self, case_id: str) -> None:
        wf = self.wf
        if case_id in wf._needs_check:
            wf._needs_check.discard(case_id)
            if wf.settings.reconcile_in_background:
                threading.Thread(target=self.check_unknown, args=(case_id,), daemon=True).start()
            else:
                self.check_unknown(case_id)

    def check_unknown(self, case_id: str) -> None:
        """Read-only GET of the capture after an unanswered refund call. The same request id is re-sent (recovery)
        only when PayPal shows the capture refunded AND no other batch explains that."""
        wf = self.wf
        try:
            case = wf._case(case_id)
            capture = wf._pp(case_id, "get_capture", case["capture_id"], timeout=5.0)
            status = capture.get("status")
            self.db.audit(case_id, "paypal", f"Checked with PayPal after an unanswered partial refund call: capture "
                          f"is {status}", {"capture_status": status})
            others = [b for b in self.db.list_batches(case_id) if b["status"] in (COMPLETED, PENDING) and b["amount_minor"]]
            if status in ("REFUNDED", "PARTIALLY_REFUNDED") and not others:
                self.recover_unknown(case_id, "after the GET check")
        except PayPalError:
            self.db.audit(case_id, "paypal", "Could not check with PayPal after the unanswered refund call — a retry "
                          "still uses the same PayPal-Request-Id", {})

    def recover_unknown(self, case_id: str, trigger: str) -> bool:
        wf = self.wf
        recovered = False
        with wf._money_op(), wf._lock(case_id):
            for batch in self.db.list_batches(case_id):
                if batch["status"] != UNKNOWN or batch["refund_id"]:
                    continue
                self.db.update_batch(batch["id"], status=APPROVED)  # the guard needs APPROVED; chain proves the approval
                try:
                    self._guard(case_id, self.db.get_batch(batch["id"]) or {})
                    case = wf._case(case_id)
                    refund = wf._pp(case_id, "refund_capture", case["capture_id"], batch["request_id"],
                                    note_to_payer=self._note(batch),
                                    amount={"currency_code": batch["currency"],
                                            "value": li.to_str(batch["amount_minor"], batch["currency"])},
                                    custom_id=f"{case_id}-B{batch['batch_no']}")
                except Exception as exc:  # restore UNKNOWN whatever went wrong
                    self.db.update_batch(batch["id"], status=UNKNOWN)
                    self.db.audit(case_id, "paypal", "Could not recover the partial refund from PayPal — outcome "
                                  "still UNKNOWN, needs a human", {"batch_id": batch["id"], "trigger": trigger,
                                                                   "error": str(exc)[:200]})
                    continue
                self.db.audit(case_id, "paypal", f"Recovered the partial refund from PayPal ({trigger}): same "
                              "PayPal-Request-Id re-sent once", {"batch_id": batch["id"], "refund_id": refund.get("id")})
                self._record(case_id, batch["id"], refund, via="recovery")
                recovered = True
        return recovered

    def reconcile(self, case_id: str, timeout: float | None = None) -> dict | None:
        """Read-only towards PayPal: GET capture, GET refund for each PENDING batch. Only PENDING -> COMPLETED/FAILED
        is applied (never a downgrade, never a refund call)."""
        wf = self.wf
        case = wf._case(case_id)
        if not case.get("capture_id"):
            return None
        timeout = 5.0 if timeout is None else timeout
        try:
            capture = wf._pp(case_id, "get_capture", case["capture_id"], timeout=timeout)
            fetched = {b["id"]: wf._pp(case_id, "get_refund", b["refund_id"], timeout=timeout)
                       for b in self.db.list_batches(case_id) if b["refund_id"] and b["status"] == PENDING}
        except PayPalError as exc:
            detail = {"error": str(exc), "debug_id": exc.debug_id or None}
            self.db.audit(case_id, "reconcile", "Reconciliation skipped — PayPal unreachable/error (no change)", detail)
            return {"ok": False, **detail}
        if any(b["status"] == UNKNOWN for b in self.db.list_batches(case_id)) and capture.get("status") in (
                "REFUNDED", "PARTIALLY_REFUNDED"):
            self.check_unknown(case_id)
        checks = []
        with wf._lock(case_id):
            for batch in self.db.list_batches(case_id):
                got = fetched.get(batch["id"])
                if got is None:
                    continue
                st = got.get("status")
                ok = st in ("COMPLETED", "PENDING", "FAILED")
                advance = ok and st != batch["refund_status"]  # PENDING -> COMPLETED/FAILED: PayPal's GET is applied
                checks.append({"field": f"batch {batch['batch_no']} refund.status", "local": batch["refund_status"],
                               "paypal": st, "match": st == batch["refund_status"] or advance,
                               "advanced": advance})
                if advance:
                    self._record(case_id, batch["id"], {**(batch["refund"] or {}), **got}, via="reconcile")
            led = self.ledger(case_id)
            cap_total = li.to_minor((capture.get("amount") or {}).get("value") or "0", case["currency"])
            checks.append({"field": "capture.status", "local": "COMPLETED/PARTIALLY_REFUNDED/REFUNDED",
                           "paypal": capture.get("status"),
                           "match": capture.get("status") in ("COMPLETED", "PARTIALLY_REFUNDED", "REFUNDED")})
            if capture.get("status") == "REFUNDED" and led.refunded_minor < cap_total and not any(
                    b["status"] == UNKNOWN for b in self.db.list_batches(case_id)):
                checks.append({"field": "refunded total", "local": li.to_str(led.refunded_minor, case["currency"]),
                               "paypal": "REFUNDED (full)", "match": False})
            bad = [c for c in checks if not c["match"]]
            self.db.audit(case_id, "reconcile", ("Reconciled with PayPal: all checks match" if not bad else
                          f"Reconciliation found {len(bad)} difference(s) — flagged for a human, nothing overwritten"),
                          {"checks": checks, "refunded_minor": led.refunded_minor, "capture_minor": cap_total})
            self._sync(case_id)
        return {"ok": not bad, "checks": checks}

    def apply_webhook(self, case: dict, etype: str, resource: dict, info: dict) -> tuple[str, str]:
        """Verified first delivery, case lock held. A refund event is matched to its batch by PayPal's refund id."""
        wf = self.wf
        case_id = case["id"]
        batch = self.db.find_batch_by_refund(resource.get("id") or "")
        res_status = resource.get("status")
        if batch is None:
            unknown = [b for b in self.db.list_batches(case_id) if b["status"] == UNKNOWN and not b["refund_id"]]
            if unknown and etype in ("PAYMENT.CAPTURE.REFUNDED", "PAYMENT.REFUND.PENDING"):
                wf._pending_recovery_requests.add(case_id)
                return ("UNKNOWN_RECOVERY", f"Verified PayPal webhook {etype} for this order's capture while a partial "
                        "refund outcome is UNKNOWN — recovering it from PayPal (same PayPal-Request-Id)")
            return ("MISMATCH_IGNORED", "Verified PayPal webhook does not match any batch refund id of this order "
                    "— logged, no state change")
        local = batch["refund_status"]
        reported = resource.get("amount")
        if reported and reported.get("value") is not None:
            try:
                if (li.to_minor(reported["value"], batch["currency"]) != batch["amount_minor"]
                        or reported.get("currency_code") not in (None, batch["currency"])):
                    return ("NEEDS_HUMAN", f"Verified PayPal webhook amount {reported.get('value')} differs from the "
                            f"computed batch amount — needs a human (no automatic change)")
            except li.MoneyError:
                return ("NEEDS_HUMAN", "Verified PayPal webhook carries an unreadable amount — needs a human")
        merged = {**(batch["refund"] or {}), **resource}
        if res_status == "COMPLETED":
            if local == "PENDING":
                self._record(case_id, batch["id"], merged, via="webhook")
                wf._confirm_webhook(case_id, info)
                return "PENDING_TO_COMPLETED", f"Verified PayPal webhook moved batch {batch['batch_no']} refund PENDING → COMPLETED"
            if local == "COMPLETED":
                wf._confirm_webhook(case_id, info)
                return ("CONFIRMED", f"PayPal webhook {etype} received — signature verified (second confirmation of "
                        f"batch {batch['batch_no']})")
            return ("NEEDS_HUMAN", f"Verified PayPal webhook says COMPLETED but TradeOS has {local} — needs a human")
        if local == "COMPLETED":
            return ("NO_CHANGE", f"Verified PayPal webhook reports refund {res_status} after COMPLETED — not downgraded")
        if res_status == "FAILED" and local == "PENDING":
            self._record(case_id, batch["id"], merged, via="webhook")
            return "PENDING_TO_FAILED", "Verified PayPal webhook: partial refund FAILED at PayPal — needs a human"
        return "NO_CHANGE", f"Verified PayPal webhook reports refund {res_status} — no state change"

    def resume(self) -> int:
        n = 0
        for b in self.db.unresolved_batches():
            n += self.wf.auto_reconcile(b["case_id"], background=self.wf.settings.reconcile_in_background)
        return n

    # ------------------------------------------------------------------ status + view
    def _open_lines(self, case_id: str) -> int:
        model = self.order(case_id)
        led = self.ledger(case_id)
        n = 0
        for r in self.db.get_items(case_id):
            if r["resolution"] == "NEEDS_HUMAN":
                n += 1
            elif r["resolution"] in ("REFUND", "EXCHANGE"):
                free = model.line(r["line_no"]).qty - led.refund_qty.get(r["line_no"], 0) - led.exchange_qty.get(r["line_no"], 0)
                n += 1 if free > 0 else 0
        return n

    def _sync(self, case_id: str) -> None:
        batches = self.db.list_batches(case_id)
        st = {b["status"] for b in batches}
        if UNKNOWN in st:
            new = S_UNKNOWN
        elif st & {ERROR, MISMATCH}:
            new = S_ATTENTION
        elif PROPOSED in st:
            new = S_PENDING
        elif PENDING in st or APPROVED in st:
            new = S_PROGRESS
        elif self._open_lines(case_id):
            new = S_NEEDS
        else:
            new = S_DONE
        if self.wf._case(case_id)["status"] != new:
            self.db.update_case(case_id, status=new)

    def view(self, case_id: str) -> dict:
        """Everything the approval screen shows. Money strings are formatted from integer minor units."""
        case = self.wf._case(case_id)
        model = self.order(case_id)
        cur = model.currency
        rows = {r["line_no"]: r for r in self.db.get_items(case_id)}
        batches = self.db.list_batches(case_id)
        shares = model.shipping_shares()
        in_batch: dict[int, list[str]] = {}
        quote_of: dict[int, dict] = {}
        pending = next((b for b in batches if b["status"] == PROPOSED), None)
        for b in batches:
            if b["status"] in RELEASED:
                continue
            for q in (b["quote"] or {}).get("refund_lines", []):
                in_batch.setdefault(q["line_no"], []).append(f"refund in batch {b['batch_no']} ({b['status']})")
                if pending is not None and b["id"] == pending["id"]:
                    quote_of[q["line_no"]] = q
            for q in (b["quote"] or {}).get("exchange_lines", []):
                in_batch.setdefault(q["line_no"], []).append(f"exchange in batch {b['batch_no']} ({b['status']})")

        def m(x: int) -> str:
            return money_label(x, cur)

        # Amounts per line from batches that are past the proposal (approved / at PayPal / done): the item table keeps
        # showing them after approval instead of going back to a dash. Computed by code from the stored quote.
        settled: dict[int, dict] = {}
        for b in batches:
            if b["status"] in RELEASED or b["status"] == PROPOSED:
                continue
            label = {COMPLETED: "refunded", PENDING: "pending at PayPal"}.get(b["status"], "approved, not confirmed yet")
            for q in (b["quote"] or {}).get("refund_lines", []):
                d = settled.setdefault(q["line_no"], {"item": 0, "tax": 0, "ship": 0, "labels": set()})
                d["item"] += q["item_minor"]
                d["tax"] += q["tax_minor"]
                d["ship"] += q["shipping_minor"]
                d["labels"].add(label)

        def settled_label(labels: set[str]) -> str:
            return "refunded" if labels == {"refunded"} else " / ".join(sorted(labels))

        lines = []
        for ln in model.lines:
            r = rows[ln.line_no]
            q = quote_of.get(ln.line_no)
            lines.append({"line_no": ln.line_no, "name": ln.name, "sku": ln.sku, "qty": ln.qty, "unit": m(ln.unit_minor),
                          "tax_unit": m(ln.tax_unit_minor), "resolution": r["resolution"] or "—",
                          "detail": r["resolution_detail"] or "", "reason": (r["proposal"] or {}).get("reason", ""),
                          "refund_item": m(q["item_minor"]) if q else None, "refund_tax": m(q["tax_minor"]) if q else None,
                          "refund_ship": m(q["shipping_minor"]) if q else None,
                          "refund_total": m(q["item_minor"] + q["tax_minor"] + q["shipping_minor"]) if q else None,
                          "done_total": m(sd["item"] + sd["tax"] + sd["ship"]) if (sd := settled.get(ln.line_no)) else None,
                          "done_parts": f"{m(sd['item'])} + {m(sd['tax'])} + {m(sd['ship'])}" if sd else None,
                          "done_label": settled_label(sd["labels"]) if sd else None,
                          "ship_share": m(shares[ln.line_no]), "state": "; ".join(in_batch.get(ln.line_no, [])),
                          "needs_human": r["resolution"] == "NEEDS_HUMAN"})
        led = self.ledger(case_id)
        quote = (pending["quote"] or {}) if pending else {}
        approval = None
        if pending:
            items = sum(q["item_minor"] for q in quote["refund_lines"])
            taxes = sum(q["tax_minor"] for q in quote["refund_lines"])
            ship = sum(q["shipping_minor"] for q in quote["refund_lines"])
            approval = {"batch": pending, "summary": pending["summary"], "total": m(pending["amount_minor"]),
                        "total_plain": li.to_str(pending["amount_minor"], cur), "hash": pending["items_hash"],
                        "items_total": m(items), "tax": m(taxes), "shipping": m(ship),
                        "after": m(quote["remaining_after_minor"]),
                        "exchange_only": pending["amount_minor"] == 0}
        batch_rows = [{"id": b["id"], "no": b["batch_no"], "status": b["status"], "summary": b["summary"],
                       "amount": m(b["amount_minor"]), "refund_id": b["refund_id"], "refund_status": b["refund_status"],
                       "paypal_amount": b["paypal_amount"], "debug_id": b["debug_id"], "request_id": b["request_id"],
                       "equal": (b["paypal_amount"] == f"{li.to_str(b['amount_minor'], cur)} {cur}") if b["paypal_amount"] else None,
                       "retryable": b["status"] in (ERROR, UNKNOWN, APPROVED) and not b["refund_id"],
                       "declinable": b["status"] in (PROPOSED, ERROR, APPROVED) and not b["refund_id"], "error": b["error"]} for b in batches]
        return {"case_id": case_id, "currency": cur, "lines": lines, "approval": approval, "batches": batch_rows,
                "captured": m(model.total), "committed": m(led.refunded_minor),
                "remaining": m(model.total - led.refunded_minor), "shipping": m(model.shipping_minor),
                "shipping_policy": self.policy, "status": case["status"],
                "open_lines": self._open_lines(case_id),
                "can_repropose": pending is None and any(r["resolution"] in ("REFUND", "EXCHANGE") for r in rows.values())
                and self._open_lines(case_id) > 0,
                "demo": case["scenario"] == "M", "demo_badge": DEMO_BADGE}

    def api(self, case_id: str) -> dict:
        case = self.wf._case(case_id)
        model = self.order(case_id)
        led = self.ledger(case_id)
        return {"items": self.db.get_items(case_id),
                "batches": [{k: v for k, v in b.items() if k not in ("quote_json", "refund_json")}
                            for b in self.db.list_batches(case_id)],
                "ledger": {"currency": case["currency"], "captured_minor": model.total,
                           "committed_minor": led.refunded_minor, "remaining_minor": model.total - led.refunded_minor,
                           "shipping_policy": self.policy}}


def wf_refused_type() -> type[Exception]:
    from .workflow import RefundNotAllowed
    return RefundNotAllowed


def wf_refused(msg: str) -> Exception:
    from .workflow import RefundNotAllowed
    return RefundNotAllowed(msg)
