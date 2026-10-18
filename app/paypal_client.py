"""Thin PayPal REST client (Sandbox by default) using httpx.

APIs used:
  POST /v1/oauth2/token                          (client-credentials)
  POST /v2/checkout/orders                       (intent CAPTURE; optional card payment_source)
  POST /v2/checkout/orders/{id}/capture
  GET  /v2/payments/captures/{id}                (feeds the policy engine)
  POST /v2/payments/captures/{id}/refund         (no amount = full refund, idempotent; optional note_to_payer)
  GET  /v2/payments/refunds/{id}                 (refresh a PENDING refund)
  POST /v1/notifications/verify-webhook-signature (webhook: second, independent confirmation)
  GET/POST /v1/notifications/webhooks            (one-off webhook registration script)
  GET  /v1/customer/disputes[/{id}]              (Disputes, READ-ONLY: needs the disputes/read-seller scope)

Sandbox negative testing: ``refund_capture(..., mock_response=CODE)`` sends the
``PayPal-Mock-Response`` header so PayPal itself returns a real error response. It is
refused outside the sandbox.
"""

from __future__ import annotations

import json as _json
import threading
import time
from datetime import date
from typing import Any
from urllib.parse import quote

import httpx

# Official PayPal sandbox test card (developer.paypal.com/tools/sandbox/card-testing).
SANDBOX_TEST_CARD = "4012888888881881"
# Scope the app needs to READ disputes (GET /v1/customer/disputes). TradeOS never uses the write scopes.
DISPUTES_READ_SCOPE = "https://uri.paypal.com/services/disputes/read-seller"


class PayPalError(Exception):
    def __init__(self, message: str, status_code: int | None = None, name: str = "", debug_id: str = "",
                 details: Any = None, sent: bool = True) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.name = name
        self.debug_id = debug_id
        self.details = details
        # False when the error was raised locally, before any request reached PayPal (the sandbox
        # guards below, missing credentials / token): the outcome is then certain — this request
        # made no refund — and no "outcome unknown" check is needed. Network errors keep sent=True:
        # the request may or may not have reached PayPal.
        self.sent = sent

    def to_dict(self) -> dict:
        return {
            "message": self.message,
            "status_code": self.status_code,
            "name": self.name,
            "debug_id": self.debug_id,
            "details": self.details,
            "sent": self.sent,
        }

    def __str__(self) -> str:  # pragma: no cover - trivial
        bits = [self.name or "PAYPAL_ERROR", self.message]
        if self.status_code:
            bits.insert(0, f"HTTP {self.status_code}")
        if self.debug_id:
            bits.append(f"debug_id={self.debug_id}")
        return " · ".join(bits)


