"""The returns inbox (/inbox): every request from customers and AI agents, and what each needs from the merchant.

- Only real requests are listed (a seeded case not run yet, or an agent order with no request, is not one).
- Each status maps to a bucket and a plain-words next step; a new status cannot ship without one.
- Agent rows say who asked, for whom, and whether the name was verified; "refunds an AI agent approved" is a live
  count, not a hard-coded 0.
- The page works without JavaScript (a server-rendered table), escapes what outsiders wrote, and keeps the CSP.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app import inbox, mixed, safety, workflow
from app.config import Settings
from app.db import TERMINAL_CASE_STATUSES
from app.intent import KeywordIntentExtractor
from app.main import create_app
from app.paypal_mock import MockPayPalClient
from app.security import CSP
from app.workflow import DEMO_MESSAGE

SAFETY_MESSAGE = "The sole melted in the heat and burned my foot."


@pytest.fixture
def site(tmp_path):
    clients = []

    def build(**overrides):
        settings = Settings(db_path=str(Path(tempfile.mkdtemp(dir=tmp_path)) / "i.db"), paypal_client_id="",
                            paypal_client_secret="", **overrides)
        paypal = MagicMock(wraps=MockPayPalClient(), is_mock=True)
        app = create_app(settings, paypal=paypal, extractor=KeywordIntentExtractor())
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client, app.state.workflow
    yield build
    for client in clients:
        client.__exit__(None, None, None)


def rows_by_id(client) -> dict[str, dict]:
    return {r["id"]: r for r in client.get("/api/inbox").json()["rows"]}


def test_an_untouched_demo_has_an_empty_inbox(site):
    client, wf = site()
    assert wf.db.list_cases()  # seeded Case A / B exist, but nobody asked for anything yet
    data = client.get("/api/inbox").json()
    assert data["rows"] == [] and data["summary"]["total"] == 0
    page = client.get("/inbox").text
    assert "No return requests yet" in page and 'id="inbox-grid"' not in page
    assert "no requests yet" in client.get("/").text  # the dashboard's strip says so too


def test_customer_requests_land_in_the_right_bucket_with_a_next_step(site):
    client, wf = site()
    a = client.post("/demo/run/A", follow_redirects=False).headers["location"].split("=")[1]
    b = client.post("/demo/run/B", follow_redirects=False).headers["location"].split("=")[1]
    rows = rows_by_id(client)
    assert rows[a]["bucket"] == "needs_you" and rows[a]["next_step"].startswith("Policy says eligible")
    assert rows[b]["bucket"] == "closed" and "never called" in rows[b]["next_step"]
    assert rows[b]["why"]  # the policy's first reason, so the merchant sees why without opening the case
    for r in (rows[a], rows[b]):
        assert r["from_agent"] is False and r["channel"] == "Customer message" and r["request"] == "Refund"
        assert r["refund_api_calls"] == 0 and r["chain_ok"] is True and r["amount"] == "49.99 USD"
    client.post(f"/cases/{a}/approve")
    done = rows_by_id(client)[a]
    assert done["bucket"] == "closed" and done["status"] == "REFUND_COMPLETED"
    assert done["refund_api_calls"] == 1 and done["approved_by"] == "human"


def test_rows_are_newest_first(site):
    client, wf = site()
    first = client.post("/demo/run/A", follow_redirects=False).headers["location"].split("=")[1]
    second = client.post("/demo/run/B", follow_redirects=False).headers["location"].split("=")[1]
    wf.db.update_case(first, created_at="2026-01-01T00:00:00+00:00")
    assert [r["id"] for r in client.get("/api/inbox").json()["rows"]] == [second, first]


def test_agent_requests_say_who_asked_for_whom_and_that_no_agent_approved(site):
    client, wf = site(auto_enabled=True)  # even with autonomy on, agent requests wait for a person
    order = wf.agents.place_order("Maria", agent="Shop assistant")
    unrequested = wf.agents.place_order("Tom", agent="Idle agent")
    wf.agents.submit_request(order, DEMO_MESSAGE, agent="Shop assistant", on_behalf_of="Maria")
    rows = rows_by_id(client)
    assert unrequested not in rows  # an order with no request is not a request
    row = rows[order]
    assert row["from_agent"] and row["channel"] == "AI agent (MCP)" and row["requested_by"] == "Shop assistant"
    assert row["buyer"] == "Maria" and row["verified"] is False and row["bucket"] == "needs_you"
    summary = client.get("/api/inbox").json()["summary"]
    assert summary["agents"] == 1 and summary["needs_you_agents"] == 1 and summary["agent_approved"] == 0
    strip = client.get("/").text
    assert "Returns inbox:" in strip and "refunds an AI agent approved: <strong>0</strong>" in strip


def test_the_agent_approved_count_is_computed_not_hard_coded():
    """If an agent request were ever approved by anything but a person, the page would show it."""
    def row(source: str, agent: bool = True) -> dict:
        return {"from_agent": agent, "bucket": "closed", "approved_by": source}
    rows = [row("human"), row(""), row("auto"), row("auto", agent=False)]
    assert inbox.inbox_summary(rows)["agent_approved"] == 1


def test_safety_and_mixed_requests_are_named_for_what_they_are(site):
    client, wf = site()
    s = client.post("/cases/free", data={"message": SAFETY_MESSAGE}, follow_redirects=False)
    safety_id = s.headers["location"].split("=")[1]
    m = client.post("/demo/run/M", follow_redirects=False).headers["location"].split("=")[1]
    rows = rows_by_id(client)
    assert rows[safety_id]["request"] == "Safety report" and rows[safety_id]["bucket"] == "needs_you"
    assert rows[m]["request"].startswith("Mixed") and rows[m]["status"] in inbox.NEXT_STEP


def case_statuses() -> set[str]:
    """Every case status the code defines: the "# Case statuses" block of app/workflow.py (read with ast, so a status
    added there is picked up), the mixed-order statuses, the terminal list and the Safety Gate's status."""
    import ast
    source = Path(workflow.__file__).read_text()
    start = source.index("# Case statuses")
    end = source.index("class SafetyNoteInvalid")
    found = set()
    for node in ast.parse(source).body:
        offset = sum(len(line) + 1 for line in source.splitlines()[:node.lineno - 1])
        if isinstance(node, ast.Assign) and start <= offset < end and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str) and node.value.value.isupper():
            found.add(node.value.value)
    return found | set(mixed.MIXED_STATUSES) | set(TERMINAL_CASE_STATUSES) | {safety.SAFETY_STATUS}


