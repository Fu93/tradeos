"""The preflight must not certify the wrong build or non-Sandbox demo."""
from __future__ import annotations

import httpx
import pytest

from scripts.submission_preflight import check


SHA = "a" * 40


def test_preflight_accepts_only_the_named_sandbox_build(monkeypatch):
    health = {"ok": True, "version": SHA, "paypal_mode": "sandbox", "llm_configured": True,
              "webhook_configured": True, "auto_enabled": False, "auto_exchange_enabled": False,
              "safety_ai_layer": False, "persistence": "ephemeral", "product_catalog": True,
              "safety_rule_version": "safety-gate/3.4.0-main"}
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: httpx.Response(200, json=health,
                        request=httpx.Request("GET", a[0])))
    result = check("https://demo.example/", SHA)
    assert result["passed"] is True
    assert result["observed"]["product_catalog"] is True
    health["version"] = "b" * 40
    assert check("https://demo.example/", SHA)["failures"]["version"]["observed"] == "b" * 40
    health["version"] = SHA
    health["paypal_mode"] = "mock"
    assert check("https://demo.example/", SHA)["failures"]["paypal_mode"]["observed"] == "mock"
    health["paypal_mode"] = "sandbox"
    health["auto_exchange_enabled"] = True
    assert check("https://demo.example/", SHA)["failures"]["auto_exchange_enabled"]["observed"] is True
    health["auto_exchange_enabled"] = False
    health["safety_ai_layer"] = True
    assert check("https://demo.example/", SHA)["failures"]["safety_ai_layer"]["observed"] is True
    health["safety_ai_layer"] = False
    health["persistence"] = "persistent-disk-configured"
    assert check("https://demo.example/", SHA)["failures"]["persistence"]["observed"] == (
        "persistent-disk-configured")


def test_preflight_rejects_non_commit_before_network(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: pytest.fail("network must not be called"))
    with pytest.raises(ValueError, match="40-character"):
        check("https://demo.example", "main")
