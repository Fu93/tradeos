"""Tests for the demo-polish round: multilingual free text, assist fields, grounded customer
notes, failure modes (late, injection, refund failure, double click), rate limiting, webhook."""

import json
import re
import threading
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.intent import (AssistFields, ChatJSONClient, Extraction, IntentResult, KeywordIntentExtractor,
                        LLMIntentExtractor, extraction_json_schema, looks_like_injection, parse_llm_output)
from app.main import create_app
from app.notes import (LLMNoteWriter, TemplateNoteWriter, english_note, numbers_preserved, reason_text)
from app.paypal_client import PayPalClient, PayPalError
from app.paypal_mock import MockPayPalClient
from app.presets import BY_KEY, PRESETS
from app.ratelimit import RateLimiter
from app.views import pipeline, result_card
from app.workflow import RefundNotAllowed, Workflow, clean_message

CORE = {"intent": "EXCHANGE_REQUEST", "reason": "SIZE_MISMATCH", "requested_action": "EXCHANGE"}
ASSIST = {"language": "Spanish", "language_code": "es", "current_size": "42", "requested_size": "43",
          "merchant_summary_en": "Customer wants to exchange size 42 for 43."}


class FakeExtractor:
    name = "fake-llm"

    def __init__(self, core=CORE, assist=ASSIST):
        self.core, self.assist = core, assist
        self.seen = []

    def extract(self, message):
        self.seen.append(message)
        return Extraction(result=IntentResult(**self.core), extractor=self.name, note="fake",
                          assist=AssistFields(**self.assist) if self.assist else None)


def chat(content):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def make_wf(settings, extractor=None, paypal=None, note_writer=None):
    db = Database(settings.db_path)
    db.init(reset=True)
    pp = paypal or MagicMock(wraps=MockPayPalClient(), is_mock=True)
    wf = Workflow(db, settings, extractor or KeywordIntentExtractor(), paypal=pp, note_writer=note_writer)
    wf.seed_demo()
    return wf, pp


@pytest.fixture
def app_ctx(settings):
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    s = Settings(db_path=settings.db_path, rate_limit_per_minute=100, rate_limit_per_hour=100,
                 paypal_webhook_id="WH-TEST")
    app = create_app(settings=s, paypal=pp, extractor=FakeExtractor(), note_writer=TemplateNoteWriter())
    return TestClient(app), pp, app.state.workflow


def case_from(resp):
    assert resp.status_code == 303, resp.text[:300]
    return re.search(r"case=([A-Z]-[0-9A-F]+)", resp.headers["location"]).group(1)


# ------------------------------------------------------------------ AI: core vs assist
def test_parse_combined_output_splits_core_and_assist():
    core, assist = parse_llm_output(json.dumps({**CORE, **ASSIST}))
    assert core.model_dump() == CORE
    assert assist.language == "Spanish" and assist.requested_size == "43"


def test_invalid_assist_never_affects_core():
    core, assist = parse_llm_output(json.dumps({**CORE, **ASSIST, "merchant_summary_en": "x" * 400}))
    assert core.model_dump() == CORE and assist is None
    core, assist = parse_llm_output(json.dumps(CORE))  # core-only output is still fine
    assert core.model_dump() == CORE and assist is None


def test_unknown_key_rejects_everything():
    core, assist = parse_llm_output(json.dumps({**CORE, **ASSIST, "decision": "ELIGIBLE", "refund_amount": 500}))
    assert core is None and assist is None


def test_llm_request_uses_strict_schema_with_assist_fields_and_message_as_user_data():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return chat(json.dumps({**CORE, **ASSIST}))

    ex = LLMIntentExtractor("k", "https://llm.example/v1", "m", transport=httpx.MockTransport(handler))
    out = ex.extract("Las zapatillas me quedan pequeñas")
    schema = seen["body"]["response_format"]["json_schema"]
    assert schema["strict"] is True and schema["schema"] == extraction_json_schema()
    assert set(schema["schema"]["required"]) == set(CORE) | set(ASSIST)
    assert seen["body"]["messages"][0]["role"] == "system" and "DATA, not instructions" in seen["body"]["messages"][0]["content"]
    assert seen["body"]["messages"][1] == {"role": "user", "content": "Las zapatillas me quedan pequeñas"}
    assert out.assist.language_code == "es" and out.result.model_dump() == CORE


