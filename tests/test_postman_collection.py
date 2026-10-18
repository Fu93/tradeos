"""The Postman collection (dev-time tooling) must stay valid, secret-free and in line with the PayPal client."""
import json
import re
from pathlib import Path

DIR = Path(__file__).resolve().parents[1] / "docs" / "postman"


def _requests(items):
    for it in items:
        if "item" in it:
            yield from _requests(it["item"])
        else:
            yield it


def test_collection_and_environment_are_valid_and_secret_free():
    col = json.loads((DIR / "tradeos-paypal-sandbox.postman_collection.json").read_text())
    env = json.loads((DIR / "tradeos-sandbox.postman_environment.template.json").read_text())
    values = {v["key"]: v for v in env["values"]}
    for key in ("client_id", "client_secret", "access_token", "webhook_id"):
        assert values[key]["value"] == ""
    assert values["client_secret"]["type"] == "secret" and values["access_token"]["type"] == "secret"
    assert values["base_url"]["value"] == "https://api-m.sandbox.paypal.com"
    text = json.dumps(col) + json.dumps(env)
    assert not re.search(r"A[A-Za-z0-9_-]{60,}", text)           # no PayPal-style client ids/tokens
    assert "api-m.paypal.com" not in text                         # sandbox only


def test_collection_covers_the_calls_the_client_makes():
    col = json.loads((DIR / "tradeos-paypal-sandbox.postman_collection.json").read_text())
    calls = {(r["request"]["method"], "/" + "/".join(r["request"]["url"]["path"])) for r in _requests(col["item"])}
    src = (Path(__file__).resolve().parents[1] / "app" / "paypal_client.py").read_text()
    wanted = {("POST", "/v1/oauth2/token"), ("POST", "/v2/checkout/orders"),
              ("POST", "/v2/checkout/orders/{{order_id}}/capture"), ("GET", "/v2/payments/captures/{{capture_id}}"),
              ("POST", "/v2/payments/captures/{{capture_id}}/refund"), ("GET", "/v2/payments/refunds/{{refund_id}}"),
              ("GET", "/v1/customer/disputes"), ("GET", "/v1/customer/disputes/{{dispute_id}}"),
              ("POST", "/v1/notifications/verify-webhook-signature")}
    assert wanted <= calls
    for path in ("/v1/oauth2/token", "/v2/checkout/orders", "/v2/payments/captures/", "/v2/payments/refunds/",
                 "/v1/customer/disputes", "/v1/notifications/verify-webhook-signature"):
        assert path in src                                        # the client really makes the documented calls
    for r in _requests(col["item"]):                              # write calls carry an idempotency key
        if r["request"]["method"] == "POST" and "refund" in r["request"]["url"]["raw"]:
            assert any(h["key"] == "PayPal-Request-Id" for h in r["request"]["header"])
