"""A live Sandbox check must refuse the wrong deployment before creating test money movement."""

import httpx

from scripts import sandbox_verify


def test_webhook_checks_skip_when_unconfigured_or_local():
    assert sandbox_verify.public_webhook_receiver("https://tradeos-s33z.onrender.com")
    assert not sandbox_verify.public_webhook_receiver("http://localhost:8000")
    assert not sandbox_verify.public_webhook_receiver("http://127.0.0.1:8000")
    assert sandbox_verify.webhook_skip_reason(True, True, "https://demo.example") == (
        "mock mode: PayPal sends nothing")
    assert "PAYPAL_WEBHOOK_ID not configured" in (
        sandbox_verify.webhook_skip_reason(False, False, "https://demo.example") or "")
    assert "no public webhook receiver" in (
        sandbox_verify.webhook_skip_reason(False, True, "http://localhost:8000") or "")
    assert sandbox_verify.webhook_skip_reason(False, True, "https://demo.example") is None


def test_expected_version_mismatch_stops_before_any_post(monkeypatch, capsys):
    requests = []

    def handler(request):
        requests.append((request.method, request.url.path))
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"version": "old", "paypal_mode": "sandbox"})
        raise AssertionError("No order or refund request may be sent to the wrong version")

    client = httpx.Client(base_url="https://example.invalid",
                          transport=httpx.MockTransport(handler))
    monkeypatch.setattr(sandbox_verify, "verify_client", lambda base: client)
    assert sandbox_verify.main("https://example.invalid", expected_version="new") == 1
    assert requests == [("GET", "/healthz")]
    assert "stopped before creating any Sandbox order or refund" in capsys.readouterr().out
    client.close()


def test_expected_version_from_environment_stops_before_any_post(monkeypatch):
    monkeypatch.setenv("TRADEOS_EXPECTED_VERSION", "new")
    requests = []

    def handler(request):
        requests.append((request.method, request.url.path))
        return httpx.Response(200, json={"version": "old", "paypal_mode": "sandbox"})

    client = httpx.Client(base_url="https://example.invalid",
                          transport=httpx.MockTransport(handler))
    monkeypatch.setattr(sandbox_verify, "verify_client", lambda base: client)
    assert sandbox_verify.main("https://example.invalid") == 1
    assert requests == [("GET", "/healthz")]
    client.close()


def test_wrong_paypal_mode_stops_before_any_post(monkeypatch):
    requests = []

    def handler(request):
        requests.append((request.method, request.url.path))
        return httpx.Response(200, json={"version": "abc", "paypal_mode": "mock"})

    client = httpx.Client(base_url="https://example.invalid",
                          transport=httpx.MockTransport(handler))
    monkeypatch.setattr(sandbox_verify, "verify_client", lambda base: client)
    assert sandbox_verify.main("https://example.invalid", expected_version="abc") == 1
    assert requests == [("GET", "/healthz")]
    client.close()
