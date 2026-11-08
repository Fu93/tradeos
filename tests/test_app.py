import re
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.intent import KeywordIntentExtractor
from app.main import create_app
from app.paypal_mock import MockPayPalClient


@pytest.fixture
def ctx(settings):
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    app = create_app(settings=settings, paypal=pp, extractor=KeywordIntentExtractor())
    return TestClient(app), pp, app.state.workflow


def run(client, scenario):
    r = client.post(f"/demo/run/{scenario}", follow_redirects=False)
    assert r.status_code == 303
    return re.search(r"case=([A-Z]-[0-9A-F]+)", r.headers["location"]).group(1)


def test_dashboard_has_three_blocks_and_required_copy(ctx):
    client, _, _ = ctx
    html = client.get("/").text
    for heading in ("Pending action", "Case timeline", "Case economics"):
        assert heading in html
    assert "Illustrative cost model — assumptions configurable." in html
    assert "Only a return leads to a refund" in html and "never calls the Refund API" in html
    assert "$2.67" in html and "$0.39" in html and "$2.28" in html
    assert "Run Case A" in html and "Run Case B" in html
    assert "MOCK mode" in html  # mock PayPal is loudly labelled


def test_dashboard_and_health_do_not_decode_the_full_case_table(ctx, monkeypatch):
    client, _, wf = ctx
    original = wf.db.list_cases
    calls = []

    def bounded(*args, **kwargs):
        calls.append(kwargs)
        assert kwargs.get("limit") is not None
        return original(*args, **kwargs)

    monkeypatch.setattr(wf.db, "list_cases", bounded)
    assert client.get("/").status_code == 200
    assert all(call["limit"] <= 51 for call in calls)
    calls.clear()
    assert client.get("/healthz").json()["cases"] == 2
    assert calls == []


def test_dashboard_finds_older_showcase_outside_recent_tabs(ctx):
    client, _, wf = ctx
    case_id = run(client, "A")
    for _ in range(20):
        wf.new_case("A")
    html = client.get("/").text
    assert f'href="/?case={case_id}"' in html
    assert "Approve &amp; refund" in html
    assert html.count('class="tab ') == 14


def test_dashboard_caps_attention_list_and_links_to_inbox(ctx):
    client, _, wf = ctx
    selected = wf.db.list_cases(limit=1)[0]["id"]
    for _ in range(55):
        wf.new_case("A", status="PENDING_APPROVAL")
    html = client.get(f"/?case={selected}").text
    attention = html.split('class="pending-list"', 1)[1].split("</ul>", 1)[0]
    assert attention.count("<li>") == 50
    assert "More cases need attention" in html and 'href="/inbox"' in html


def test_startup_refund_scan_uses_ids_and_includes_archived_cases(ctx, monkeypatch):
    _, _, wf = ctx
    case_id = wf.new_case("A", status="REFUND_OUTCOME_UNKNOWN")
    wf.db.archive_all()
    assert case_id in wf.db.unresolved_refund_case_ids(("REFUND_OUTCOME_UNKNOWN", "REFUND_AMOUNT_REVIEW"))

    def expensive(*args, **kwargs):
        raise AssertionError("startup decoded the entire cases table")

    monkeypatch.setattr(wf.db, "list_cases", expensive)
    wf.resume_unresolved_refunds()


def test_case_b_via_http_never_calls_refund(ctx):
    client, pp, _ = ctx
    case_id = run(client, "B")
    html = client.get(f"/?case={case_id}").text
    assert "NOT CALLED" in html and "seeded demo data" in html and "return window exceeded" in html
    assert client.post(f"/cases/{case_id}/refund", follow_redirects=False).status_code == 409
    assert client.post(f"/cases/{case_id}/approve", follow_redirects=False).status_code == 409
    pp.refund_capture.assert_not_called()


def test_case_a_via_http(ctx):
    client, pp, wf = ctx
    case_id = run(client, "A")
    html = client.get("/").text
    assert "Approve &amp; refund" in html
    pp.refund_capture.assert_not_called()
    r = client.post(f"/cases/{case_id}/approve", follow_redirects=False)
    assert r.status_code == 303
    case = wf.db.get_case(case_id)
    html = client.get("/").text
    assert case["refund_id"] in html and "Refund COMPLETED" in html and "Confirmed by PayPal" in html
    data = client.get(f"/api/cases/{case_id}").json()
    assert data["case"]["refund_status"] == "COMPLETED"
    assert [c["operation"] for c in data["paypal_calls"]] == [
        "create_order_with_card", "get_capture", "get_capture", "refund_capture"]


def test_wrong_refund_amount_is_visible_and_cannot_be_retried(ctx):
    client, pp, wf = ctx
    case_id = run(client, "A")
    original = pp._mock_wraps.refund_capture

    def wrong_amount(*args, **kwargs):
        refund = original(*args, **kwargs)
        refund["amount"] = {"value": "5.00", "currency_code": "USD"}
        return refund

    pp.refund_capture.side_effect = wrong_amount
    assert client.post(f"/cases/{case_id}/approve", follow_redirects=False).status_code == 303
    assert wf.db.get_case(case_id)["status"] == "REFUND_AMOUNT_REVIEW"
    html = client.get(f"/?case={case_id}").text
    assert "Refund amount needs verification" in html
    assert "Check with PayPal" in html
    assert "PayPal reported amount" in html
    # Loading the page may also trigger a valid PayPal GET and resolve the review.
    assert wf.db.get_case(case_id)["status"] in ("REFUND_AMOUNT_REVIEW", "REFUND_COMPLETED")
    assert client.post(f"/cases/{case_id}/refund", follow_redirects=False).status_code == 409
    assert pp.refund_capture.call_count == 1


def test_reset_and_health(ctx):
    client, _, wf = ctx
    run(client, "A")
    assert client.post("/demo/reset", follow_redirects=False).status_code == 303
    assert {c["status"] for c in wf.db.list_cases()} == {"NEW"}
    assert client.get("/healthz").json()["ok"] is True


def test_home_after_demo_reset_shows_only_the_two_starter_cases(ctx):
    """Cases run before a reset (incl. a double-approved one) are archived and gone from the home page."""
    client, pp, wf = ctx
    case_id = run(client, "A")
    client.post(f"/cases/{case_id}/approve-twice", follow_redirects=False)
    client.post("/cases/free", data={"preset": "en"}, follow_redirects=False)
    assert client.post("/demo/reset", follow_redirects=False).status_code == 303
    cases = wf.db.list_cases()
    assert sorted(c["scenario"] for c in cases) == ["A", "B"] and all(c["status"] == "NEW" for c in cases)
    html = client.get("/").text
    assert case_id not in html and html.count('class="tab ') == 2
