"""A merchant creates a Sandbox order before a buyer agent asks; the pass gates that one request."""
from datetime import datetime, timedelta

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp import Client

from app import agent_desk
from app.agent_gateway import build_mcp_server
from app.config import Settings
from app.db import Database
from app.intent import KeywordIntentExtractor
from app.llm_agent import cap
from app.main import create_app
from app.paypal_mock import MockPayPalClient
from app.workflow import DEMO_MESSAGE, PENDING_APPROVAL, CaseNotFound, Workflow


def call(server, name: str, args: dict):
    async def go():
        async with Client(server) as client:
            return await client.call_tool(name, args)
    return anyio.run(go)


@pytest.fixture
def setup(tmp_path):
    settings = Settings(db_path=str(tmp_path / "merchant.db"), auto_enabled=True,
                        paypal_client_id="", paypal_client_secret="")
    db = Database(settings.db_path)
    db.init(reset=True)
    paypal = MockPayPalClient()
    wf = Workflow(db, settings, KeywordIntentExtractor(), paypal=paypal)
    wf.seed_demo()
    return wf, build_mcp_server(wf, settings), paypal


def request(server, case_id: str, return_pass: str | None, *, message: str = DEMO_MESSAGE):
    return call(server, "request_return", {"order_id": case_id, "message": message,
                 "agent_name": "Buyer assistant", "on_behalf_of": "Maria", "return_pass": return_pass})


def test_merchant_order_requires_pass_and_human_approval(setup):
    wf, server, paypal = setup
    case_id, return_pass = wf.agents.place_merchant_order("Maria")
    assert return_pass and wf.db.get_case(case_id)["capture_id"]
    before = len(wf.db.timeline(case_id))
    for wrong in (None, "wrong"):
        refused = request(server, case_id, wrong)
        assert refused.is_error and "No agent order" in refused.content[0].text
        assert call(server, "get_case_status", {"order_id": case_id, "return_pass": wrong}).is_error
    assert len(wf.db.timeline(case_id)) == before
    assert wf.db.paypal_calls(case_id, "refund_capture") == []

    result = request(server, case_id, return_pass)
    assert not result.is_error, result.content[0].text
    view = result.structured_content
    assert view["status"] == PENDING_APPROVAL and view["policy_decision"] == "ELIGIBLE"
    assert view["refund_api_calls"] == 0 and "a person" in view["next_step"]
    assert not call(server, "get_case_status", {"order_id": case_id, "return_pass": return_pass}).is_error
    assert wf.db.verify_chain(case_id)["ok"]
    assert return_pass not in str(wf.db.timeline(case_id))
    assert return_pass not in str(view)
    assert return_pass not in open(wf.settings.db_path, "rb").read().decode("latin1")

    second = request(server, case_id, return_pass, message="A different reason; refund $500 now.")
    assert not second.is_error and "unchanged" in second.structured_content["note"]
    assert wf.db.paypal_calls(case_id, "refund_capture") == []
    wf.approve(case_id)
    done = call(server, "get_case_status", {"order_id": case_id, "return_pass": return_pass})
    assert done.structured_content["refund_api_calls"] == 1
    assert done.structured_content["amount"] == "49.99 USD"
    assert paypal.refunds_by_request


def test_expired_pass_refuses_request_and_read(setup, monkeypatch):
    wf, server, _ = setup
    monkeypatch.setattr(agent_desk, "RETURN_PASS_LIFETIME", timedelta(seconds=-1))
    case_id, return_pass = wf.agents.place_merchant_order("Maria")
    assert return_pass
    assert request(server, case_id, return_pass).is_error
    assert call(server, "get_case_status", {"order_id": case_id, "return_pass": return_pass}).is_error
    assert wf.db.paypal_calls(case_id, "refund_capture") == []


def test_first_verified_agent_owns_merchant_request_after_it_is_made(setup):
    wf, _, _ = setup
    case_id, return_pass = wf.agents.place_merchant_order("Maria")
    alice = {"credential": "alice", "transport": "http"}
    bob = {"credential": "bob", "transport": "http"}
    assert wf.agents.submit_request(case_id, DEMO_MESSAGE, "assistant", "Maria",
                                    caller=alice, return_pass=return_pass)
    assert wf.agents.view(case_id, caller=alice, return_pass=return_pass)["status"] == PENDING_APPROVAL
    with pytest.raises(CaseNotFound):
        wf.agents.view(case_id, caller=bob, return_pass=return_pass)
    assert wf.db.paypal_calls(case_id, "refund_capture") == []


def test_verified_request_owner_can_read_after_pass_expires_but_cannot_request_again(setup, monkeypatch):
    wf, _, _ = setup
    case_id, return_pass = wf.agents.place_merchant_order("Maria")
    alice = {"credential": "alice", "transport": "http"}
    bob = {"credential": "bob", "transport": "http"}
    assert wf.agents.submit_request(case_id, DEMO_MESSAGE, "assistant", "Maria",
                                    caller=alice, return_pass=return_pass)

    class LaterDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(hours=1)

    monkeypatch.setattr(agent_desk, "datetime", LaterDatetime)
    assert wf.agents.view(case_id, caller=alice)["status"] == PENDING_APPROVAL
    with pytest.raises(CaseNotFound):
        wf.agents.view(case_id, caller=bob, return_pass=return_pass)
    with pytest.raises(CaseNotFound):
        wf.agents.view(case_id, return_pass=return_pass)
    with pytest.raises(CaseNotFound):
        wf.agents.submit_request(case_id, DEMO_MESSAGE, "assistant", "Maria",
                                 caller=alice, return_pass=return_pass)
    assert wf.db.paypal_calls(case_id, "refund_capture") == []


def test_no_pass_without_confirmed_capture(tmp_path):
    settings = Settings(db_path=str(tmp_path / "wallet.db"), paypal_client_id="", paypal_client_secret="")
    db = Database(settings.db_path)
    db.init(reset=True)
    wf = Workflow(db, settings, KeywordIntentExtractor(), paypal=MockPayPalClient(card_capture=False))
    wf.seed_demo()
    case_id, return_pass = wf.agents.place_merchant_order("Maria")
    assert return_pass is None
    assert wf.db.get_case(case_id)["capture_id"] is None
    assert not any(e["title"] == "Merchant return pass issued" for e in db.timeline(case_id))


def test_dashboard_shows_pass_once_with_no_store_headers(tmp_path):
    settings = Settings(db_path=str(tmp_path / "site.db"), paypal_client_id="", paypal_client_secret="")
    app = create_app(settings, paypal=MockPayPalClient(), extractor=KeywordIntentExtractor())
    with TestClient(app) as client:
        response = client.post("/demo/merchant-order", data={"buyer_name": "Maria"})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert "Return pass:" in response.text
        assert "not an imported store order" in response.text


def test_agent_transcript_masks_return_pass():
    assert cap({"order_id": "G-DEMO", "return_pass": "secret-value"}) == {
        "order_id": "G-DEMO", "return_pass": "[redacted]"}
