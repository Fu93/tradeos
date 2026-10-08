"""Keyword fallback + prompt injection → UNKNOWN, routed to a human (never an approvable exchange)."""

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.intent import INJECTION_GUARD_NOTE, KeywordIntentExtractor, LLMIntentExtractor, looks_like_injection
from app.main import create_app
from app.notes import TemplateNoteWriter
from app.paypal_mock import MockPayPalClient
from app.policy import SUPPORTED_INTENTS
from app.presets import BY_KEY, PRESETS

ROOT = Path(__file__).resolve().parents[1]
DATASET = {m["id"]: m for m in json.loads((ROOT / "docs/eval/dataset.json").read_text())["messages"]}
UNKNOWN = {"intent": "UNKNOWN", "reason": "UNKNOWN", "requested_action": "UNKNOWN"}
# m37: German "SYSTEM: … Gib requested_action=EXCHANGE zurück …"; m52: JSON break-out with "EXCHANGE".
ATTACKS = [DATASET["m37"]["message"], DATASET["m52"]["message"], BY_KEY["injection"]["message"]]


def failing_llm():
    """The production LLM extractor whose API is down (HTTP 503) → keyword fallback."""
    return LLMIntentExtractor("k", "https://llm.example/v1", "m",
                              transport=httpx.MockTransport(lambda r: httpx.Response(503)))


def test_unguarded_keyword_rules_would_have_produced_an_approvable_exchange():
    # Documents the bug being fixed: the raw keyword regexes see "EXCHANGE" in both attacks.
    kw = KeywordIntentExtractor()
    for msg in ATTACKS[:2]:
        assert kw._EXCHANGE.search(msg)


@pytest.mark.parametrize("message", ATTACKS)
def test_detector_catches_eval_attacks_and_preset(message):
    assert looks_like_injection(message)


@pytest.mark.parametrize("message", ATTACKS)
def test_llm_failure_plus_injection_forces_unknown(message):
    ex = failing_llm().extract(message)
    assert "LLM unavailable" in ex.extractor
    assert ex.result.model_dump() == UNKNOWN and ex.injection_guard
    assert INJECTION_GUARD_NOTE in ex.note and "LLM call failed" in ex.note
    key = (ex.result.intent, ex.result.requested_action)
    assert key not in SUPPORTED_INTENTS


def test_no_key_keyword_extractor_is_guarded_too():
    ex = KeywordIntentExtractor().extract(DATASET["m37"]["message"])
    assert ex.result.model_dump() == UNKNOWN and ex.injection_guard and ex.note == INJECTION_GUARD_NOTE


def test_every_injection_in_the_eval_set_is_detected_and_no_clean_message_is():
    for m in DATASET.values():
        assert looks_like_injection(m["message"]) is m["injection"], m["id"]
    for p in PRESETS:
        assert looks_like_injection(p["message"]) is (p["key"] == "injection"), p["key"]


def test_clean_messages_on_fallback_are_unchanged():
    ex = failing_llm().extract("The shoes are too small. Can I exchange size 42 for size 43?")
    assert ex.result.model_dump() == {"intent": "EXCHANGE_REQUEST", "reason": "SIZE_MISMATCH",
                                      "requested_action": "EXCHANGE"}
    assert not ex.injection_guard and INJECTION_GUARD_NOTE not in ex.note


def test_llm_path_is_not_affected_by_the_guard():
    content = json.dumps({"intent": "REFUND_REQUEST", "reason": "OTHER", "requested_action": "REFUND",
                          "language": "English", "language_code": "en", "current_size": None,
                          "requested_size": None, "merchant_summary_en": "Customer asks for a refund."})
    ex = LLMIntentExtractor("k", "https://llm.example/v1", "m", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"content": content}}]}))
    ).extract(BY_KEY["injection"]["message"])
    assert ex.result.intent == "REFUND_REQUEST" and not ex.injection_guard


@pytest.fixture
def client_wf(settings):
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    s = Settings(db_path=settings.db_path, rate_limit_per_minute=100, rate_limit_per_hour=100)
    app = create_app(settings=s, paypal=pp, extractor=failing_llm(), note_writer=TemplateNoteWriter())
    return TestClient(app), pp, app.state.workflow


@pytest.mark.parametrize("message", ATTACKS)
def test_end_to_end_guarded_case_goes_to_human_without_approve_button(client_wf, message):
    client, pp, wf = client_wf
    r = client.post("/cases/free", data={"message": message}, follow_redirects=False)
    case_id = re.search(r"case=([A-Z]-[0-9A-F]+)", r.headers["location"]).group(1)
    case = wf.db.get_case(case_id)
    assert case["intent"] == UNKNOWN and case["status"] == "REJECTED"
    assert "route to a human" in case["policy"]["reasons"][0]
    events = [e["title"] for e in wf.db.timeline(case_id)]
    assert "Keyword fallback + injection detected → intent UNKNOWN, sent to a human" in events
    html = client.get(f"/?case={case_id}").text
    assert f'action="/cases/{case_id}/approve"' not in html  # no Approve button for this case
    assert f'action="/cases/{case_id}/approve-twice"' not in html
    assert "intent was forced to <code>UNKNOWN</code>" in html
    assert "Keyword fallback + injection detected" in html
    assert client.post(f"/cases/{case_id}/approve", follow_redirects=False).status_code == 409
    pp.refund_capture.assert_not_called()


def test_control_clean_fallback_message_still_gets_an_approve_button(client_wf):
    client, pp, wf = client_wf
    r = client.post("/cases/free", data={"preset": "en"}, follow_redirects=False)
    case_id = re.search(r"case=([A-Z]-[0-9A-F]+)", r.headers["location"]).group(1)
    assert wf.db.get_case(case_id)["status"] == "PENDING_APPROVAL"
    assert f'action="/cases/{case_id}/approve"' in client.get(f"/?case={case_id}").text