def test_every_status_the_system_can_set_has_a_next_step():
    """A status added later must get a bucket and plain words here, or the inbox would fall back to 'Open the
    case.' for it."""
    statuses = case_statuses()
    assert {"PENDING_APPROVAL", "REFUND_OUTCOME_UNKNOWN", "MIXED_DONE", "NEEDS_HUMAN_SAFETY_REVIEW"} <= statuses
    missing = {s for s in statuses if s not in inbox.NEXT_STEP and s not in inbox.NOT_A_REQUEST}
    assert not missing, missing


def test_the_page_escapes_what_outsiders_wrote_and_works_without_javascript(site):
    client, wf = site()
    order = wf.agents.place_order("<img src=x onerror=alert(1)>", agent="<script>alert(1)</script>")
    wf.agents.submit_request(order, DEMO_MESSAGE, agent="<script>alert(1)</script>",
                             on_behalf_of="<img src=x onerror=alert(1)>")
    page = client.get("/inbox").text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<img src=x" not in page
    table = page[page.index('id="inbox-table"'):]
    assert table.count("<tr class=\"bucket-") == 1 and "name self-declared" in table  # usable with JS off


def test_the_grid_is_vendored_and_the_csp_is_unchanged(site):
    client, _ = site()
    client.post("/demo/run/A")
    r = client.get("/inbox")
    assert r.headers["content-security-policy"] == CSP and "script-src 'self'" in CSP and "unsafe" not in CSP
    for path in ("/static/vendor/ag-grid/ag-grid-community.min.noStyle.js", "/static/vendor/ag-grid/ag-grid.min.css",
                 "/static/vendor/ag-grid/ag-theme-quartz-no-font.min.css", "/static/vendor/ag-grid/LICENSE.txt"):
        assert f'"{path}"' in r.text or path.endswith("LICENSE.txt")
        assert client.get(path).status_code == 200
    assert "MIT License" in client.get("/static/vendor/ag-grid/LICENSE.txt").text
    big = client.get("/static/vendor/ag-grid/ag-grid-community.min.noStyle.js", headers={"Accept-Encoding": "gzip"})
    assert big.headers.get("content-encoding") == "gzip"  # 1.4 MB on the wire would be a slow first load
    assert '<a href="/inbox">Inbox</a>' in client.get("/").text


def test_the_dashboard_strip_reads_only_the_cases_table(site, monkeypatch):
    """The strip renders on every dashboard view of a shared demo, so it must not read each agent case's timeline
    or recompute each chain; only the inbox page does that."""
    client, wf = site()
    order = wf.agents.place_order("Maria", agent="Shop assistant")
    wf.agents.submit_request(order, DEMO_MESSAGE, agent="Shop assistant", on_behalf_of="Maria")

    def expensive(*args, **kwargs):
        raise AssertionError("the strip read more than the cases table")
    monkeypatch.setattr(wf.agents, "provenance", expensive)
    monkeypatch.setattr(wf.db, "paypal_calls", expensive)
    rows = inbox.inbox_rows(wf, evidence=False)
    assert inbox.inbox_summary(rows)["needs_you_agents"] == 1
