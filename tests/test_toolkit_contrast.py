"""The contrast with PayPal's official agent toolkits, measured from their published packages.

docs/eval/paypal-agent-toolkit.json is produced by scripts/paypal_toolkit_contrast.py from the PyPI wheel and the npm
package of version 1.11.0 (their tool tables; nothing called). These tests pin what it found and compare it with the
tools TradeOS's gateway offers an agent.
"""
from __future__ import annotations

import json
from pathlib import Path

import anyio
from mcp import Client

from app.agent_gateway import build_mcp_server
from tests.helpers import make_wf

MEASURED = json.loads(Path("docs/eval/paypal-agent-toolkit.json").read_text())


def tradeos_tools(settings) -> list:
    wf, _ = make_wf(settings)

    async def go():
        async with Client(build_mcp_server(wf, settings)) as client:
            return (await client.list_tools()).tools
    return anyio.run(go)


def test_paypals_toolkits_give_an_agent_money_moving_tools():
    ts, py = MEASURED["typescript"], MEASURED["python"]
    assert ts["money_moving"] == ["accept_dispute_claim", "create_refund", "pay_order"]
    assert py["money_moving"] == ["accept_dispute_claim", "pay_order"]
    # The agent chooses the refund amount, and leaving it out refunds the whole capture.
    assert "If not specified, the full captured amount is refunded." in ts["create_refund_amount_schema"]
    accept = next(t for t in py["tools"] if t["method"] == "accept_dispute_claim")
    assert accept["parameters"] == ["dispute_id", "note"] and "automatically refunds money" in accept["description"]
    assert all(len(side["sha256"]) == 64 for side in (ts, py))  # which exact artifacts were measured


def test_tradeos_gives_an_agent_none_of_them_and_no_amount_to_set(settings):
    tools = tradeos_tools(settings)
    names = {t.name for t in tools}
    assert names == {"place_demo_order", "request_return", "get_case_status"}
    every_money_tool = set(MEASURED["money_moving_rule"])
    assert not names & every_money_tool
    for tool in tools:  # nothing an agent sends can name an amount or a refund
        props = set((tool.input_schema or {}).get("properties", {}))
        assert not props & {"amount", "value", "currency_code", "refund_amount", "capture_id"}, (tool.name, props)
