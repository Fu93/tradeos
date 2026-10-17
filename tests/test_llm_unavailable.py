"""LLM down (quota/outage): visible notice, unreadable messages go to a human, refund safety unchanged."""

import re
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.intent import LLM_DOWN_NOTICE, LLMIntentExtractor
from app.main import create_app
from app.notes import TemplateNoteWriter
from app.paypal_mock import MockPayPalClient
from app.presets import BY_KEY


def llm(status):
    return LLMIntentExtractor("k", "https://llm.example/v1", "m",
                              transport=httpx.MockTransport(lambda r: httpx.Response(status)))


def make(settings, status):
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    s = Settings(db_path=settings.db_path, rate_limit_per_minute=100, rate_limit_per_hour=100)
    app = create_app(settings=s, paypal=pp, extractor=llm(status), note_writer=TemplateNoteWriter())
    return TestClient(app), pp, app.state.workflow


def run(client, **data):
    r = client.post("/cases/free", data=data, follow_redirects=False)
    return re.search(r"case=([A-Z]-[0-9A-F]+)", r.headers["location"]).group(1)


def test_quota_error_is_flagged_and_described_without_secrets():
    ex = llm(429).extract("hello")
    assert ex.llm_unavailable and "429" in ex.note and "quota" in ex.note


@pytest.mark.parametrize("status", [429, 503])
def test_unreadable_message_with_llm_down_goes_to_human_not_rejected(settings, status):
    client, pp, wf = make(settings, status)
    cid = run(client, preset="zh")
    case = wf.db.get_case(cid)
    assert case["status"] == "NEEDS_HUMAN" and case["decision"] == "NEEDS_HUMAN"
    html = client.get(f"/?case={cid}").text
    assert "AI model unavailable" in html and "needs a human" in html.lower()
    assert f'action="/cases/{cid}/approve"' not in html
    assert client.post(f"/cases/{cid}/approve", follow_redirects=False).status_code == 409
    assert client.post(f"/cases/{cid}/refund", follow_redirects=False).status_code in (404, 409, 422, 303)
    assert wf.db.get_case(cid)["refund_id"] is None
    pp.refund_capture.assert_not_called()


def test_english_message_with_llm_down_still_needs_human_approval_and_shows_notice(settings):
    client, pp, wf = make(settings, 503)
    cid = run(client, preset="en")
    assert wf.db.get_case(cid)["status"] == "PENDING_APPROVAL"
    assert "AI model unavailable: using basic English-only rules" in client.get(f"/?case={cid}").text
    pp.refund_capture.assert_not_called()


def test_injection_with_llm_down_stays_rejected_as_before(settings):
    client, pp, wf = make(settings, 503)
    cid = run(client, preset="injection")
    assert wf.db.get_case(cid)["status"] == "REJECTED"
    pp.refund_capture.assert_not_called()


def test_notice_text_names_the_limit():
    assert "English-only" in LLM_DOWN_NOTICE and "human" in LLM_DOWN_NOTICE and BY_KEY["zh"]
