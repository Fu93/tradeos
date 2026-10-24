"""The dashboard side of the agent gateway: what a judge clicks and what a merchant sees.

- "Run agent scenes" plays three scenes through the real MCP tools (not the workflow directly), in the background
  on the same progress page as a live model, and each tile turns green only when its scene shows what it promises.
- An agent case says who asked and for whom, and its footnote gives the real reason it needs a person.
- The button is rate-limited and has its own cooldown wording; it is absent when the gateway or demo orders are off.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.agent_scenes import SCENES, SCRIPTED_AGENT, agent_provenance
from app.config import Settings
from app.intent import KeywordIntentExtractor
from app.main import create_app
from app.paypal_mock import MockPayPalClient
from app.ratelimit import Cooldown


@pytest.fixture
def site(tmp_path):
    clients = []

    def build(**overrides):
        settings = Settings(db_path=str(Path(tempfile.mkdtemp(dir=tmp_path)) / "d.db"), paypal_client_id="",
                            paypal_client_secret="", **overrides)
        paypal = MagicMock(wraps=MockPayPalClient(), is_mock=True)
        app = create_app(settings, paypal=paypal, extractor=KeywordIntentExtractor())
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client, app.state.workflow, paypal
    yield build
    for client in clients:
        client.__exit__(None, None, None)


def play(client) -> dict:
    """Click the button, follow it to the progress page's run, wait for the background run, return its JSON."""
    r = client.post("/demo/agent-scenes", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/agent-runs/"), r.text[:300]
    run_id = r.headers["location"].rsplit("/", 1)[1]
    client.app.state.agent_runs.join(run_id, timeout=20)
    return client.get(f"/api/agent-runs/{run_id}").json()


def agents_section(html: str) -> str:
    start = html.index('id="agents"')
    return html[start:html.index("</section>", start)]


def test_one_click_plays_three_scenes_through_the_mcp_tools(site):
    client, wf, paypal = site()
    run = play(client)
    assert run["status"] == "done" and run["kind"] == "scripted" and run["stop_reason"] == "all 3 scenes played"
    assert [(s["scene"], s["tool"]) for s in run["steps"]] == [
        (scene.title, tool) for scene in SCENES for tool in ("place_demo_order", "request_return")]
    assert run["final_report"].count("as promised") == 3 and "NOT" not in run["final_report"]
    cases = {c["label"]: c for c in wf.db.list_cases() if c["scenario"] == "G"}
    assert set(cases) == {s.label for s in SCENES}
    assert {label: c["status"] for label, c in cases.items()} == {
        "Agent: honest return": "PENDING_APPROVAL", "Agent: prompt injection": "REJECTED",
        "Agent: late order (45 days)": "REJECTED"}
    assert paypal.refund_capture.call_count == 0
    for c in cases.values():  # the agent name only exists in the tool arguments: proof the MCP layer was used
        request = [e for e in wf.db.timeline(c["id"]) if e["title"].startswith("Return requested")]
        assert request and request[0]["detail"]["agent"] == SCRIPTED_AGENT
    honest = cases["Agent: honest return"]["id"]
    assert run["case_id"] == honest and run["case_link"]["href"] == f"/?case={honest}#agents"
    page = client.get(f"/agent-runs/{run['id']}").text
    assert "A script, not a model" in page and "chooses every tool call itself" not in page
    assert "Scripted MCP client" in page and "Prompt injection:" in page and f'href="/?case={honest}#agents"' in page
    section = agents_section(client.get(f"/?case={honest}").text)
    assert section.count('class="fm ok"') == 3 and "scripted MCP client" in section
    assert all(f"<code>{t}</code>" in section for t in ("place_demo_order", "request_return", "get_case_status"))


def test_honest_tile_stays_green_after_a_person_approves(site):
    client, wf, paypal = site()
    play(client)
    honest = wf.db.latest_case("G", "Agent: honest return")["id"]
    client.post(f"/cases/{honest}/approve")
    assert wf.db.get_case(honest)["status"] == "REFUND_COMPLETED" and paypal.refund_capture.call_count == 1
    section = agents_section(client.get("/").text)
    assert section.count('class="fm ok"') == 3 and "REFUND COMPLETED" in section


def test_agent_case_shows_who_asked_and_the_real_reason_it_needs_a_person(site):
    client, wf, _ = site(auto_enabled=True)
    play(client)
    honest = wf.db.latest_case("G", "Agent: honest return")["id"]
    page = client.get(f"/?case={honest}").text
    assert re.search(r'class="agent-card".*Requested by <strong>Scripted MCP client \(demo\)</strong> for Maria',
                     page, re.S)
    assert "Name self-declared, not verified" in page  # in-process scenes carry no credential
    assert "because an AI agent asked for it" in page and "either autonomy is off" not in page
    assert page.count('<span class="chip agent">AI agent</span>') >= 4  # three tabs + the card
    case_a = wf.db.latest_case("A")["id"]
    plain = client.get(f"/?case={case_a}").text
    assert 'class="agent-card"' not in plain


def test_card_for_an_order_with_no_request_yet(site):
    client, wf, _ = site()
    order_id = wf.agents.place_order("Tom", agent="Some agent")
    page = client.get(f"/?case={order_id}").text
    assert "Order placed by <strong>Some agent</strong> for Tom; no request on it yet." in page
    assert agent_provenance(wf, None) is None


def test_second_click_waits_with_its_own_wording(site):
    client, _, _ = site()
    play(client)
    again = client.post("/demo/agent-scenes")
    assert again.status_code == 429 and "Run agent scenes was used from your address" in again.text


def test_scenes_share_the_run_limit(site):
    client, _, paypal = site(rate_limit_per_minute=0)
    r = client.post("/demo/agent-scenes")
    assert r.status_code == 429 and "Rate limit" in r.text and paypal.create_order_with_card.call_count == 0


def test_a_failing_scene_is_reported_not_hidden(site):
    client, wf, _ = site()
    assert wf.begin_reset()
    try:
        run = play(client)  # waits for the background run while the reset is still in progress
    finally:
        wf.end_reset()
    assert run["status"] == "done" and run["stop_reason"] == "3 of 3 scenes did not show what they promise"
    assert run["final_report"].count("could not run") == 3 and "reset" in run["final_report"]
    assert run["case_id"] is None and run["case_link"] is None
    page = client.get(f"/agent-runs/{run['id']}").text
    assert "No scene placed an order. Nothing was refunded." in page and "could not run" in page


def test_a_click_while_any_agent_run_is_going_waits_and_costs_nothing(site):
    """One agent run at a time, of either kind. A click meanwhile links to the run in progress and neither places
    an order nor uses up the clicker's cooldown."""
    import threading
    from app.llm_agent import AgentRun
    client, wf, paypal = site()
    hold = threading.Event()

    def slow(progress):
        hold.wait(10)
        return AgentRun("honest", "m")
    busy = client.app.state.agent_runs.start("live", "honest", "Honest", "m", slow, lambda run: None)
    try:
        r = client.post("/demo/agent-scenes")
        assert r.status_code == 409 and f"/agent-runs/{busy}" in r.text and "already in progress" in r.text
        assert paypal.create_order_with_card.call_count == 0
        assert f'<a href="/agent-runs/{busy}">watch it</a>' in agents_section(client.get("/").text)
    finally:
        hold.set()
        client.app.state.agent_runs.join(busy, 10)
    assert play(client)["status"] == "done"  # the refused click did not start the cooldown


def test_button_and_section_follow_the_switches(site):
    off, _, _ = site(mcp_enabled=False)
    assert 'id="agents"' not in off.get("/").text and off.post("/demo/agent-scenes").status_code == 404
    no_orders, _, _ = site(agent_demo_orders=False)
    page = no_orders.get("/").text
    assert 'id="agents"' in page and "/demo/agent-scenes" not in page
    assert "<code>place_demo_order</code>" not in page
    assert no_orders.post("/demo/agent-scenes").status_code == 404


def test_cooldown_wording_defaults_to_reset():
    t = [0.0]
    reset = Cooldown(60, 15, clock=lambda: t[0])
    assert reset.check("a") is None and reset.check("a").startswith("Reset was used")
    assert reset.check("b").startswith("The demo was just reset by someone else")
    scenes = Cooldown(60, 20, clock=lambda: t[0], action="Run agent scenes", done_by_other="Someone else ran them")
    assert scenes.check("a") is None and scenes.check("b").startswith("Someone else ran them")


def test_honest_tile_counts_a_person_declining_as_the_promise_kept(site):
    client, wf, paypal = site()
    play(client)
    honest = wf.db.latest_case("G", "Agent: honest return")["id"]
    client.post(f"/cases/{honest}/decline")
    assert wf.db.get_case(honest)["status"] == "DECLINED_BY_HUMAN"
    assert agents_section(client.get("/").text).count('class="fm ok"') == 3 and paypal.refund_capture.call_count == 0


def test_create_app_works_inside_a_running_event_loop(tmp_path):
    """An ASGI server may import app.main inside its event loop. create_app() used to call anyio.run() at startup,
    which raises there ("Already running asyncio in this thread")."""
    import asyncio

    async def boot():
        app = create_app(Settings(db_path=str(tmp_path / "loop.db")), paypal=MockPayPalClient(),
                         extractor=KeywordIntentExtractor())
        return app.state.mcp_server is not None
    assert asyncio.run(boot())


def test_scripted_progress_wording_names_the_scene():
    from app.agent_runs import RunState
    state = RunState("r1", "scripted", "scenes", "Agent scenes", "Scripted MCP client (demo)", 0.0)
    assert state.snapshot()["status_text"] == "starting…"
    state.phase = "scene 2 of 3: Prompt injection"
    assert state.snapshot()["status_text"] == "playing scene 2 of 3: Prompt injection…"
    state.status, state.error = "failed", "RuntimeError"
    assert "Nothing was approved or refunded" in state.snapshot()["status_text"]


def test_json_on_the_page_reads_as_written_and_stays_escaped(site):
    """Step arguments and raw audit details used tojson, which is meant for <script> blocks: an apostrophe showed up
    as \\u0027 on the page. They are now plain text, escaped by autoescape, so markup in them is still inert."""
    client, wf, _ = site()
    run = play(client)
    page = client.get(f"/agent-runs/{run['id']}").text
    assert "\\u0027" not in page and "\\u003c" not in page
    order_id = wf.agents.place_order("Tom's <b>shop</b>", agent="it's <script>x</script>")
    case_page = client.get(f"/?case={order_id}").text
    assert "Tom&#39;s &lt;b&gt;shop&lt;/b&gt;" in case_page and "<script>x</script>" not in case_page
    assert "\\u0027" not in case_page
