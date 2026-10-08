import json

import httpx
import pytest

from app.config import Settings
from app.intent import (KeywordIntentExtractor, LLMIntentExtractor, build_extractor, parse_llm_json)

DEMO = "The shoes are too small. Can I exchange size 42 for size 43?"


def test_keyword_extractor_demo_message():
    r = KeywordIntentExtractor().extract(DEMO).result
    assert r.model_dump() == {"intent": "EXCHANGE_REQUEST", "reason": "SIZE_MISMATCH", "requested_action": "EXCHANGE"}


@pytest.mark.parametrize("msg,intent", [
    ("I want my money back, the box arrived damaged", "REFUND_REQUEST"),
    ("Where is my parcel? tracking says nothing", "ORDER_STATUS"),
    ("Hello!", "UNKNOWN"),
    ("", "UNKNOWN"),
])
def test_keyword_extractor_other_messages(msg, intent):
    assert KeywordIntentExtractor().extract(msg).result.intent == intent


def llm_with(handler):
    return LLMIntentExtractor("test-key", "https://llm.example/v1", "some-model", transport=httpx.MockTransport(handler))


def chat(content):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_llm_extractor_valid_json_and_request_shape():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return chat('{"intent":"EXCHANGE_REQUEST","reason":"SIZE_MISMATCH","requested_action":"EXCHANGE"}')

    ex = llm_with(handler).extract(DEMO)
    assert ex.result.intent == "EXCHANGE_REQUEST"
    assert ex.extractor == "llm:some-model"
    assert seen["url"] == "https://llm.example/v1/chat/completions"
    assert seen["auth"] == "Bearer test-key"
    rf = seen["body"]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"]["properties"]["intent"]["enum"] == [
        "EXCHANGE_REQUEST", "REFUND_REQUEST", "ORDER_STATUS", "UNKNOWN"]
    assert seen["body"]["messages"][-1]["content"] == DEMO


@pytest.mark.parametrize("content", [
    '{"intent":"APPROVE_REFUND_NOW","reason":"SIZE_MISMATCH","requested_action":"EXCHANGE"}',  # off-enum
    '{"intent":"EXCHANGE_REQUEST","reason":"SIZE_MISMATCH","requested_action":"EXCHANGE","approved":true}',  # extra key
    '{"intent":"EXCHANGE_REQUEST"}',  # missing keys
    "Sure! The customer wants an exchange.",  # not JSON
    "[]",
])
def test_llm_off_schema_output_becomes_unknown(content):
    ex = llm_with(lambda r: chat(content)).extract(DEMO)
    assert ex.result.model_dump() == {"intent": "UNKNOWN", "reason": "UNKNOWN", "requested_action": "UNKNOWN"}


def test_llm_fenced_json_is_accepted():
    assert parse_llm_json('```json\n{"intent":"UNKNOWN","reason":"OTHER","requested_action":"INFO"}\n```').reason == "OTHER"


def test_llm_http_error_falls_back_to_keywords():
    ex = llm_with(lambda r: httpx.Response(500, json={"error": "boom"})).extract(DEMO)
    assert ex.result.intent == "EXCHANGE_REQUEST"
    assert "fallback" in ex.extractor and "LLM unavailable" in ex.extractor


def test_build_extractor_uses_keywords_without_key():
    assert isinstance(build_extractor(Settings()), KeywordIntentExtractor)
    assert isinstance(build_extractor(Settings(llm_api_key="k", llm_model="")), KeywordIntentExtractor)
    ex = build_extractor(Settings(llm_api_key="k"))
    assert isinstance(ex, LLMIntentExtractor)
    assert ex._base_url == "https://api.groq.com/openai/v1" and ex._model == "openai/gpt-oss-20b"


def test_llm_retries_in_json_mode_when_structured_output_unsupported():
    formats = []

    def handler(request):
        fmt = json.loads(request.content)["response_format"]["type"]
        formats.append(fmt)
        if fmt == "json_schema":
            return httpx.Response(400, json={"error": {"message": "json_schema not supported"}})
        return chat('{"intent":"EXCHANGE_REQUEST","reason":"SIZE_MISMATCH","requested_action":"EXCHANGE"}')

    ex = llm_with(handler).extract(DEMO)
    assert formats == ["json_schema", "json_object"]
    assert ex.result.intent == "EXCHANGE_REQUEST" and ex.extractor == "llm:some-model"


def test_llm_network_error_falls_back_to_keywords():
    def handler(request):
        raise httpx.ConnectError("down")

    ex = llm_with(handler).extract(DEMO)
    assert ex.result.intent == "EXCHANGE_REQUEST" and "LLM unavailable" in ex.extractor