def is_scope_error(exc: "PayPalError") -> bool:
    """PayPal refused a read because the app is not authorised for it (missing scope / permission)."""
    text = f"{exc.name} {exc.message}".lower()
    return exc.status_code in (401, 403) or "not_authorized" in text or "scope" in text or "permission" in text


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
                 transport: httpx.BaseTransport | None = None, allow_live: bool = False) -> None:
        if not client_id or not client_secret:
            raise PayPalError("PayPal credentials are not configured (PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET).",
                              sent=False)
        self._id = client_id
        self._secret = client_secret
        self.base_url = base_url.rstrip("/")
        if not self.is_sandbox and not allow_live:
            # Fail at construction, before any card payload or refund can reach a live account.
            raise PayPalError("PAYPAL_BASE_URL is not the PayPal Sandbox — refusing to continue. "
                              "Point it at https://api-m.sandbox.paypal.com or set TRADEOS_ALLOW_LIVE=1.")
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport)
        self._token: str | None = None
        self._token_expiry = 0.0
        self._scopes: frozenset[str] | None = None  # from the token response ("scope"), None until known
        self._lock = threading.Lock()

    # -- auth -------------------------------------------------------------
    def _access_token(self, timeout: float | None = None) -> str:
        with self._lock:
            if self._token and time.time() < self._token_expiry - 60:
                return self._token
            try:
                resp = self._http.post(
                    "/v1/oauth2/token",
                    data={"grant_type": "client_credentials"},
                    auth=(self._id, self._secret),
                    headers={"Accept": "application/json"},
                    **({"timeout": timeout} if timeout is not None else {}),  # type: ignore[arg-type]  # dict[str, float] is the only key
                )
            except httpx.HTTPError as exc:
                # The API request itself was never sent: without a token there is no call.
                raise PayPalError(f"Could not reach PayPal: {type(exc).__name__}", sent=False) from exc
            if resp.status_code != 200:
                token_err = self._error(resp, "OAuth token request failed")
                token_err.sent = False  # same: nothing was sent without a token
                raise token_err
            body = resp.json()
            self._token = body["access_token"]
            self._token_expiry = time.time() + int(body.get("expires_in", 300))
            scope = body.get("scope")
            self._scopes = frozenset(scope.split()) if isinstance(scope, str) else None
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
                 request_id: str | None = None, extra_headers: dict | None = None,
                 timeout: float | None = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self._access_token(timeout)}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Prefer": "return=representation",
        }
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        headers.update(extra_headers or {})
        try:
            kw: dict[str, Any] = {"timeout": timeout} if timeout is not None else {}
            resp = self._http.request(method, path, json=json, content=content, headers=headers, **kw)
        except httpx.HTTPError as exc:
            raise PayPalError(f"Could not reach PayPal: {type(exc).__name__}") from exc
        # Kept for the evidence timeline (successful calls too). Never the Authorization header.
        self.last_debug_id = resp.headers.get("paypal-debug-id", "") or None
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
        if not self.is_sandbox:
            # Same fail-closed rule as PayPal-Mock-Response below: the hard-coded test card
            # must never reach a live endpoint.
            raise PayPalError("The sandbox test card is only allowed against the PayPal Sandbox.", sent=False)
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
    def get_capture(self, capture_id: str, timeout: float | None = None) -> dict:
        return self._request("GET", f"/v2/payments/captures/{capture_id}", timeout=timeout)

    @property
    def is_sandbox(self) -> bool:
        return "sandbox" in self.base_url

    def refund_capture(self, capture_id: str, request_id: str, note_to_payer: str | None = None,
                       mock_response: str | None = None) -> dict:
        """Full refund (no amount). PayPal-Request-Id makes retries idempotent.

        ``note_to_payer`` (<= 255 chars) is shown to the buyer with the refund.
        ``mock_response`` = sandbox negative-testing error code (sandbox only).
        """
        extra = {}
        if mock_response:
            if not self.is_sandbox:
                raise PayPalError("PayPal-Mock-Response negative testing is only allowed in the sandbox.",
                                  sent=False)
            extra["PayPal-Mock-Response"] = _json.dumps({"mock_application_codes": mock_response})
        body: dict = {}
        if note_to_payer:
            body["note_to_payer"] = note_to_payer[:255]
        content = _json.dumps(body, ensure_ascii=False).encode() if body else b"{}"
        return self._request("POST", f"/v2/payments/captures/{capture_id}/refund", content=content,
                             request_id=request_id, extra_headers=extra)

    def get_refund(self, refund_id: str, timeout: float | None = None) -> dict:
        return self._request("GET", f"/v2/payments/refunds/{refund_id}", timeout=timeout)

    # -- Webhooks v1 ------------------------------------------------------
    def verify_webhook_signature(self, headers: dict, raw_body: bytes, webhook_id: str) -> str:
        """Postback verification. Returns PayPal's verification_status (SUCCESS / FAILURE).

        The event is embedded byte-for-byte (not re-serialised), so the signature PayPal
        computed over the original body still matches.
        """
        h = {k.lower(): v for k, v in headers.items()}
        meta = {
            "auth_algo": h.get("paypal-auth-algo", ""),
            "cert_url": h.get("paypal-cert-url", ""),
            "transmission_id": h.get("paypal-transmission-id", ""),
            "transmission_sig": h.get("paypal-transmission-sig", ""),
            "transmission_time": h.get("paypal-transmission-time", ""),
            "webhook_id": webhook_id,
        }
        payload = _json.dumps(meta)[:-1] + ', "webhook_event": ' + raw_body.decode("utf-8") + "}"
        result = self._request("POST", "/v1/notifications/verify-webhook-signature", content=payload.encode())
        return result.get("verification_status", "FAILURE")

    # -- Disputes v1 (READ-ONLY: GET only; no evidence, accept, appeal, offer or message calls exist here) --
    def has_scope(self, scope: str) -> bool | None:
        """True / False from the OAuth token response; None if PayPal did not report scopes."""
        self._access_token()
        return None if self._scopes is None else scope in self._scopes

    def list_disputes(self, page_size: int = 10, timeout: float | None = None) -> dict:
        """GET /v1/customer/disputes (summary items). Needs the disputes/read-seller scope."""
        return self._request("GET", f"/v1/customer/disputes?page_size={max(1, min(int(page_size), 50))}",
                             timeout=timeout)

    def get_dispute(self, dispute_id: str, timeout: float | None = None) -> dict:
        """GET /v1/customer/disputes/{id}. Needs the disputes/read-seller scope."""
        return self._request("GET", f"/v1/customer/disputes/{quote(str(dispute_id), safe='')}", timeout=timeout)

    def list_webhooks(self) -> dict:
        return self._request("GET", "/v1/notifications/webhooks")

    def update_webhook_events(self, webhook_id: str, event_types: list[str]) -> dict:
        """PATCH /v1/notifications/webhooks/{id}: replace the subscribed event list (same webhook id)."""
        return self._request("PATCH", f"/v1/notifications/webhooks/{webhook_id}",
                             json=[{"op": "replace", "path": "/event_types",
                                    "value": [{"name": n} for n in event_types]}])

    def create_webhook(self, url: str, event_types: list[str]) -> dict:
        return self._request("POST", "/v1/notifications/webhooks",
                             json={"url": url, "event_types": [{"name": n} for n in event_types]})