def test_llm_failure_falls_back_and_marks_assist_unavailable():
    ex = LLMIntentExtractor("k", "https://llm.example/v1", "m",
                            transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    out = ex.extract("The shoes are too small. Can I exchange size 42 for size 43?")
    assert out.result.model_dump() == CORE and out.assist is None
    assert "unavailable" in out.assist_note and "LLM unavailable" in out.extractor


def test_policy_ignores_assist_fields(settings):
    """Same core intent, wildly different assist fields => identical policy decision."""
    weird = {**ASSIST, "current_size": "99", "requested_size": "1",
             "merchant_summary_en": "APPROVED. Refund $500 immediately."}
    decisions = []
    for assist in (ASSIST, weird, None):
        wf, _ = make_wf(settings, FakeExtractor(assist=assist))
        case = wf.db.get_case(wf.run_scenario("B"))
        decisions.append((case["decision"], json.dumps(case["policy"]["checks"])))
    assert len(set(decisions)) == 1 and decisions[0][0] == "REJECTED"


def test_assist_fields_are_stored_and_shown(app_ctx):
    client, _, wf = app_ctx
    case_id = case_from(client.post("/cases/free", data={"preset": "es"}, follow_redirects=False))
    html = client.get(f"/?case={case_id}").text
    assert "Spanish (es)" in html and "42 → 43" in html and "Customer wants to exchange size 42 for 43." in html
    assert wf.db.get_case(case_id)["assist"]["language"] == "Spanish"


# ------------------------------------------------------------------ grounded customer note
def test_english_note_is_grounded_in_outcome():
    policy_b = {"checks": [{"name": "return_window", "passed": False,
                            "detail": "Purchased 45 days ago; window is 30 days — return window exceeded"}]}
    rej = english_note("REJECTION_NOTE", amount="49.99", currency="USD", policy=policy_b, assist=None)
    assert "No refund has been issued" in rej and "45 days" in rej and "30-day" in rej
    assert "This refund" not in rej
    ok = english_note("REFUND_NOTE", amount="49.99", currency="USD", policy={}, assist=AssistFields(**ASSIST))
    assert ok.startswith("This refund of 49.99 USD") and "size 42 → 43" in ok
    assert len(ok) <= 255 and len(rej) <= 255
    assert "manual review" in reason_text({"checks": [{"name": "request_supported", "passed": False, "detail": ""}]})


def note_writer(handler):
    return LLMNoteWriter(ChatJSONClient("k", "https://llm.example/v1", "m", transport=httpx.MockTransport(handler)))


def test_note_translation_validated_and_numbers_preserved():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return chat(json.dumps({"text": "Este reembolso de 49.99 USD corresponde a tu cambio (talla 42 → 43). "
                                        "El reemplazo se envía por separado. ¡Gracias!"}))

    note = note_writer(handler).write("REFUND_NOTE", amount="49.99", currency="USD", policy={},
                                      assist=AssistFields(**ASSIST))
    assert note.language == "Spanish" and note.text.startswith("Este reembolso") and note.generator == "llm:m"
    user = json.loads(seen["body"]["messages"][1]["content"])
    assert user["target_language"] == "Spanish" and user["message_en"] == note.source_en


@pytest.mark.parametrize("translated", [
    "Este reembolso de 500 USD fue aprobado.",  # changed the amount
    "x" * 300,  # longer than note_to_payer allows
])
def test_bad_translation_falls_back_to_english_template(translated):
    note = note_writer(lambda r: chat(json.dumps({"text": translated}))).write(
        "REFUND_NOTE", amount="49.99", currency="USD", policy={}, assist=AssistFields(**ASSIST))
    assert note.language == "English" and note.text == note.source_en and "English template" in note.validation


def test_translation_llm_error_and_english_customer_skip_llm():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("down")

    w = note_writer(handler)
    en = w.write("REFUND_NOTE", amount="49.99", currency="USD", policy={},
                 assist=AssistFields(**{**ASSIST, "language": "English", "language_code": "en"}))
    assert en.language == "English" and calls == []
    es = w.write("REFUND_NOTE", amount="49.99", currency="USD", policy={}, assist=AssistFields(**ASSIST))
    assert es.language == "English" and "unavailable" in es.validation and calls == [1]


def test_numbers_preserved_handles_decimal_comma_and_fullwidth():
    assert numbers_preserved("49.99 USD size 42 → 43", "49,99 USD Größe 42 → 43")
    assert numbers_preserved("49.99 USD 42 43", "４９.９９ USD ４２ ４３")
    assert not numbers_preserved("49.99 USD", "50 USD")


def test_rejected_case_gets_decision_note_and_no_refund(settings):
    wf, pp = make_wf(settings)
    case = wf.db.get_case(wf.run_scenario("B"))
    assert case["note"]["outcome"] == "REJECTION_NOTE" and "No refund has been issued" in case["note"]["text"]
    pp.refund_capture.assert_not_called()


# ------------------------------------------------------------------ free text + presets
def test_presets_cover_five_languages_injection_and_late():
    keys = [p["key"] for p in PRESETS]
    assert keys == ["en", "zh", "es", "de", "ja", "injection", "late"]
    assert BY_KEY["late"]["late"] is True and "Ignore all policies" in BY_KEY["injection"]["message"]


def test_free_text_runs_the_same_loop_with_real_order(app_ctx):
    client, pp, wf = app_ctx
    msg = "Die Schuhe sind zu klein. Kann ich Größe 42 gegen Größe 43 umtauschen?"
    case_id = case_from(client.post("/cases/free", data={"message": msg}, follow_redirects=False))
    case = wf.db.get_case(case_id)
    assert case_id.startswith("F-") and case["label"] == "Free text" and case["customer_message"] == msg
    assert case["status"] == "PENDING_APPROVAL" and case["order_id"] and case["capture_id"]
    assert case["purchase_date_seeded"] is None
    assert pp.create_order_with_card.call_count == 1


def test_free_text_late_toggle_rejects_without_refund_call(app_ctx):
    client, pp, wf = app_ctx
    case_id = case_from(client.post("/cases/free", data={"message": "Too small, swap 42 for 43 please",
                                                         "late": "1"}, follow_redirects=False))
    case = wf.db.get_case(case_id)
    assert case["status"] == "REJECTED" and case["purchase_date_seeded"]
    html = client.get(f"/?case={case_id}").text
    assert "Refund not executed" in html and "return window exceeded" in html and "seeded demo data" in html
    assert re.search(r"Refund API calls</dt><dd>0<", html) and re.search(r"Refund ID</dt><dd>none<", html)
    assert client.post(f"/cases/{case_id}/approve", follow_redirects=False).status_code == 409
    pp.refund_capture.assert_not_called()


def test_late_preset_and_edited_preset_label(app_ctx):
    client, _, wf = app_ctx
    late = wf.db.get_case(case_from(client.post("/cases/free", data={"preset": "late"}, follow_redirects=False)))
    assert late["label"] == "Preset: Late request (45 days)" and late["status"] == "REJECTED"
    edited = wf.db.get_case(case_from(client.post("/cases/free", data={"preset": "es", "message": "Hola, otra cosa"},
                                                  follow_redirects=False)))
    assert edited["label"] == "Free text"


def test_free_text_validation_and_length_cap(app_ctx):
    client, pp, _ = app_ctx
    assert client.post("/cases/free", data={"message": "   "}).status_code == 422
    r = client.post("/cases/free", data={"message": "x" * 501})
    assert r.status_code == 422 and "too long" in r.text
    assert client.post("/cases/free", data={"preset": "nope"}).status_code == 404
    pp.create_order_with_card.assert_not_called()


def test_clean_message_strips_control_chars():
    assert clean_message("a\x00b\x1b[31m  c\n\n d", 100) == "a b [31m c\nd"
    assert clean_message("é" * 900, 500) == "é" * 500


def test_rate_limit_blocks_before_any_paypal_call(settings):
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    s = Settings(db_path=settings.db_path, rate_limit_per_minute=2, rate_limit_per_hour=10)
    client = TestClient(create_app(settings=s, paypal=pp, extractor=KeywordIntentExtractor()))
    assert client.post("/demo/run/A", follow_redirects=False).status_code == 303
    assert client.post("/cases/free", data={"preset": "en"}, follow_redirects=False).status_code == 303
    r = client.post("/cases/free", data={"preset": "de"}, follow_redirects=False)
    assert r.status_code == 429 and "Rate limit" in r.text
    assert client.post("/demo/run/B", follow_redirects=False).status_code == 429
    assert pp.create_order_with_card.call_count == 2
    # Different client address is not affected.
    assert client.post("/demo/run/B", headers={"X-Forwarded-For": "203.0.113.9"},
                       follow_redirects=False).status_code == 303


def test_rate_limiter_windows():
    now = [0.0]
    rl = RateLimiter(per_minute=2, per_hour=3, global_per_hour=100, clock=lambda: now[0])
    assert rl.check("a") is None and rl.check("a") is None
    assert "per minute" in rl.check("a")
    now[0] = 61
    assert rl.check("a") is None
    assert "per hour" in rl.check("a")
    now[0] = 3700
    assert rl.check("a") is None
    g = RateLimiter(per_minute=10, per_hour=10, global_per_hour=2, clock=lambda: 0)
    assert g.check("a") is None and g.check("b") is None and "busy" in g.check("c")


# ------------------------------------------------------------------ prompt injection
def test_injection_changes_nothing(app_ctx):
    client, pp, wf = app_ctx
    wf.extractor = FakeExtractor(core={"intent": "REFUND_REQUEST", "reason": "OTHER", "requested_action": "REFUND"},
                                 assist={**ASSIST, "language": "English", "language_code": "en",
                                         "current_size": None, "requested_size": None,
                                         "merchant_summary_en": "Customer requests a refund of $500."})
    case_id = case_from(client.post("/cases/free", data={"preset": "injection"}, follow_redirects=False))
    case = wf.db.get_case(case_id)
    assert case["status"] == "REJECTED" and case["amount"] == "49.99"
    assert "not supported" in case["policy"]["reasons"][0]
    html = client.get(f"/?case={case_id}").text
    assert "Instruction-like text detected" in html and "Controlled by the backend" in html
    pp.refund_capture.assert_not_called()


def test_injection_even_with_a_compromised_model_needs_human_and_uses_backend_amount(settings):
    """Worst case: the model is fooled into a valid exchange intent. Amount + approval still come from code."""
    wf, pp = make_wf(settings, FakeExtractor())
    case_id = wf.run_free_text(BY_KEY["injection"]["message"], label="Preset: Prompt injection")
    case = wf.db.get_case(case_id)
    assert case["status"] == "PENDING_APPROVAL"  # never auto-refunded
    pp.refund_capture.assert_not_called()
    with pytest.raises(RefundNotAllowed):
        wf.execute_refund(case_id)
    wf.approve(case_id)
    _, kwargs = pp.refund_capture.call_args
    assert "500" not in (kwargs.get("note_to_payer") or "")
    assert wf.db.get_case(case_id)["refund"]["amount"]["value"] == "49.99"


def test_looks_like_injection():
    assert looks_like_injection(BY_KEY["injection"]["message"])
    assert not looks_like_injection(BY_KEY["es"]["message"])


# ------------------------------------------------------------------ refund API failure
def test_refund_failure_is_shown_never_success_and_retry_recovers(app_ctx):
    client, pp, wf = app_ctx
    case_id = case_from(client.post("/demo/run/R", follow_redirects=False))
    assert case_id.startswith("R-")
    assert client.post(f"/cases/{case_id}/approve", follow_redirects=False).status_code == 303
    case = wf.db.get_case(case_id)
    assert case["status"] == "REFUND_ERROR" and case["refund_id"] is None
    assert "REFUND_FAILED_INSUFFICIENT_FUNDS" in case["error"]
    first = pp.refund_capture.call_args
    assert first.kwargs["mock_response"] == "REFUND_FAILED_INSUFFICIENT_FUNDS"
    html = client.get(f"/?case={case_id}").text
    assert "Refund FAILED at PayPal" in html and "Refund COMPLETED" not in html and "Retry refund" in html
    assert "the refund could not be completed yet" in html and "FINAL" not in html
    assert case["note"]["outcome"] == "FAILURE_NOTE" and "could not be completed yet" in case["note"]["text"]

    assert client.post(f"/cases/{case_id}/refund", follow_redirects=False).status_code == 303
    case = wf.db.get_case(case_id)
    retry = pp.refund_capture.call_args
    assert "mock_response" not in retry.kwargs and retry.args[1] == first.args[1]  # same PayPal-Request-Id
    assert case["status"] == "REFUND_COMPLETED" and case["refund_id"]
    assert case["note"]["outcome"] == "COMPLETED_NOTE"
    assert retry.kwargs["note_to_payer"] == first.kwargs["note_to_payer"]  # identical idempotent body
    calls = wf.db.paypal_calls(case_id, "refund_capture")
    assert [c["ok"] for c in calls] == [0, 1]


def test_paypal_client_refund_note_and_mock_header():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return httpx.Response(201, json={"id": "R1", "status": "COMPLETED"})

    pp = PayPalClient("id", "s", "https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    pp.refund_capture("C1", "rid", note_to_payer="Reembolso ñ 日本" + "x" * 300, mock_response="INTERNAL_SERVER_ERROR")
    req = seen[-1]
    body = json.loads(req.content)
    assert set(body) == {"note_to_payer"} and len(body["note_to_payer"]) == 255
    assert body["note_to_payer"].startswith("Reembolso ñ 日本")
    assert json.loads(req.headers["PayPal-Mock-Response"]) == {"mock_application_codes": "INTERNAL_SERVER_ERROR"}
    live = PayPalClient("id", "s", "https://api-m.paypal.com", transport=httpx.MockTransport(handler))
    with pytest.raises(PayPalError, match="only allowed in the sandbox"):
        live.refund_capture("C1", "rid", mock_response="INTERNAL_SERVER_ERROR")


# ------------------------------------------------------------------ duplicate / double click
def test_double_click_yields_one_refund(app_ctx):
    client, pp, wf = app_ctx
    case_id = case_from(client.post("/demo/run/D", follow_redirects=False))
    assert "Approve twice" in client.get(f"/?case={case_id}").text
    assert client.post(f"/cases/{case_id}/approve-twice", follow_redirects=False).status_code == 303
    case = wf.db.get_case(case_id)
    ev = case["duplicate"]
    assert ev["same_refund"] is True and ev["first_refund_id"] == ev["replayed_refund_id"] == case["refund_id"]
    assert ev["refund_api_calls"] == 2 and ev["total_refunded"] == "49.99 USD"
    request_ids = {c.args[1] for c in pp.refund_capture.call_args_list}
    assert request_ids == {f"tradeos-refund-{case_id}"}
    assert len(pp._mock_wraps.refunds_by_request) == 1  # PayPal side: exactly one refund
    assert client.post(f"/cases/{case_id}/approve", follow_redirects=False).status_code == 409
    html = client.get(f"/?case={case_id}").text
    assert "one refund" in html and "Refund COMPLETED" in html


def test_approve_twice_only_on_duplicate_test_case(app_ctx):
    client, _, _ = app_ctx
    case_id = case_from(client.post("/demo/run/A", follow_redirects=False))
    assert client.post(f"/cases/{case_id}/approve-twice", follow_redirects=False).status_code == 404


def test_concurrent_approvals_refund_once(settings):
    wf, pp = make_wf(settings)
    case_id = wf.run_scenario("A")
    barrier = threading.Barrier(4)
    outcomes = []

    def click():
        barrier.wait()
        try:
            wf.approve(case_id)
            outcomes.append("ok")
        except RefundNotAllowed:
            outcomes.append("refused")

    threads = [threading.Thread(target=click) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(outcomes) == ["ok", "refused", "refused", "refused"]
    assert pp.refund_capture.call_count == 1


def test_mock_paypal_rejects_second_distinct_refund():
    pp = MockPayPalClient()
    cap = pp.create_order_with_card("49.99", "USD", "r", "d", "x")["purchase_units"][0]["payments"]["captures"][0]
    first = pp.refund_capture(cap["id"], "rid-1")
    assert pp.refund_capture(cap["id"], "rid-1")["id"] == first["id"]
    with pytest.raises(PayPalError, match="already been fully refunded"):
        pp.refund_capture(cap["id"], "rid-2")


# ------------------------------------------------------------------ pipeline + result card
def test_pipeline_states(settings):
    wf, _ = make_wf(settings)
    a = wf.run_scenario("A")
    states = {s["key"]: s["state"] for s in pipeline(wf.db, wf.db.get_case(a))}
    assert states == {"request": "done", "intent": "done", "policy": "done", "supplier": "done",
                      "human": "waiting", "paypal": "todo"}
    wf.approve(a)
    assert pipeline(wf.db, wf.db.get_case(a))[-1]["state"] == "done"
    b = wf.run_scenario("B")
    states = {s["key"]: (s["state"], s["detail"]) for s in pipeline(wf.db, wf.db.get_case(b))}
    assert states["policy"][0] == "blocked" and states["supplier"][0] == "skipped"
    assert states["paypal"] == ("blocked", "Refund API NOT CALLED · 0 calls")
    card = result_card(wf.db, wf.db.get_case(b))
    assert card["title"] == "Refund not executed" and ("Refund ID", "none") in card["rows"]
    assert ("Refund API calls", "0") in card["rows"] and "return window exceeded" in card["reason"]


def test_success_card_has_all_ids(settings):
    wf, _ = make_wf(settings)
    a = wf.run_scenario("A")
    wf.approve(a)
    case = wf.db.get_case(a)
    rows = dict(result_card(wf.db, case)["rows"])
    assert rows["PayPal Order ID"] == case["order_id"] and rows["Capture ID"] == case["capture_id"]
    assert rows["Refund ID"] == case["refund_id"] and rows["Amount"] == "$49.99 USD"
    assert rows["PayPal timestamp"].endswith("UTC")


def test_dashboard_has_new_panels(app_ctx):
    client, _, _ = app_ctx
    html = client.get("/").text
    for text in ("Try it yourself", "中文（繁體）", "Español", "Deutsch", "日本語", "Prompt injection",
                 "Late request (45 days)", "Purchased 45 days ago", "Failure &amp; safety modes",
                 "Refund API failure", "Double-click approve", "MOCK supplier", "Customer request",
                 "AI intent", "Human approval", 'maxlength="500"'):
        assert text in html, text


# ------------------------------------------------------------------ webhook
def refund_event(refund_id, capture_id="C-unknown", event_type="PAYMENT.CAPTURE.REFUNDED"):
    return {"id": "WH-EVT-1", "event_type": event_type, "create_time": "2026-10-08T22:00:00Z",
            "resource": {"id": refund_id, "status": "COMPLETED",
                         "links": [{"rel": "up", "href": f"https://api.sandbox.paypal.com/v2/payments/captures/{capture_id}"}]}}


def test_webhook_verified_is_second_confirmation(app_ctx):
    client, pp, wf = app_ctx
    case_id = case_from(client.post("/demo/run/A", follow_redirects=False))
    client.post(f"/cases/{case_id}/approve", follow_redirects=False)
    refund_id = wf.db.get_case(case_id)["refund_id"]
    r = client.post("/webhooks/paypal", content=json.dumps(refund_event(refund_id)),
                    headers={"PAYPAL-TRANSMISSION-SIG": "valid-mock-signature", "Content-Type": "application/json"})
    assert r.json() == {"ok": True, "handled": True, "verified": True, "case": case_id, "method": "postback"}
    case = wf.db.get_case(case_id)
    assert case["webhook_status"] == "VERIFIED" and case["webhook"]["event_id"] == "WH-EVT-1"
    html = client.get(f"/?case={case_id}").text
    assert "Signed PayPal webhook: verified" in html and "signature verified (second confirmation)" in html


def test_webhook_bad_signature_is_not_trusted(app_ctx):
    client, _, wf = app_ctx
    case_id = case_from(client.post("/demo/run/A", follow_redirects=False))
    client.post(f"/cases/{case_id}/approve", follow_redirects=False)
    capture_id = wf.db.get_case(case_id)["capture_id"]
    r = client.post("/webhooks/paypal", content=json.dumps(refund_event("R-other", capture_id)),
                    headers={"PAYPAL-TRANSMISSION-SIG": "forged"})
    assert r.json()["verified"] is False and r.json()["case"] == case_id  # matched via capture link
    case = wf.db.get_case(case_id)
    # Changed in #10 review fix: unverified deliveries are log-only and never touch the displayed status.
    assert case["webhook_status"] is None and case["status"] == "REFUND_COMPLETED"


def test_webhook_ignores_other_events_and_bad_json(app_ctx):
    client, _, _ = app_ctx
    assert client.post("/webhooks/paypal", content="not json").status_code == 400
    r = client.post("/webhooks/paypal", content=json.dumps(refund_event("R1", event_type="PAYMENT.CAPTURE.COMPLETED")))
    assert r.json() == {"ok": True, "handled": False}
    r = client.post("/webhooks/paypal", content=json.dumps(refund_event("R-unknown")),
                    headers={"PAYPAL-TRANSMISSION-SIG": "valid-mock-signature"})
    assert r.json()["case"] is None


def test_webhook_without_webhook_id_is_unverified(settings):
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    client = TestClient(create_app(settings=settings, paypal=pp, extractor=KeywordIntentExtractor()))
    case_id = case_from(client.post("/demo/run/A", follow_redirects=False))
    client.post(f"/cases/{case_id}/approve", follow_redirects=False)
    refund_id = pp._mock_wraps.refunds_by_request[f"tradeos-refund-{case_id}"]["id"]
    r = client.post("/webhooks/paypal", content=json.dumps(refund_event(refund_id)),
                    headers={"PAYPAL-TRANSMISSION-SIG": "valid-mock-signature"})
    assert r.json()["verified"] is False
    pp.verify_webhook_signature.assert_not_called()
    # Changed in #10 review fix: an unverified delivery no longer changes what the case shows.
    assert "not configured (PAYPAL_WEBHOOK_ID)" in client.get(f"/?case={case_id}").text
    other = case_from(client.post("/demo/run/A", follow_redirects=False))
    client.post(f"/cases/{other}/approve", follow_redirects=False)
    assert "not configured (PAYPAL_WEBHOOK_ID)" in client.get(f"/?case={other}").text


def test_verify_webhook_signature_embeds_raw_body():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return httpx.Response(200, json={"verification_status": "SUCCESS"})

    pp = PayPalClient("id", "s", "https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    raw = b'{"id":"WH-1",  "event_type":"PAYMENT.CAPTURE.REFUNDED","resource":{"id":"R1"}}'
    headers = {"PAYPAL-AUTH-ALGO": "SHA256withRSA", "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/cert",
               "PAYPAL-TRANSMISSION-ID": "tid", "PAYPAL-TRANSMISSION-SIG": "sig", "PAYPAL-TRANSMISSION-TIME": "now"}
    assert pp.verify_webhook_signature(headers, raw, "WH-ID") == "SUCCESS"
    req = seen[-1]
    assert req.url.path == "/v1/notifications/verify-webhook-signature"
    assert raw.decode() in req.content.decode()  # byte-for-byte, not re-serialised
    body = json.loads(req.content)
    assert body["webhook_id"] == "WH-ID" and body["transmission_sig"] == "sig" and body["webhook_event"]["id"] == "WH-1"


def test_healthz_reports_modes_without_secrets(app_ctx):
    client, _, _ = app_ctx
    data = client.get("/healthz").json()
    assert data["ok"] is True and data["paypal_mode"] == "mock"
    assert data["webhook_configured"] is True and "WH-TEST" not in json.dumps(data)


def test_chinese_script_label_is_corrected_deterministically():
    from app.intent import chinese_script
    assert chinese_script(BY_KEY["zh"]["message"]) == "Hant"
    assert chinese_script("鞋子太小了，可以把42号换成43号吗？") == "Hans"
    assert chinese_script("Hello") is None
    wrong = {**CORE, **ASSIST, "language": "Chinese (Simplified)", "language_code": "zh-CN"}
    ex = LLMIntentExtractor("k", "https://llm.example/v1", "m",
                            transport=httpx.MockTransport(lambda r: chat(json.dumps(wrong))))
    out = ex.extract(BY_KEY["zh"]["message"])
    assert out.assist.language == "Chinese (Traditional)" and out.assist.language_code == "zh-Hant"
    assert out.result.model_dump() == CORE


def test_fmt_ts_converts_paypal_offsets_to_utc():
    from app.views import fmt_ts
    assert fmt_ts("2026-10-08T15:40:14-07:00") == "2026-10-08 22:40:14 UTC"
    assert fmt_ts("2026-10-08T22:40:14Z") == "2026-10-08 22:40:14 UTC"
    assert fmt_ts(None) == "—"


# ------------------------------------------------------------------ state-aware note wording
from app.notes import CLAIMS_ALLOWED, claims_consistent, makes_completion_claim  # noqa: E402

LANGS = {
    "en": AssistFields(**{**ASSIST, "language": "English", "language_code": "en"}),
    "zh": AssistFields(**{**ASSIST, "language": "Chinese (Traditional)", "language_code": "zh-Hant"}),
    "es": AssistFields(**ASSIST),
    "de": AssistFields(**{**ASSIST, "language": "German", "language_code": "de"}),
    "ja": AssistFields(**{**ASSIST, "language": "Japanese", "language_code": "ja"}),
}
GOOD_PENDING = {
    "zh": "您的換貨請求（尺寸 42 → 43）已審核，正在等待商家核准。目前尚未退款。",
    "es": "Su solicitud de cambio (talla 42 → 43) ha sido revisada y está pendiente de aprobación del comerciante. "
          "Aún no se ha emitido ningún reembolso.",
    "de": "Ihre Umtauschanfrage (Größe 42 → 43) wurde geprüft und wartet auf die Genehmigung des Händlers. "
          "Es wurde noch keine Rückerstattung ausgestellt.",
    "ja": "交換リクエスト（サイズ42→43）は確認済みで、販売者の承認待ちです。まだ返金は行われていません。",
}
BAD_PENDING = {
    "zh": "您的換貨請求（尺寸 42 → 43）已批准，退款 49.99 USD 已退款。",
    "es": "Su solicitud de cambio (talla 42 → 43) fue aprobada.",
    "de": "Ihre Umtauschanfrage (Größe 42 → 43) wurde genehmigt.",
    "ja": "交換リクエスト（サイズ42→43）は承認済みです。",
    "en": "Your exchange request (size 42 → 43) was approved.",
}


def test_english_templates_only_claim_after_completion():
    for outcome in ("PENDING_NOTE", "REFUND_NOTE", "COMPLETED_NOTE", "FAILURE_NOTE", "REJECTION_NOTE"):
        text = english_note(outcome, amount="49.99", currency="USD",
                            policy={"checks": [{"name": "return_window", "passed": False,
                                                "detail": "Purchased 45 days ago; window is 30 days"}]},
                            assist=LANGS["es"])
        assert makes_completion_claim(text) == (outcome in CLAIMS_ALLOWED), outcome
        assert len(text) <= 255
    pending = english_note("PENDING_NOTE", amount="49.99", currency="USD", policy={}, assist=None)
    assert "awaiting merchant approval" in pending and "No refund has been issued yet" in pending


@pytest.mark.parametrize("lang", ["zh", "es", "de", "ja"])
def test_pending_translation_without_claims_is_accepted(lang):
    note = note_writer(lambda r: chat(json.dumps({"text": GOOD_PENDING[lang]}))).write(
        "PENDING_NOTE", amount="49.99", currency="USD", policy={}, assist=LANGS[lang])
    assert note.text == GOOD_PENDING[lang] and note.language == LANGS[lang].language
    assert not makes_completion_claim(note.text)


@pytest.mark.parametrize("lang", ["zh", "es", "de", "ja", "en"])
@pytest.mark.parametrize("outcome", ["PENDING_NOTE", "FAILURE_NOTE", "REFUND_NOTE", "REJECTION_NOTE"])
def test_translation_claiming_approval_falls_back_to_english(lang, outcome):
    # "en" customers skip the LLM; emulate a model reply in English for a Spanish customer instead.
    assist = LANGS["es"] if lang == "en" else LANGS[lang]
    note = note_writer(lambda r: chat(json.dumps({"text": BAD_PENDING[lang]}))).write(
        outcome, amount="49.99", currency="USD", policy={}, assist=assist)
    assert note.language == "English" and note.text == note.source_en
    assert not makes_completion_claim(note.text)
    assert "approval/refund that has not happened" in note.validation or "number" in note.validation


def test_completed_translation_may_claim_approval():
    text = "您的換貨請求（尺寸 42 → 43）已批准，49.99 USD 的退款已由 PayPal 完成。替換品將另行寄出。謝謝！"
    note = note_writer(lambda r: chat(json.dumps({"text": text}))).write(
        "COMPLETED_NOTE", amount="49.99", currency="USD", policy={}, assist=LANGS["zh"])
    assert note.text == text and claims_consistent("COMPLETED_NOTE", text)


def bad_zh_writer():
    return note_writer(lambda r: chat(json.dumps({"text": BAD_PENDING["zh"]})))


def test_pending_case_note_never_claims_approval_even_with_bad_model(settings):
    wf, pp = make_wf(settings, FakeExtractor(assist={**ASSIST, "language": "Chinese (Traditional)",
                                                     "language_code": "zh-Hant"}), note_writer=bad_zh_writer())
    case_id = wf.run_free_text(BY_KEY["zh"]["message"])
    case = wf.db.get_case(case_id)
    assert case["status"] == "PENDING_APPROVAL" and case["note"]["outcome"] == "PENDING_NOTE"
    assert "已批准" not in case["note"]["text"] and not makes_completion_claim(case["note"]["text"])
    assert "awaiting merchant approval" in case["note"]["text"] and case["payer_note"] is None
    pp.refund_capture.assert_not_called()


def test_completed_note_only_after_paypal_completed(settings):
    paypal = MagicMock(wraps=MockPayPalClient(refund_status="PENDING"), is_mock=True)
    wf, _ = make_wf(settings, paypal=paypal)
    case_id = wf.run_scenario("A")
    wf.approve(case_id)
    case = wf.db.get_case(case_id)
    assert case["refund_status"] == "PENDING"
    assert case["note"]["outcome"] == "PENDING_NOTE" and not makes_completion_claim(case["note"]["text"])
    assert not makes_completion_claim(case["payer_note"]["text"])  # what was sent WITH the refund call
    paypal.complete_refund(case["refund_id"])  # PayPal settles the refund
    wf.refresh_refund(case_id)
    case = wf.db.get_case(case_id)
    assert case["refund_status"] == "COMPLETED" and case["note"]["outcome"] == "COMPLETED_NOTE"
    assert "was approved" in case["note"]["text"] and "has been completed" in case["note"]["text"]


def test_failure_note_wording(settings):
    paypal = MagicMock(wraps=MockPayPalClient(fail_refund=True), is_mock=True)
    wf, _ = make_wf(settings, paypal=paypal)
    case_id = wf.run_scenario("A")
    with pytest.raises(PayPalError):
        wf.approve(case_id)
    case = wf.db.get_case(case_id)
    assert case["note"]["outcome"] == "FAILURE_NOTE"
    assert "could not be completed yet" in case["note"]["text"] and not makes_completion_claim(case["note"]["text"])


def test_dashboard_labels_draft_vs_final(app_ctx):
    client, _, wf = app_ctx
    case_id = case_from(client.post("/demo/run/A", follow_redirects=False))
    html = client.get(f"/?case={case_id}").text
    assert "DRAFT — pending merchant approval. Not sent." in html and "DRAFT · not sent" in html
    assert ">FINAL<" not in html and "note_to_payer ·" not in html
    client.post(f"/cases/{case_id}/approve", follow_redirects=False)
    html = client.get(f"/?case={case_id}").text
    assert ">FINAL<" in html and "only after the merchant approved and PayPal returned COMPLETED" in html
    assert "PayPal note_to_payer" in html and "delivered with refund" in html


def test_rejected_note_keeps_no_refund_wording(settings):
    wf, _ = make_wf(settings)
    case = wf.db.get_case(wf.run_scenario("B"))
    assert case["note"]["outcome"] == "REJECTION_NOTE" and "No refund has been issued." in case["note"]["text"]
    assert not makes_completion_claim(case["note"]["text"])
