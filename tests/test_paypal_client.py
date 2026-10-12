import json

import httpx
import pytest

from app.paypal_client import SANDBOX_TEST_CARD, PayPalClient, PayPalError, find_link, first_capture


class Recorder:
    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def __call__(self, request: httpx.Request):
        self.requests.append(request)
        key = (request.method, request.url.path)
        for (method, path), resp in self.routes.items():
            if method == request.method and (path == request.url.path or (path.endswith("*") and request.url.path.startswith(path[:-1]))):
                return resp(request) if callable(resp) else resp
        return httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND", "message": str(key)})


TOKEN = httpx.Response(200, json={"access_token": "A21-test", "expires_in": 32400})


def client(routes):
    rec = Recorder({("POST", "/v1/oauth2/token"): TOKEN, **routes})
    return PayPalClient("id", "secret", "https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(rec)), rec


def test_missing_credentials_raise_visible_error():
    with pytest.raises(PayPalError, match="not configured"):
        PayPalClient("", "", "https://api-m.sandbox.paypal.com")


def test_token_is_cached_and_card_order_payload():
    order = {"id": "O1", "status": "COMPLETED",
             "purchase_units": [{"payments": {"captures": [{"id": "C1", "status": "COMPLETED"}]}}]}
    pp, rec = client({("POST", "/v2/checkout/orders"): httpx.Response(201, json=order)})
    pp.create_order_with_card("49.99", "USD", "A-1", "demo", "tradeos-order-A-1")
    pp.create_order_with_card("49.99", "USD", "A-2", "demo", "tradeos-order-A-2")
    assert [r.url.path for r in rec.requests].count("/v1/oauth2/token") == 1
    req = rec.requests[1]
    body = json.loads(req.content)
    assert req.headers["PayPal-Request-Id"] == "tradeos-order-A-1"
    assert req.headers["Authorization"] == "Bearer A21-test"
    assert body["intent"] == "CAPTURE"
    assert body["purchase_units"][0]["amount"] == {"currency_code": "USD", "value": "49.99"}
    assert body["payment_source"]["card"]["number"] == SANDBOX_TEST_CARD
    assert first_capture(order)["id"] == "C1"


def test_refund_is_full_empty_body_and_idempotent_header():
    pp, rec = client({("POST", "/v2/payments/captures/C1/refund"):
                      httpx.Response(201, json={"id": "R1", "status": "COMPLETED"})})
    out = pp.refund_capture("C1", "tradeos-refund-A-1")
    req = rec.requests[-1]
    assert out == {"id": "R1", "status": "COMPLETED"}
    assert req.url.path == "/v2/payments/captures/C1/refund"
    assert json.loads(req.content) == {}  # empty body => full refund
    assert req.headers["PayPal-Request-Id"] == "tradeos-refund-A-1"


def test_get_capture_and_refund():
    pp, _ = client({("GET", "/v2/payments/captures/C1"): httpx.Response(200, json={"id": "C1", "status": "COMPLETED"}),
                    ("GET", "/v2/payments/refunds/R1"): httpx.Response(200, json={"id": "R1", "status": "PENDING"})})
    assert pp.get_capture("C1")["status"] == "COMPLETED"
    assert pp.get_refund("R1")["status"] == "PENDING"


def test_api_errors_are_structured():
    err = {"name": "UNPROCESSABLE_ENTITY", "message": "The requested action could not be performed.",
           "debug_id": "dbg123", "details": [{"issue": "REFUND_AMOUNT_EXCEEDED", "description": "too much"}]}
    pp, _ = client({("POST", "/v2/payments/captures/C1/refund"): httpx.Response(422, json=err)})
    with pytest.raises(PayPalError) as ei:
        pp.refund_capture("C1", "x")
    e = ei.value
    assert e.status_code == 422 and e.name == "UNPROCESSABLE_ENTITY" and e.debug_id == "dbg123"
    assert "REFUND_AMOUNT_EXCEEDED" in e.message


def test_bad_credentials_surface_as_error():
    rec = Recorder({("POST", "/v1/oauth2/token"): httpx.Response(401, json={"error": "invalid_client",
                                                                            "error_description": "Client Authentication failed"})})
    pp = PayPalClient("id", "bad", "https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(rec))
    with pytest.raises(PayPalError, match="Client Authentication failed"):
        pp.get_capture("C1")


def test_find_link():
    order = {"links": [{"rel": "self", "href": "s"}, {"rel": "payer-action", "href": "p"}]}
    assert find_link(order, "payer-action", "approve") == "p"
    assert find_link(order, "approve") is None


# ------------------------------------------------------------------ safe retries (upgrade)
def test_transient_5xx_on_idempotent_call_is_retried(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)  # keep the test fast
    responses = [httpx.Response(503, json={"name": "INTERNAL_ERROR"}),
                 httpx.Response(200, json={"status": "COMPLETED"})]

    def flaky(request):
        return responses.pop(0)

    pp, rec = client({("GET", "/v2/payments/captures/C1"): flaky})
    out = pp.get_capture("C1")
    assert out == {"status": "COMPLETED"}
    assert len([r for r in rec.requests if r.url.path.endswith('/captures/C1')]) == 2  # original + retry


def test_network_timeout_on_idempotent_post_is_retried(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = {"n": 0}

    def timeout_then_ok(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectTimeout("boom")
        return httpx.Response(201, json={"id": "R1", "status": "COMPLETED"})

    pp, _ = client({("POST", "/v2/payments/captures/C1/refund"): timeout_then_ok})
    out = pp.refund_capture("C1", "tradeos-refund-A-1")
    assert out["id"] == "R1"
    assert calls["n"] == 2  # PayPal-Request-Id makes the replay idempotent


def test_non_idempotent_post_is_never_retried(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    pp, rec = client({("POST", "/v2/checkout/orders"):
                      lambda r: httpx.Response(500, json={"name": "INTERNAL_ERROR", "message": "oops"})})
    with pytest.raises(PayPalError):
        pp._request("POST", "/v2/checkout/orders", json={})  # no request_id => single attempt
    assert len([r for r in rec.requests if r.url.path == "/v2/checkout/orders"]) == 1


def test_persistent_5xx_exhausts_retries_and_raises(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    pp, rec = client({("GET", "/v2/payments/refunds/R1"):
                      httpx.Response(502, json={"name": "INTERNAL_ERROR", "message": "bad gateway"})})
    with pytest.raises(PayPalError, match="502"):
        pp.get_refund("R1")
    assert len([r for r in rec.requests if r.url.path == "/v2/payments/refunds/R1"]) == PayPalClient.MAX_ATTEMPTS
