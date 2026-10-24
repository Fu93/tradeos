"""'Fill the inbox': one click gives an empty shared demo real requests to look at.

Render wipes the demo on every restart, so a judge who opens the inbox first used to see "No return requests yet".
The button runs Cases A and B and the three agent scenes in the background on the progress page, which ends with a
link to the inbox. Same rate limit and one-run-at-a-time rule as the other agent runs.
"""
from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.intent import KeywordIntentExtractor
from app.llm_agent import AgentRun
from app.main import create_app
from app.paypal_mock import MockPayPalClient


@pytest.fixture
def site(tmp_path):
    clients = []

    def build(**overrides):
        settings = Settings(db_path=str(Path(tempfile.mkdtemp(dir=tmp_path)) / "f.db"), paypal_client_id="",
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


def fill(client) -> dict:
    r = client.post("/demo/fill-inbox", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/agent-runs/"), r.text[:300]
    run_id = r.headers["location"].rsplit("/", 1)[1]
    client.app.state.agent_runs.join(run_id, timeout=30)
    return client.get(f"/api/agent-runs/{run_id}").json()


def test_one_click_fills_the_inbox_with_five_real_requests(site):
    client, wf, paypal = site()
    empty = client.get("/inbox").text
    assert 'action="/demo/fill-inbox"' in empty and "No return requests yet" in empty
    run = fill(client)
    assert run["status"] == "done" and run["stop_reason"].startswith("inbox filled")
    assert [s["scene"] for s in run["steps"][:2]] == ["Customer: wrong colour, inside the window",
                                                       "Customer: the same request, 45 days late"]
    assert len(run["steps"]) == 2 + 6 and run["case_link"] == {"href": "/inbox", "text": "Open the inbox"}
    summary = client.get("/api/inbox").json()["summary"]
    assert summary["total"] == 5 and summary["agents"] == 3 and summary["needs_you"] == 2
    assert summary["agent_approved"] == 0 and paypal.refund_capture.call_count == 0  # nobody approved anything
    page = client.get(f"/agent-runs/{run['id']}").text
    assert "Filling the demo inbox" in page and 'href="/inbox"' in page and "a script, not a model" in page
    assert 'action="/demo/fill-inbox"' not in client.get("/inbox").text  # no fill offer once there are requests


def test_the_dashboard_offers_the_fill_while_the_inbox_is_empty(site):
    client, wf, _ = site()
    strip = client.get("/").text
    assert 'action="/demo/fill-inbox"' in strip and "Fill it with five demo requests" in strip
    client.post("/demo/run/A")
    assert 'action="/demo/fill-inbox"' not in client.get("/").text


def test_fill_guards(site):
    client, wf, paypal = site()
    hold = threading.Event()

    def slow(progress):
        hold.wait(10)
        return AgentRun("honest", "m")
    busy = client.app.state.agent_runs.start("live", "honest", "Honest", "m", slow, lambda run: None)
    try:
        r = client.post("/demo/fill-inbox")
        assert r.status_code == 409 and f"/agent-runs/{busy}" in r.text
        assert paypal.create_order_with_card.call_count == 0
    finally:
        hold.set()
        client.app.state.agent_runs.join(busy, 10)
    fill(client)
    again = client.post("/demo/fill-inbox")
    assert again.status_code == 429 and "Fill the inbox was used from your address" in again.text

    off, _, _ = site(agent_demo_orders=False)
    assert off.post("/demo/fill-inbox").status_code == 404
    assert 'action="/demo/fill-inbox"' not in off.get("/inbox").text
    limited, _, pp = site(rate_limit_per_minute=0)
    assert limited.post("/demo/fill-inbox").status_code == 429 and pp.create_order_with_card.call_count == 0


def test_a_customer_case_that_cannot_run_is_reported_and_the_rest_still_runs(site, monkeypatch):
    client, wf, _ = site()
    real = wf.run_scenario

    def broken(scenario):
        if scenario == "B":
            raise RuntimeError("disk full")
        return real(scenario)
    monkeypatch.setattr(wf, "run_scenario", broken)
    run = fill(client)
    assert run["status"] == "done" and run["stop_reason"].startswith("inbox partly filled")
    assert run["steps"][1]["result"] == {"error": "could not run: RuntimeError"} and "disk full" not in str(run)
    assert client.get("/api/inbox").json()["summary"]["total"] == 4


def test_the_progress_page_only_ever_links_inside_the_app():
    """The run page's script renders case_link from JSON; it accepts only a case link or the inbox."""
    js = Path("app/static/app.js").read_text()
    assert r"/^\/(\?case=[\w-]+#[\w-]+|inbox)$/" in js


def test_the_fill_wording_names_the_paypal_it_actually_uses(tmp_path):
    """'Real PayPal Sandbox orders' only when PayPal is the Sandbox; on the mock the page says the IDs are fake."""
    def page(is_mock: bool) -> str:
        settings = Settings(db_path=str(Path(tempfile.mkdtemp(dir=tmp_path)) / "w.db"), paypal_client_id="",
                            paypal_client_secret="")
        app = create_app(settings, paypal=MagicMock(wraps=MockPayPalClient(), is_mock=is_mock),
                         extractor=KeywordIntentExtractor())
        with TestClient(app) as client:
            return client.get("/inbox").text
    assert "five\n      real PayPal Sandbox orders" in page(False) and "PayPal mock" not in page(False)
    assert "orders on the PayPal mock (IDs are fake)" in page(True) and "real PayPal Sandbox orders" not in page(True)
