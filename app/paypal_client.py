"""Thin PayPal REST client (Sandbox by default) using httpx.

APIs used:
  POST /v1/oauth2/token                          (client-credentials)
  POST /v2/checkout/orders                       (intent CAPTURE; optional card payment_source)
  POST /v2/checkout/orders/{id}/capture
  GET  /v2/payments/captures/{id}                (feeds the policy engine)
  POST /v2/payments/captures/{id}/refund         (empty body = full refund, idempotent)
  GET  /v2/payments/refunds/{id}                 (refresh a PENDING refund)
"""

from __future__ import annotations

import threading
import time
from datetime import date
from typing import Any

import httpx

# Official PayPal sandbox test card (developer.paypal.com/tools/sandbox/card-testing).
SANDBOX_TEST_CARD = "4012888888881881"


class PayPalError(Exception):
    def __init__(self, message: str, status_code: int | None = None, name: str = "", debug_id: str = "",
                 details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.name = name
        self.debug_id = debug_id
        self.details = details

    def to_dict(self) -> dict:
        return {
            "message": self.message,
            "status_code": self.status_code,
            "name": self.name,
            "debug_id": self.debug_id,
            "details": self.details,
        }

    def __str__(self) -> str:  # pragma: no cover - trivial
        bits = [self.name or "PAYPAL_ERROR", self.message]
        if self.status_code:
            bits.insert(0, f"HTTP {self.status_code}")
        if self.debug_id:
            bits.append(f"debug_id={self.debug_id}")
        return " · ".join(bits)


def find_link(resource: dict, *rels: str) -> str | None:
    for rel in rels:
        for link in resource.get("links", []) or []:
            if link.get("rel") == rel:
                return link.get("href")
    return None


def first_capture(order: dict) -> dict | None:
    for unit in order.get("purchase_units", []) or []:
        caps = (unit.get("payments") or {}).get("captures") or []
        if caps:
            return caps[0]
    return None


class PayPalClient:
    is_mock = False

    def __init__(self, client_id: str, client_secret: str, base_url: str, timeout: float = 30.0,
                 transport: httpx.BaseTransport | None = None) -> None:
        if not client_id or not client_secret:
            raise PayPalError("PayPal credentials are not configured (PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET).")
        self._id = client_id
        self._secret = client_secret
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport)
        self._token: str | None = None
        self._token_expiry = 0.0
        self._lock = threading.Lock()

    # -- auth -------------------------------------------------------------
    def _access_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._token_expiry - 60:
                return self._token
            try:
                resp = self._http.post(
                    "/v1/oauth2/token",
                    data={"grant_type": "client_credentials"},
                    auth=(self._id, self._secret),
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise PayPalError(f"Could not reach PayPal: {type(exc).__name__}") from exc
            if resp.status_code != 200:
                raise self._error(resp, "OAuth token request failed")
            body = resp.json()
            self._token = body["access_token"]
            self._token_expiry = time.time() + int(body.get("expires_in", 300))
            return self._token

    # -- low level --------------------------------------------------------
    @staticmethod
    def _error(resp: httpx.Response, fallback: str) -> PayPalError:
        try:
            body = resp.json()
        except ValueError:
            body = {}
        message = body.get("message") or body.get("error_description") or fallback
        details = body.get("details")
        if details and isinstance(details, list):
            issue = details[0].get("issue") or ""
            desc = details[0].get("description") or ""
            message = f"{message} ({issue}{': ' + desc if desc else ''})"
        return PayPalError(
            message,
            status_code=resp.status_code,
            name=body.get("name") or body.get("error") or "",
            debug_id=body.get("debug_id") or resp.headers.get("paypal-debug-id", ""),
            details=details,
        )

    def _request(self, method: str, path: str, *, json: Any = None, content: bytes | None = None,
                 request_id: str | None = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self._access_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Prefer": "return=representation",
        }
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        try:
            resp = self._http.request(method, path, json=json, content=content, headers=headers)
        except httpx.HTTPError as exc:
            raise PayPalError(f"Could not reach PayPal: {type(exc).__name__}") from exc
        if resp.status_code >= 400:
            raise self._error(resp, f"{method} {path} failed")
        return resp.json() if resp.content else {}

    # -- Orders v2 --------------------------------------------------------
    @staticmethod
    def _purchase_unit(amount: str, currency: str, reference_id: str, description: str) -> dict:
        return {
            "reference_id": reference_id[:256],
            "description": description[:127],
            "amount": {"currency_code": currency, "value": amount},
        }

    def create_order_with_card(self, amount: str, currency: str, reference_id: str, description: str,
                               request_id: str) -> dict:
        """Create an order paid with a sandbox test card. With intent CAPTURE PayPal
        normally captures immediately (order status COMPLETED)."""
        expiry = f"{date.today().year + 3}-12"
        body = {
            "intent": "CAPTURE",
            "purchase_units": [self._purchase_unit(amount, currency, reference_id, description)],
            "payment_source": {
                "card": {
                    "number": SANDBOX_TEST_CARD,
                    "expiry": expiry,
                    "security_code": "123",
                    "name": "TradeOS Demo Buyer",
                    "billing_address": {
                        "address_line_1": "2211 N First Street",
                        "admin_area_2": "San Jose",
                        "admin_area_1": "CA",
                        "postal_code": "95131",
                        "country_code": "US",
                    },
                }
            },
        }
        return self._request("POST", "/v2/checkout/orders", json=body, request_id=request_id)

    def create_order(self, amount: str, currency: str, reference_id: str, description: str, request_id: str,
                     return_url: str, cancel_url: str) -> dict:
        """Fallback: a normal PayPal-wallet order that needs buyer approval (approve link)."""
        body = {
            "intent": "CAPTURE",
            "purchase_units": [self._purchase_unit(amount, currency, reference_id, description)],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "return_url": return_url,
                        "cancel_url": cancel_url,
                        "user_action": "PAY_NOW",
                        "shipping_preference": "NO_SHIPPING",
                    }
                }
            },
        }
        return self._request("POST", "/v2/checkout/orders", json=body, request_id=request_id)

    def capture_order(self, order_id: str, request_id: str) -> dict:
        return self._request("POST", f"/v2/checkout/orders/{order_id}/capture", content=b"{}",
                             request_id=request_id)

    # -- Payments v2 ------------------------------------------------------
    def get_capture(self, capture_id: str) -> dict:
        return self._request("GET", f"/v2/payments/captures/{capture_id}")

    def refund_capture(self, capture_id: str, request_id: str) -> dict:
        """Full refund: empty JSON body. PayPal-Request-Id makes retries idempotent."""
        return self._request("POST", f"/v2/payments/captures/{capture_id}/refund", content=b"{}",
                             request_id=request_id)

    def get_refund(self, refund_id: str) -> dict:
        return self._request("GET", f"/v2/payments/refunds/{refund_id}")
