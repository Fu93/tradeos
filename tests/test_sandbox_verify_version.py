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


def test_ai_e2e_only_stops_when_llm_not_configured(monkeypatch, capsys):
    def handler(request):
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"version": "abc", "paypal_mode": "sandbox",
                                             "llm_configured": False, "auto_enabled": False,
                                             "auto_exchange_enabled": False})
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    client = httpx.Client(base_url="https://example.invalid",
                          transport=httpx.MockTransport(handler))
    monkeypatch.setattr(sandbox_verify, "verify_client", lambda base: client)
    assert sandbox_verify.main("https://example.invalid", expected_version="abc", ai_e2e_only=True) == 1
    out = capsys.readouterr().out
    assert "llm_configured" in out and "FAIL" in out
    client.close()


def test_ai_e2e_checks_require_live_llm_extractor(capsys):
    """Keyword fallback must not count as an AI end-to-end pass."""
    fails: list[str] = []

    def check(ok: bool, label: str) -> None:
        print(("PASS " if ok else "FAIL ") + label)
        if not ok:
            fails.append(label)

    class FakeClient:
        def post(self, path, data=None):
            assert path == "/cases/free"
            assert data["message"] == sandbox_verify.AI_E2E_MESSAGE
            return httpx.Response(303, headers={"location": "/?case=A-AI00000000000001"},
                                  request=httpx.Request("POST", "https://example.invalid/cases/free"))

        def get(self, path):
            if path.startswith("/api/cases/"):
                return httpx.Response(200, json={
                    "case": {"status": "PENDING_APPROVAL", "extraction": {"extractor": "keywords"},
                             "intent": {"requested_action": "REFUND"}, "note": {"generator": "template"}},
                    "paypal_calls": [],
                }, request=httpx.Request("GET", f"https://example.invalid{path}"))
            raise AssertionError(path)

    sandbox_verify.ai_e2e_checks(FakeClient(), check)  # type: ignore[arg-type]
    assert any("live LLM extractor" in f for f in fails)


def test_ai_e2e_checks_print_measured_llm_chat_completions(capsys):
    """AI e2e must report case.extraction.llm_chat_completions, not a hard-coded 1."""
    fails: list[str] = []
    state = {"approved": False}

    def check(ok: bool, label: str) -> None:
        print(("PASS " if ok else "FAIL ") + label)
        if not ok:
            fails.append(label)

    class FakeClient:
        def post(self, path, data=None):
            if path == "/cases/free":
                return httpx.Response(303, headers={"location": "/?case=A-AI00000000000002"},
                                      request=httpx.Request("POST", "https://example.invalid/cases/free"))
            if path.endswith("/approve"):
                state["approved"] = True
                return httpx.Response(303, headers={"location": "/?case=A-AI00000000000002"},
                                      request=httpx.Request("POST", "https://example.invalid/approve"))
            raise AssertionError(path)

        def get(self, path):
            if path.startswith("/api/cases/"):
                if not state["approved"]:
                    return httpx.Response(200, json={
                        "case": {
                            "status": "PENDING_APPROVAL",
                            "extraction": {"extractor": "llm:openai/gpt-oss-20b",
                                           "llm_unavailable": False, "llm_chat_completions": 2},
                            "intent": {"requested_action": "REFUND"},
                            "note": {"generator": "template"},
                        },
                        "paypal_calls": [],
                    }, request=httpx.Request("GET", f"https://example.invalid{path}"))
                return httpx.Response(200, json={
                    "case": {
                        "status": "REFUND_COMPLETED", "refund_status": "COMPLETED",
                        "refund_id": "REF-1",
                        "extraction": {"extractor": "llm:openai/gpt-oss-20b",
                                       "llm_unavailable": False, "llm_chat_completions": 2},
                        "intent": {"requested_action": "REFUND"},
                        "note": {"generator": "template"},
                    },
                    "paypal_calls": [{"operation": "refund_capture", "debug_id": "dbg-live-1"}],
                }, request=httpx.Request("GET", f"https://example.invalid{path}"))
            if path.endswith("/audit/verify"):
                return httpx.Response(200, json={"ok": True, "entries": 8},
                                      request=httpx.Request("GET", f"https://example.invalid{path}"))
            raise AssertionError(path)

    sandbox_verify.ai_e2e_checks(FakeClient(), check)  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert "AI e2e LLM chat completions: 2" in out
    assert fails == []
