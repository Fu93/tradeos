"""The preflight must not certify the wrong build or non-Sandbox demo."""
from __future__ import annotations

import httpx
import pytest

from scripts.submission_preflight import check


SHA = "a" * 40


def test_preflight_accepts_only_the_named_sandbox_build(monkeypatch):
    health = {"ok": True, "version": SHA, "paypal_mode": "sandbox", "llm_configured": True,
              "webhook_configured": True, "auto_enabled": False, "auto_exchange_enabled": False}
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: httpx.Response(200, json=health,
                        request=httpx.Request("GET", a[0])))
    assert check("https://demo.example/", SHA)["passed"] is True
    health["version"] = "b" * 40
    assert check("https://demo.example/", SHA)["failures"]["version"]["observed"] == "b" * 40
    health["version"] = SHA
    health["paypal_mode"] = "mock"
    assert check("https://demo.example/", SHA)["failures"]["paypal_mode"]["observed"] == "mock"
    health["paypal_mode"] = "sandbox"
    health["auto_exchange_enabled"] = True
    assert check("https://demo.example/", SHA)["failures"]["auto_exchange_enabled"]["observed"] is True


def test_preflight_rejects_non_commit_before_network(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: pytest.fail("network must not be called"))
    with pytest.raises(ValueError, match="40-character"):
        check("https://demo.example", "main")
