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
    assert "the financial side of an exchange is simplified to a refund" in html
    assert "$2.67" in html and "$0.39" in html and "$2.28" in html
    assert "Run Case A" in html and "Run Case B" in html
    assert "MOCK mode" in html  # mock PayPal is loudly labelled


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
    assert [c["operation"] for c in data["paypal_calls"]] == ["create_order_with_card", "get_capture", "refund_capture"]


def test_reset_and_health(ctx):
    client, _, wf = ctx
    run(client, "A")
    assert client.post("/demo/reset", follow_redirects=False).status_code == 303
    assert {c["status"] for c in wf.db.list_cases()} == {"NEW"}
    assert client.get("/healthz").json()["ok"] is True
