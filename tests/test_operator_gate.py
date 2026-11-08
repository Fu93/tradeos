"""The optional private-Sandbox gate blocks UI actions before they reach the workflow."""

import base64
from unittest.mock import MagicMock

import pytest
import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.notes import TemplateNoteWriter
from app.paypal_mock import MockPayPalClient
from tests.helpers import FakeExtractor
from scripts.sandbox_verify import verify_client

TOKEN = "private-sandbox-operator-token-123456"


def client_with_gate(settings):
    private = Settings(db_path=settings.db_path, operator_token=TOKEN, mcp_enabled=False)
    paypal = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    app = create_app(settings=private, paypal=paypal, extractor=FakeExtractor(), note_writer=TemplateNoteWriter())
    return TestClient(app), app.state.workflow


def auth(username="operator", password=TOKEN):
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def test_operator_gate_blocks_reads_and_writes_before_workflow(settings):
    client, wf = client_with_gate(settings)
    before = len(wf.db.list_cases())
    for path in ("/", "/api/inbox", "/audit/heads"):
        response = client.get(path)
        assert response.status_code == 401
        assert response.headers["www-authenticate"].startswith("Basic ")
        assert response.headers["cache-control"] == "private, no-store"
    for headers in ({}, {"Authorization": "Basic ???"}, auth("wrong"), auth(password="wrong")):
        assert client.post("/demo/run/B", headers=headers, follow_redirects=False).status_code == 401
    assert len(wf.db.list_cases()) == before


def test_operator_gate_allows_authorized_browser_and_keeps_csrf(settings):
    client, _ = client_with_gate(settings)
    dashboard = client.get("/", headers=auth())
    assert dashboard.status_code == 200 and TOKEN not in dashboard.text
    assert TOKEN not in client.get("/healthz").text
    assert client.post("/demo/run/B", headers=auth(), follow_redirects=False).status_code == 303
    blocked = client.post("/demo/run/B", headers={**auth(), "Origin": "https://attacker.example"},
                          follow_redirects=False)
    assert blocked.status_code == 403
    assert blocked.headers["cache-control"] == "private, no-store"


def test_public_health_static_and_webhook_bypass_operator_gate(settings):
    client, _ = client_with_gate(settings)
    assert client.get("/healthz").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    # A webhook still reaches its own validation path without browser credentials.
    assert client.post("/webhooks/paypal", content=b"bad json").status_code == 400


def test_private_mode_requires_agent_gateway_credentials(settings):
    private = Settings(db_path=settings.db_path, operator_token=TOKEN)
    with pytest.raises(ValueError, match="requires MCP credentials"):
        create_app(settings=private, paypal=MockPayPalClient(), extractor=FakeExtractor())
    with pytest.raises(ValueError, match="distinct MCP tokens"):
        create_app(settings=Settings(db_path=settings.db_path, operator_token=TOKEN, mcp_token="weak"),
                   paypal=MockPayPalClient(), extractor=FakeExtractor())
    with pytest.raises(ValueError, match="distinct MCP tokens"):
        create_app(settings=Settings(db_path=settings.db_path, operator_token=TOKEN, mcp_token=TOKEN),
                   paypal=MockPayPalClient(), extractor=FakeExtractor())


def test_private_gateway_uses_its_own_bearer_gate(settings):
    private = Settings(db_path=settings.db_path, operator_token=TOKEN,
                       mcp_token="separate-agent-gateway-token-123456")
    app = create_app(settings=private, paypal=MockPayPalClient(), extractor=FakeExtractor())
    client = TestClient(app, base_url="http://localhost")
    assert client.post("/mcp", content=b"{}", follow_redirects=False).status_code == 401
    assert client.get("/mcp-not-really").status_code == 401


def test_operator_token_is_loaded_and_rejects_short_value(monkeypatch):
    monkeypatch.setenv("TRADEOS_OPERATOR_TOKEN", TOKEN)
    assert Settings.from_env().operator_token == TOKEN
    with pytest.raises(ValueError, match="at least 24 characters"):
        Settings(operator_token="short")
    with pytest.raises(ValueError, match="HTTPS public URL"):
        Settings(operator_token=TOKEN, public_base_url="http://private.example")


def test_deploy_verifier_sends_operator_credentials_only_when_configured(monkeypatch):
    seen = []
    transport = httpx.MockTransport(lambda request: seen.append(request.headers.get("authorization"))
                                    or httpx.Response(200))
    monkeypatch.delenv("TRADEOS_OPERATOR_TOKEN", raising=False)
    with verify_client("https://private.example", transport) as client:
        client.get("/healthz")
    monkeypatch.setenv("TRADEOS_OPERATOR_TOKEN", TOKEN)
    with verify_client("https://private.example", transport) as client:
        client.get("/audit/heads")
    assert seen == [None, auth()["Authorization"]]
