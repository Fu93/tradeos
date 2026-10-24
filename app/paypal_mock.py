"""Offline stand-in for PayPal, used by the test-suite and by the opt-in PAYPAL_MOCK=1 mode.

Every ID it returns starts with MOCK- and the UI shows a red banner when it is active.
It is never used automatically: without credentials the app shows a visible error instead.
"""

from __future__ import annotations

import copy
import itertools
import time
from datetime import datetime, timezone

from .paypal_client import PayPalError


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


PENDING_DEMO_PREFIX = "tradeos-refund-P-"  # scenario P (mock only): refund starts PENDING


class MockPayPalClient:
    is_mock = True
    base_url = "mock://paypal"

    def __init__(self, refund_status: str = "COMPLETED", card_capture: bool = True,
                 fail_refund: bool = False) -> None:
        self._seq = itertools.count(1)
        self.refund_status = refund_status
        self.card_capture = card_capture
        self.fail_refund = fail_refund
        self.orders: dict[str, dict] = {}
        self.captures: dict[str, dict] = {}
        self.refunds_by_request: dict[str, dict] = {}
        # PayPal-Request-Id idempotency for the order calls, as PayPal documents it: the same id returns the result
        # of the first request instead of doing the work again (so a retried card charge or capture never charges
        # twice). developer.paypal.com/api/rest/reference/idempotency/
        self.orders_by_request: dict[str, dict] = {}
        self.pending_demo_seconds = 20.0
        self.disputes = {}

    last_debug_id: str | None = None

    def _id(self, kind: str) -> str:
        n = next(self._seq)
        self.last_debug_id = f"mock-debug-{n:04d}"  # labelled fake, mirrors PayPal-Debug-Id
        return f"MOCK-{kind}-{n:04d}"

    def _capture(self, amount: str, currency: str) -> dict:
        cap_id = self._id("CAPTURE")
        cap = {"id": cap_id, "status": "COMPLETED", "create_time": _now(),
               "amount": {"currency_code": currency, "value": amount}}
        self.captures[cap_id] = cap
        return cap

    def create_order_with_card(self, amount, currency, reference_id, description, request_id, order_lines=None):
        if request_id in self.orders_by_request:
            return copy.deepcopy(self.orders_by_request[request_id])
        if not self.card_capture:
            raise PayPalError("Card payments not enabled for this account (mock)", 422, "UNPROCESSABLE_ENTITY")
        if order_lines:  # PayPal validates the breakdown arithmetic: item_total + tax_total + shipping == value
            from .lineitems import MoneyError, to_minor
            try:
                parts = order_lines["breakdown"]
                got = sum(to_minor(parts[k]["value"], currency) for k in ("item_total", "tax_total", "shipping")
                          if k in parts)
                items = sum(to_minor(i["unit_amount"]["value"], currency) * int(i["quantity"]) for i in order_lines["items"])
                taxes = sum(to_minor(i.get("tax", {"value": "0"})["value"], currency) * int(i["quantity"])
                            for i in order_lines["items"])
                ok = (got == to_minor(amount, currency) and items == to_minor(parts["item_total"]["value"], currency)
                      and taxes == to_minor(parts.get("tax_total", {"value": "0"})["value"], currency))
            except (MoneyError, KeyError, ValueError):
                ok = False
            if not ok:
                raise PayPalError("Item amounts do not add up (mock)", 422, "UNPROCESSABLE_ENTITY",
                                  details=[{"issue": "AMOUNT_MISMATCH"}])
        order = {"id": self._id("ORDER"), "status": "COMPLETED",
                 "purchase_units": [{"reference_id": reference_id,
                                     "payments": {"captures": [self._capture(amount, currency)]}}]}
        self.orders[order["id"]] = order
        self.orders_by_request[request_id] = copy.deepcopy(order)  # PayPal replays the response it sent then
        return order

    def create_order(self, amount, currency, reference_id, description, request_id, return_url, cancel_url):
        if request_id in self.orders_by_request:
            return copy.deepcopy(self.orders_by_request[request_id])
        order = {"id": self._id("ORDER"), "status": "PAYER_ACTION_REQUIRED", "_amount": (amount, currency),
                 "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=mock"}]}
        self.orders[order["id"]] = order
        self.orders_by_request[request_id] = copy.deepcopy(order)  # PayPal replays the response it sent then
        return order

    def capture_order(self, order_id, request_id):
        if request_id in self.orders_by_request:
            return copy.deepcopy(self.orders_by_request[request_id])
        order = self.orders[order_id]
        amount, currency = order.get("_amount", ("49.99", "USD"))
        order.update({"status": "COMPLETED",
                      "purchase_units": [{"payments": {"captures": [self._capture(amount, currency)]}}]})
        self.orders_by_request[request_id] = copy.deepcopy(order)  # PayPal replays the response it sent then
        return order

    def get_capture(self, capture_id, timeout=None):
        return dict(self.captures[capture_id])

    is_sandbox = True

    @staticmethod
    def _minor(value: str, currency: str) -> int:
        from .lineitems import MoneyError, to_minor
        try:
            return to_minor(value, currency)
        except MoneyError as exc:
            raise PayPalError(f"Invalid amount (mock): {exc}", 400, "INVALID_REQUEST",
                              details=[{"issue": "DECIMAL_PRECISION"}])

    def _refunded_minor(self, capture_id: str, currency: str, completed_only: bool = False) -> int:
        return sum(self._minor(r["amount"]["value"], currency) for r in self.refunds_by_request.values()
                   if r["_capture"] == capture_id and r["status"] != "FAILED"
                   and (not completed_only or r["status"] == "COMPLETED"))

    def _capture_status_after(self, capture_id: str) -> None:
        cap = self.captures[capture_id]
        cur = cap["amount"]["currency_code"]
        done = self._refunded_minor(capture_id, cur, completed_only=True)
        if done:
            cap["status"] = "REFUNDED" if done >= self._minor(cap["amount"]["value"], cur) else "PARTIALLY_REFUNDED"

    def refund_capture(self, capture_id, request_id, note_to_payer=None, mock_response=None, amount=None,
                       custom_id=None):
        if self.fail_refund:
            raise PayPalError("Refund failed (mock)", 422, "UNPROCESSABLE_ENTITY")
        if mock_response:  # mirrors PayPal-Mock-Response negative testing
            raise PayPalError(f"The requested action could not be completed (mock) ({mock_response})", 422,
                              "UNPROCESSABLE_ENTITY", debug_id="mock-debug",
                              details=[{"issue": mock_response}])
        body = (note_to_payer, repr(sorted((amount or {}).items())), custom_id)
        prior = self.refunds_by_request.get(request_id)
        if prior is not None and prior["_capture"] == capture_id and prior.get("_body") == body:
            return {k: v for k, v in prior.items() if not k.startswith("_")}  # idempotent: same id + same body
        if prior is not None:  # same PayPal-Request-Id, different capture or body
            raise PayPalError("PayPal-Request-Id reused with a different request (mock)", 422, "UNPROCESSABLE_ENTITY",
                              details=[{"issue": "DUPLICATE_REQUEST_ID"}])
        cap = self.captures[capture_id]
        cur = cap["amount"]["currency_code"]
        remaining = self._minor(cap["amount"]["value"], cur) - self._refunded_minor(capture_id, cur)
        if amount is None:
            if remaining <= 0:
                raise PayPalError("Capture has already been fully refunded (mock)", 422, "UNPROCESSABLE_ENTITY",
                                  details=[{"issue": "CAPTURE_FULLY_REFUNDED"}])
            refund_minor = remaining  # PayPal: captured amount - previous refunds
        else:
            if amount.get("currency_code") != cur:
                raise PayPalError("Refund currency must equal the capture currency (mock)", 422,
                                  "UNPROCESSABLE_ENTITY", details=[{"issue": "REFUND_CURRENCY_MISMATCH"}])
            refund_minor = self._minor(amount["value"], cur)
            if refund_minor <= 0:
                raise PayPalError("Refund amount must be positive (mock)", 400, "INVALID_REQUEST",
                                  details=[{"issue": "INVALID_PARAMETER_VALUE"}])
            if refund_minor > remaining:
                raise PayPalError("Refund amount exceeds what is left to refund (mock)", 422, "UNPROCESSABLE_ENTITY",
                                  details=[{"issue": "REFUND_AMOUNT_EXCEEDED"}])
        from .lineitems import to_str
        pending_demo = request_id.startswith(PENDING_DEMO_PREFIX)
        refund = {"id": self._id("REFUND"), "status": "PENDING" if pending_demo else self.refund_status,
                  "amount": {"currency_code": cur, "value": to_str(refund_minor, cur)},
                  "_capture": capture_id, "_body": body, "_note": note_to_payer}
        if custom_id:
            refund["custom_id"] = custom_id[:127]
        if note_to_payer:
            refund["note_to_payer"] = note_to_payer[:255]
        if pending_demo:  # like an eCheck-funded refund: PENDING, completes after a delay
            refund["status_details"] = {"reason": "ECHECK"}
            refund["_completes_at"] = time.time() + self.pending_demo_seconds
        self.refunds_by_request[request_id] = refund
        total = self._refunded_minor(capture_id, cur)
        refund["seller_payable_breakdown"] = {"total_refunded_amount": {"currency_code": cur,
                                                                        "value": to_str(total, cur)}}
        self._capture_status_after(capture_id)  # PARTIALLY_REFUNDED / REFUNDED, as GET capture reports
        return {k: v for k, v in refund.items() if not k.startswith("_")}

    def complete_refund(self, refund_id):
        """Mock only: the delayed PENDING refund settles (what PayPal does when an eCheck clears)."""
        for r in self.refunds_by_request.values():
            if r["id"] == refund_id:
                r["status"] = "COMPLETED"
                r.pop("status_details", None)
                r["_completes_at"] = None
                if r["_capture"] in self.captures:
                    self._capture_status_after(r["_capture"])
                return {k: v for k, v in r.items() if not k.startswith("_")}
        return None

    def verify_webhook_signature(self, headers, raw_body, webhook_id):
        return "SUCCESS" if headers.get("paypal-transmission-sig") == "valid-mock-signature" else "FAILURE"

    # Disputes (read-only). Tests / demos put dispute objects here; PayPal's shapes, labelled MOCK by id.
    disputes: dict = {}
    disputes_scope = True  # False: the mock behaves like an app without disputes/read-seller

    def has_scope(self, scope):
        return self.disputes_scope

    def _disputes_guard(self):
        if not self.disputes_scope:
            raise PayPalError("Authorization failed due to insufficient permissions (mock)", 403, "NOT_AUTHORIZED",
                              debug_id="mock-debug")

    def list_disputes(self, page_size=10, timeout=None):
        self._disputes_guard()
        return {"items": [{"dispute_id": k, "status": v.get("status")} for k, v in list(self.disputes.items())[:page_size]]}

    def get_dispute(self, dispute_id, timeout=None):
        self._disputes_guard()
        if dispute_id not in self.disputes:
            raise PayPalError("Dispute not found (mock)", 404, "INVALID_RESOURCE_ID")
        return dict(self.disputes[dispute_id])

    def get_refund(self, refund_id, timeout=None):
        for r in self.refunds_by_request.values():
            if r["id"] == refund_id:
                if r.get("_completes_at") is not None:  # mock PENDING demo: completes later
                    if time.time() >= r["_completes_at"]:
                        self.complete_refund(refund_id)
                    return {k: v for k, v in r.items() if not k.startswith("_")}
                return {k: v for k, v in r.items() if not k.startswith("_")}  # the refund's real status
        raise PayPalError("Refund not found (mock)", 404, "RESOURCE_NOT_FOUND")
