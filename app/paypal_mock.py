"""Offline stand-in for PayPal, used by the test-suite and by the opt-in PAYPAL_MOCK=1 mode.

Every ID it returns starts with MOCK- and the UI shows a red banner when it is active.
It is never used automatically: without credentials the app shows a visible error instead.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone

from .paypal_client import PayPalError


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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

    def _id(self, kind: str) -> str:
        return f"MOCK-{kind}-{next(self._seq):04d}"

    def _capture(self, amount: str, currency: str) -> dict:
        cap = {"id": self._id("CAPTURE"), "status": "COMPLETED", "create_time": _now(),
               "amount": {"currency_code": currency, "value": amount}}
        self.captures[cap["id"]] = cap
        return cap

    def create_order_with_card(self, amount, currency, reference_id, description, request_id):
        if not self.card_capture:
            raise PayPalError("Card payments not enabled for this account (mock)", 422, "UNPROCESSABLE_ENTITY")
        order = {"id": self._id("ORDER"), "status": "COMPLETED",
                 "purchase_units": [{"reference_id": reference_id,
                                     "payments": {"captures": [self._capture(amount, currency)]}}]}
        self.orders[order["id"]] = order
        return order

    def create_order(self, amount, currency, reference_id, description, request_id, return_url, cancel_url):
        order = {"id": self._id("ORDER"), "status": "PAYER_ACTION_REQUIRED", "_amount": (amount, currency),
                 "links": [{"rel": "payer-action", "href": f"https://www.sandbox.paypal.com/checkoutnow?token=mock"}]}
        self.orders[order["id"]] = order
        return order

    def capture_order(self, order_id, request_id):
        order = self.orders[order_id]
        amount, currency = order.get("_amount", ("49.99", "USD"))
        order.update({"status": "COMPLETED",
                      "purchase_units": [{"payments": {"captures": [self._capture(amount, currency)]}}]})
        return order

    def get_capture(self, capture_id):
        return dict(self.captures[capture_id])

    is_sandbox = True

    def refund_capture(self, capture_id, request_id, note_to_payer=None, mock_response=None):
        if self.fail_refund:
            raise PayPalError("Refund failed (mock)", 422, "UNPROCESSABLE_ENTITY")
        if mock_response:  # mirrors PayPal-Mock-Response negative testing
            raise PayPalError(f"The requested action could not be completed (mock) ({mock_response})", 422,
                              "UNPROCESSABLE_ENTITY", debug_id="mock-debug",
                              details=[{"issue": mock_response}])
        if request_id in self.refunds_by_request:  # idempotent, like PayPal-Request-Id
            return self.refunds_by_request[request_id]
        cap = self.captures[capture_id]
        if any(r["_capture"] == capture_id for r in self.refunds_by_request.values()):
            raise PayPalError("Capture has already been fully refunded (mock)", 422, "UNPROCESSABLE_ENTITY",
                              details=[{"issue": "CAPTURE_FULLY_REFUNDED"}])
        refund = {"id": self._id("REFUND"), "status": self.refund_status, "create_time": _now(),
                  "amount": dict(cap["amount"]), "_capture": capture_id,
                  "seller_payable_breakdown": {"total_refunded_amount": dict(cap["amount"])}}
        if note_to_payer:
            refund["note_to_payer"] = note_to_payer[:255]
        self.refunds_by_request[request_id] = refund
        return refund

    def verify_webhook_signature(self, headers, raw_body, webhook_id):
        return "SUCCESS" if headers.get("paypal-transmission-sig") == "valid-mock-signature" else "FAILURE"

    def get_refund(self, refund_id):
        for r in self.refunds_by_request.values():
            if r["id"] == refund_id:
                return dict(r, status="COMPLETED")
        raise PayPalError("Refund not found (mock)", 404, "RESOURCE_NOT_FOUND")
