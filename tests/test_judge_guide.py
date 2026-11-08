"""The first screen gives judges a reproducible path through the agent story."""
from __future__ import annotations

from starlette.requests import Request

from app.config import Settings
from app.intent import KeywordIntentExtractor
from app.main import create_app
from app.paypal_mock import MockPayPalClient


def dashboard(app, selected: str | None = None) -> str:
    """Render the synchronous GET route without TestClient's thread portal."""
    route = next(r for r in app.routes if getattr(r, "path", None) == "/"
                 and "GET" in getattr(r, "methods", set()))
    request = Request({"type": "http", "method": "GET", "path": "/", "root_path": "", "scheme": "http",
                       "server": ("test", 80), "client": ("testclient", 123), "headers": [],
                       "query_string": b"", "app": app})
    return route.endpoint(request, case=selected).body.decode()


def guide(html: str) -> str:
    start = html.index('id="demo-guide-title"')
    return html[start:html.index("</section>", start)]


def test_judge_path_shows_agent_and_blocked_case_links(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "guide.db")), paypal=MockPayPalClient(),
                     extractor=KeywordIntentExtractor())
    initial = guide(dashboard(app))
    assert 'action="/demo/agent-scenes"' in initial
    assert "The MCP scenes use a script, not a model" in initial
    assert "Open honest return" not in initial

    wf = app.state.workflow
    honest = wf.agents.place_order("Maria", agent="Scripted MCP client")
    wf.db.update_case(honest, label="Agent: honest return")
    blocked = wf.agents.place_order("Tom", agent="Scripted MCP client")
    wf.db.update_case(blocked, label="Agent: prompt injection")
    current = guide(dashboard(app))
    assert f'href="/?case={honest}#pending"' in current
    assert f'href="/?case={blocked}#pending"' in current


def test_judge_path_falls_back_without_agent_demo_orders(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "guide.db"), agent_demo_orders=False),
                     paypal=MockPayPalClient(), extractor=KeywordIntentExtractor())
    current = guide(dashboard(app))
    assert "Run Case A" in current
    assert 'action="/demo/agent-scenes"' not in current


def test_landing_page_prefers_the_story_over_a_newer_failure_case(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "guide.db")), paypal=MockPayPalClient(),
                     extractor=KeywordIntentExtractor())
    wf = app.state.workflow
    eligible = wf.run_scenario("A")
    rejected = wf.run_scenario("B")  # newer, but a poor first impression
    assert f'href="/?case={eligible}" class="tab active"' in dashboard(app)
    assert f'href="/?case={rejected}" class="tab active"' in dashboard(app, rejected)

    honest = wf.agents.place_order("Maria", agent="Scripted MCP client")
    wf.agents.submit_request(honest, "The shoes arrived in the wrong colour; I want a refund.",
                             agent="Scripted MCP client", on_behalf_of="Maria")
    wf.db.update_case(honest, label="Agent: honest return")
    assert wf.db.get_case(honest)["status"] == "PENDING_APPROVAL"
    for _ in range(16):
        wf.new_case("B")  # pushes the honest case past the first 14 tabs
    page = dashboard(app)
    assert f'href="/?case={honest}" class="tab active"' in page
    assert f'href="/?case={honest}#ai"' in guide(page)
