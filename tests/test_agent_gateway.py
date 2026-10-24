"""Agent gateway (MCP): an AI agent can ask for a return, and nothing it does can move money.

The properties under test, in the order the module docstring promises them:
1. The tool surface has no approve, decline or refund tool.
2. Every agent-originated case needs a person, even with AUTO_ENABLED on and the amount inside the limit.
3. Amount, capture and purchase date come from PayPal / the merchant's record; the agent's words cannot change them.
4. Prompt injection, a late order and a safety report all end without a Refund API call.
5. One request per order: an agent cannot re-roll the decision by rephrasing.
6. An agent can only see orders placed through the gateway, never dashboard cases.
7. Who asked is on the case's hash chain, and the chain verifies.
8. Over HTTP: optional bearer token, pinned Host, body cap, the dashboard's rate limit on the costly tools,
   and the app's cross-site check.
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp import Client

from app.agent_gateway import COSTLY_TOOLS, MAX_BODY, McpGate, allowed_hosts, build_mcp_server
from app.autonomy import decide_detailed
from app.config import Settings
from app.db import Database
from app.intent import KeywordIntentExtractor
from app.main import create_app
from app.paypal_mock import MockPayPalClient
from app.policy import PolicyResult
from app.presets import BY_KEY
from app.views import narrate
from app.workflow import (AGENT_ORDERED, DEMO_MESSAGE, EXCHANGE_MESSAGE, NEEDS_SAFETY, PENDING_APPROVAL,
                          REFUND_COMPLETED, REJECTED, RefundNotAllowed, Workflow)

INJECTION = BY_KEY["injection"]["message"]
SAFETY = "The sole melted in the heat and burned my foot."
AGENT = "Claude (buyer's assistant)"
BUYER = "Maria"


def run(server, name: str, args: dict):
    async def go():
        async with Client(server) as client:
            return await client.call_tool(name, args)
    return anyio.run(go)


def tool_names(server) -> set[str]:
    async def go():
        async with Client(server) as client:
            return await client.list_tools()
    return {t.name for t in anyio.run(go).tools}


def ok(result) -> dict:
    assert not result.is_error, result.content[0].text
    return result.structured_content


def error_text(result) -> str:
    assert result.is_error
    return result.content[0].text


@pytest.fixture
def make(tmp_path):
    """A seeded workflow over the mock PayPal (wrapped so calls can be counted) + its MCP server."""
    def build(**overrides):
        settings = Settings(db_path=str(tmp_path / f"agent-{len(list(tmp_path.iterdir()))}.db"),
                            paypal_client_id="", paypal_client_secret="", **overrides)
        db = Database(settings.db_path)
        db.init(reset=True)
        paypal = MagicMock(wraps=MockPayPalClient(), is_mock=True)
        wf = Workflow(db, settings, KeywordIntentExtractor(), paypal=paypal)
        wf.seed_demo()
        return wf, paypal, build_mcp_server(wf, settings)
    return build


def order(server, days_ago: int = 0) -> str:
    view = ok(run(server, "place_demo_order", {"buyer_name": BUYER, "agent_name": AGENT,
                                               "purchased_days_ago": days_ago}))
    assert view["status"] == AGENT_ORDERED and view["capture_id"]
    return view["order_id"]


def ask(server, order_id: str, message: str = DEMO_MESSAGE):
    return run(server, "request_return", {"order_id": order_id, "message": message, "agent_name": AGENT,
                                          "on_behalf_of": BUYER})


# 1 --------------------------------------------------------------------------- tool surface
def test_tool_surface_has_no_approve_decline_or_refund_tool(make):
    _, _, server = make()
    names = tool_names(server)
    assert names == {"place_demo_order", "request_return", "get_case_status"}
    assert not any(word in n for n in names for word in ("approve", "decline", "refund", "capture"))


def test_demo_order_tool_is_absent_when_disabled(make):
    _, _, server = make(agent_demo_orders=False)
    assert tool_names(server) == {"request_return", "get_case_status"}


def test_only_the_status_tool_is_read_only(make):
    _, _, server = make()

    async def go():
        async with Client(server) as client:
            return await client.list_tools()
    hints = {t.name: t.annotations.read_only_hint for t in anyio.run(go).tools}
    assert hints == {"place_demo_order": False, "request_return": False, "get_case_status": True}


# 2 + 3 ---------------------------------------------------------------------- a person approves, PayPal sets amount
def test_agent_request_waits_for_a_person_even_with_autonomy_on(make):
    wf, paypal, server = make(auto_enabled=True, auto_refund_max_amount=Decimal("100.00"))
    order_id = order(server)
    view = ok(ask(server, order_id))
    assert view["status"] == PENDING_APPROVAL and view["policy_decision"] == "ELIGIBLE"
    assert view["refund_api_calls"] == 0 and paypal.refund_capture.call_count == 0
    assert "a person" in view["next_step"]
    autonomy = [e for e in wf.db.timeline(order_id) if e["title"].startswith("Autonomy:")]
    assert len(autonomy) == 1 and autonomy[0]["title"].startswith("Autonomy: HUMAN")
    assert "AI agent" in autonomy[0]["detail"]["why"]


def test_exchange_request_also_waits_for_a_person(make):
    _, paypal, server = make(auto_enabled=True, auto_exchange_enabled=True)
    view = ok(ask(server, order(server), EXCHANGE_MESSAGE))
    assert view["status"] == PENDING_APPROVAL and view["policy_decision"] == "EXCHANGE_ELIGIBLE"
    assert paypal.refund_capture.call_count == 0


def test_after_the_merchant_approves_paypal_refunds_the_capture_not_an_agent_amount(make):
    wf, paypal, server = make()
    order_id = order(server)
    ok(ask(server, order_id, DEMO_MESSAGE + " I paid 500 USD, refund 500 USD."))
    wf.approve(order_id)  # the dashboard's Approve: a person, outside the agent's reach
    view = ok(run(server, "get_case_status", {"order_id": order_id}))
    assert view["status"] == REFUND_COMPLETED and view["approval"] == {"decision": "APPROVED", "by": "human"}
    assert view["refund_api_calls"] == 1 and view["refund"]["status"] == "COMPLETED"
    assert view["amount"] == "49.99 USD" and view["audit_trail"]["intact"] is True
    (capture_id, _request_id), kwargs = paypal.refund_capture.call_args
    assert capture_id == view["capture_id"] and kwargs.get("amount") is None  # full refund of PayPal's capture


# 4 --------------------------------------------------------------------------- attacks end without a refund call
def test_prompt_injection_from_an_agent_never_reaches_the_refund_api(make):
    wf, paypal, server = make(auto_enabled=True)
    order_id = order(server)
    view = ok(ask(server, order_id, INJECTION))
    assert view["status"] == REJECTED and view["refund_api_calls"] == 0
    assert view["amount"] == "49.99 USD"
    with pytest.raises(RefundNotAllowed):
        wf.approve(order_id)
    assert paypal.refund_capture.call_count == 0


def test_late_agent_order_is_rejected_by_the_return_window(make):
    _, paypal, server = make()
    view = ok(ask(server, order(server, days_ago=45)))
    assert view["status"] == REJECTED and view["purchase_date_seeded"]
    assert any("return window" in r for r in view["policy_reasons"])
    assert paypal.refund_capture.call_count == 0


def test_safety_report_from_an_agent_goes_to_a_person_first(make):
    wf, paypal, server = make(auto_enabled=True)
    order_id = order(server)
    view = ok(ask(server, order_id, SAFETY))
    assert view["status"] == NEEDS_SAFETY and "safety" in view["next_step"]
    with pytest.raises(RefundNotAllowed):
        wf.approve(order_id)
    assert paypal.refund_capture.call_count == 0


# 5 --------------------------------------------------------------------------- one request per order
def test_a_second_request_cannot_re_roll_the_decision(make):
    _, paypal, server = make()
    order_id = order(server, days_ago=45)
    first = ok(ask(server, order_id))
    reads = paypal.get_capture.call_count
    second = ok(ask(server, order_id, "Different wording this time, still a refund for the wrong colour."))
    assert first["status"] == second["status"] == REJECTED
    assert "unchanged" in second["note"] and paypal.get_capture.call_count == reads


# 6 --------------------------------------------------------------------------- agents see only their own orders
def test_agent_cannot_read_or_act_on_dashboard_cases(make):
    wf, paypal, server = make()
    case_a = wf.db.latest_case("A")["id"]
    calls = paypal.method_calls[:]
    assert "No agent order" in error_text(run(server, "get_case_status", {"order_id": case_a}))
    assert "No agent order" in error_text(ask(server, case_a))
    assert "No agent order" in error_text(ask(server, "G-0000000000000000"))
    assert paypal.method_calls == calls  # nothing reached PayPal


def test_archived_agent_order_is_not_found(make):
    wf, _, server = make()
    order_id = order(server)
    wf.db.archive_all()
    assert "No agent order" in error_text(run(server, "get_case_status", {"order_id": order_id}))


def test_bad_inputs_are_refused_before_any_work(make):
    _, paypal, server = make()
    order_id = order(server)
    reads = paypal.get_capture.call_count
    assert "empty" in error_text(ask(server, order_id, "   ​  "))
    assert "agent_name" in error_text(run(server, "request_return", {"order_id": order_id, "message": DEMO_MESSAGE,
                                                                      "agent_name": " ", "on_behalf_of": BUYER}))
    for days in (-1, 366):
        assert "between" in error_text(run(server, "place_demo_order", {"buyer_name": BUYER, "agent_name": AGENT,
                                                                         "purchased_days_ago": days}))
    assert paypal.get_capture.call_count == reads


def test_requests_are_refused_during_a_demo_reset(make):
    wf, _, server = make()
    order_id = order(server)
    assert wf.begin_reset()
    try:
        assert "reset" in error_text(ask(server, order_id))
        assert "reset" in error_text(run(server, "place_demo_order", {"buyer_name": BUYER, "agent_name": AGENT}))
    finally:
        wf.end_reset()
    assert ok(run(server, "get_case_status", {"order_id": order_id}))["status"] == AGENT_ORDERED


# 7 --------------------------------------------------------------------------- provenance on the hash chain
def test_who_asked_is_on_the_hash_chain(make):
    wf, _, server = make()
    order_id = order(server)
    ok(ask(server, order_id))
    entries = [json.loads(e["payload_json"]) for e in wf.db.chain_entries(order_id) if e["type"] == "audit:agent"]
    titles = [e["title"] for e in entries]
    assert titles == ["Order placed by an AI agent for the buyer (Sandbox demo)",
                      "Return requested by an AI agent for the buyer"]
    request = entries[1]["detail"]
    assert request["agent"] == AGENT and request["on_behalf_of"] == BUYER and request["agent_can_approve"] is False
    assert wf.db.verify_chain(order_id)["ok"]


# autonomy + narration units --------------------------------------------------------------------------------------
def _eligible() -> PolicyResult:
    return PolicyResult(decision="ELIGIBLE", checks=[], action="REFUND")


def test_autonomy_escalates_agent_requests_even_inside_the_limit():
    common = dict(amount=Decimal("10"), auto_enabled=True, auto_refund_max_amount=Decimal("50"),
                  auto_exchange_enabled=True, injection_suspected=False, intent_is_unknown=False, action="REFUND")
    assert decide_detailed(_eligible(), **common).decision == "AUTO"
    assert decide_detailed(_eligible(), agent_originated=True, **common).decision == "HUMAN"
    rejected = PolicyResult(decision="REJECTED", checks=[], action="REFUND")
    assert decide_detailed(rejected, agent_originated=True, **common).decision == "BLOCK"


def test_timeline_narrates_the_agent_and_says_it_cannot_approve():
    placed = narrate({"stage": "agent", "title": "Order placed by an AI agent for the buyer (Sandbox demo)",
                      "detail": {"agent": AGENT, "buyer": BUYER}})
    asked = narrate({"stage": "agent", "title": "Return requested by an AI agent for the buyer",
                     "detail": {"agent": AGENT, "on_behalf_of": BUYER, "message": "wrong colour"}})
    assert AGENT in placed and BUYER in placed
    assert AGENT in asked and "cannot approve" in asked and "wrong colour" in asked


# 8 --------------------------------------------------------------------------- the HTTP endpoint
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def rpc(method: str, params: dict | None = None, id_: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}


def call_rpc(name: str, arguments: dict, id_: int = 1) -> dict:
    return rpc("tools/call", {"name": name, "arguments": arguments}, id_)


@pytest.fixture
def http(tmp_path):
    """create_app() over the mock PayPal, served through TestClient with its lifespan running."""
    clients = []

    def build(host: str = "localhost:8000", **overrides):
        settings = Settings(db_path=str(Path(tempfile.mkdtemp(dir=tmp_path)) / "http.db"), paypal_client_id="",
                            paypal_client_secret="", **overrides)
        paypal = MagicMock(wraps=MockPayPalClient(), is_mock=True)
        app = create_app(settings, paypal=paypal, extractor=KeywordIntentExtractor())
        client = TestClient(app, base_url=f"http://{host}")
        client.__enter__()
        clients.append(client)
        return client, paypal
    yield build
    for client in clients:
        client.__exit__(None, None, None)


def test_http_end_to_end_request_waits_for_a_person(http):
    client, paypal = http()
    init = client.post("/mcp", headers=HEADERS, json=rpc("initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}))
    assert init.status_code == 200 and "cannot approve" in init.json()["result"]["instructions"]
    listed = client.post("/mcp", headers=HEADERS, json=rpc("tools/list", id_=2)).json()["result"]["tools"]
    assert {t["name"] for t in listed} == {"place_demo_order", "request_return", "get_case_status"}
    placed = client.post("/mcp", headers=HEADERS, json=call_rpc("place_demo_order",
                                                                {"buyer_name": BUYER, "agent_name": AGENT}, 3))
    order_id = placed.json()["result"]["structuredContent"]["order_id"]
    asked = client.post("/mcp", headers=HEADERS, json=call_rpc("request_return", {
        "order_id": order_id, "message": DEMO_MESSAGE, "agent_name": AGENT, "on_behalf_of": BUYER}, 4))
    view = asked.json()["result"]["structuredContent"]
    assert view["status"] == PENDING_APPROVAL and paypal.refund_capture.call_count == 0
    page = client.get(f"/?case={order_id}")
    assert page.status_code == 200 and "AI agent Claude (buyer" in page.text  # the merchant sees who asked


def test_token_is_required_when_configured(http):
    client, _ = http(mcp_token="s3cret-token")
    body = rpc("tools/list")
    assert client.post("/mcp", headers=HEADERS, json=body).status_code == 401
    assert client.post("/mcp", headers={**HEADERS, "Authorization": "Bearer wrong"}, json=body).status_code == 401
    assert client.get("/mcp").status_code == 401
    good = client.post("/mcp", headers={**HEADERS, "Authorization": "Bearer s3cret-token"}, json=body)
    assert good.status_code == 200 and good.json()["result"]["tools"]


def test_untrusted_host_is_refused_and_the_public_host_is_allowed(http):
    evil, _ = http(host="attacker.example")
    assert evil.post("/mcp", headers=HEADERS, json=rpc("tools/list")).status_code == 421
    public, _ = http(host="tradeos.example", public_base_url="https://tradeos.example")
    assert public.post("/mcp", headers=HEADERS, json=rpc("tools/list")).status_code == 200


def test_allowed_hosts_include_public_and_configured_extras():
    hosts = allowed_hosts(Settings(public_base_url="https://shop.example:8443", mcp_allowed_hosts=("10.0.0.5:9000",)))
    assert "shop.example:8443" in hosts and "10.0.0.5:9000" in hosts and "localhost:*" in hosts


def test_costly_tools_share_the_dashboard_rate_limit(http):
    client, paypal = http(rate_limit_per_minute=2)
    for i in range(2):
        r = client.post("/mcp", headers=HEADERS, json=call_rpc("place_demo_order",
                                                               {"buyer_name": BUYER, "agent_name": AGENT}, i))
        assert r.status_code == 200
    refused = client.post("/mcp", headers=HEADERS, json=call_rpc("place_demo_order",
                                                                 {"buyer_name": BUYER, "agent_name": AGENT}, 9))
    assert refused.status_code == 429 and refused.json()["error"]["message"].startswith("Rate limit")
    assert refused.json()["id"] == 9
    # reads are not throttled, and the refused call never reached PayPal
    assert client.post("/mcp", headers=HEADERS, json=rpc("tools/list")).status_code == 200
    assert paypal.create_order_with_card.call_count == 2


def test_rate_limit_applies_inside_a_json_rpc_batch():
    limiter = MagicMock()
    limiter.check.return_value = "Rate limit: nope"
    gate = McpGate(app=MagicMock(), settings=Settings(), limiter=limiter, client_key=lambda r: "1.2.3.4")
    batch = json.dumps([rpc("tools/list"), call_rpc("request_return", {}, 7)]).encode()
    refusal = gate._rate_refusal(batch, request=MagicMock())
    assert refusal["id"] == 7 and limiter.check.call_args.args == ("mcp:1.2.3.4",)
    assert gate._rate_refusal(b"not json", request=MagicMock()) is None
    assert gate._rate_refusal(json.dumps(call_rpc("get_case_status", {})).encode(), MagicMock()) is None
    assert COSTLY_TOOLS == {"place_demo_order", "request_return"}


def test_oversized_body_is_refused(http):
    client, _ = http()
    huge = json.dumps(call_rpc("request_return", {"message": "x" * (MAX_BODY + 1)}))
    assert client.post("/mcp", headers=HEADERS, content=huge).status_code == 413


def test_cross_site_browser_post_is_refused_by_the_app(http):
    client, _ = http()
    r = client.post("/mcp", headers={**HEADERS, "Origin": "https://attacker.example"}, json=rpc("tools/list"))
    assert r.status_code == 403


def test_gateway_can_be_switched_off(http):
    client, _ = http(mcp_enabled=False)
    assert client.post("/mcp", headers=HEADERS, json=rpc("tools/list")).status_code in (404, 405)


def test_settings_from_env_read_the_gateway_switches(monkeypatch):
    monkeypatch.setenv("TRADEOS_MCP", "0")
    monkeypatch.setenv("TRADEOS_MCP_TOKEN", "tok")
    monkeypatch.setenv("TRADEOS_MCP_ALLOWED_HOSTS", "a.example, b.example:8080 ,")
    monkeypatch.setenv("TRADEOS_AGENT_DEMO_ORDERS", "false")
    s = Settings.from_env()
    assert (s.mcp_enabled, s.mcp_token, s.mcp_allowed_hosts, s.agent_demo_orders) == (
        False, "tok", ("a.example", "b.example:8080"), False)
    assert replace(s, mcp_token="").mcp_token == ""


# edge paths ------------------------------------------------------------------------------------------------------
def test_a_request_already_in_flight_is_not_run_twice(make):
    wf, paypal, server = make()
    order_id = order(server)
    reads = paypal.get_capture.call_count
    wf._running.add(order_id)  # another request on this order is mid-flight
    try:
        view = ok(ask(server, order_id))
    finally:
        wf._running.discard(order_id)
    assert view["status"] == AGENT_ORDERED and "in progress" in view["note"]
    assert paypal.get_capture.call_count == reads


def test_a_case_finalized_underneath_the_request_is_recorded_not_raised(make, monkeypatch):
    from app.db import CaseFinalized
    wf, _, server = make()
    order_id = order(server)

    def finalized(case_id):
        raise CaseFinalized("status REJECTED is final")
    monkeypatch.setattr(wf, "_after_capture", finalized)
    view = ok(ask(server, order_id))
    assert "unchanged" in view["note"]
    assert any(e["title"] == "Agent request stopped — the case was already finalized" for e in wf.db.timeline(order_id))


def _gate_with(inner):
    return McpGate(app=inner, settings=Settings(), limiter=MagicMock(check=MagicMock(return_value=None)),
                   client_key=lambda r: "k")


def _scope():
    return {"type": "http", "method": "POST", "path": "/mcp", "headers": [], "query_string": b""}


def test_gate_stops_on_client_disconnect_mid_body():
    inner = MagicMock()
    messages = iter([{"type": "http.request", "body": b"{", "more_body": True}, {"type": "http.disconnect"}])

    async def receive():
        return next(messages)

    async def send(_message):
        raise AssertionError("nothing is sent to a client that left")
    anyio.run(_gate_with(inner), _scope(), receive, send)
    inner.assert_not_called()


def test_gate_replays_the_body_once_then_hands_over_the_stream():
    seen = []

    async def inner(scope, receive, send):
        seen.append(await receive())
        seen.append(await receive())

    messages = iter([{"type": "http.request", "body": json.dumps(rpc("tools/list")).encode(), "more_body": False},
                     {"type": "http.disconnect"}])

    async def receive():
        return next(messages)

    async def send(_message):
        pass
    anyio.run(_gate_with(inner), _scope(), receive, send)
    assert json.loads(seen[0]["body"])["method"] == "tools/list" and seen[1]["type"] == "http.disconnect"


def test_gate_passes_a_get_straight_through_when_no_token_is_set():
    calls = []

    async def inner(scope, receive, send):
        calls.append(scope["method"])

    async def receive():
        raise AssertionError("a GET body is never read by the gate")

    async def send(_message):
        pass
    anyio.run(_gate_with(inner), {**_scope(), "method": "GET"}, receive, send)
    assert calls == ["GET"]
