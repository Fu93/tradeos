"""feat/paypal-hardening: self-verified webhook signatures, REFUND.PENDING/FAILED events,
capture warnings, and a PayPal check after a refund call with an unknown outcome."""
import base64
import json
import zlib
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

from app import webhook_verify as wv
from app.config import Settings
from app.main import create_app
from app.notes import TemplateNoteWriter
from app.paypal_client import PayPalClient, PayPalError
from app.paypal_mock import MockPayPalClient
from tests.test_upgrade import FakeExtractor, case_from, make_wf

CERT_URL = "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-test"
WEBHOOK_ID = "WH-TEST"


def _keypair(days_valid=30):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "messageverificationcerts.paypal.com")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=days_valid))
            .sign(key, hashes.SHA256()))
    return key, cert.public_bytes(serialization.Encoding.PEM)


KEY, PEM = _keypair()


def signed_headers(raw: bytes, webhook_id=WEBHOOK_ID, key=KEY, cert_url=CERT_URL, tid="tid-1", ttime="2026-10-10T15:00:00Z"):
    msg = f"{tid}|{ttime}|{webhook_id}|{zlib.crc32(raw)}".encode()
    sig = key.sign(msg, padding.PKCS1v15(), hashes.SHA256())
    return {"paypal-transmission-id": tid, "paypal-transmission-time": ttime, "paypal-cert-url": cert_url,
            "paypal-auth-algo": "SHA256withRSA", "paypal-transmission-sig": base64.b64encode(sig).decode()}


@pytest.fixture(autouse=True)
def _clean_cache():
    wv.clear_cache()
    yield
    wv.clear_cache()


def fetch_ok(url, timeout):
    fetch_ok.calls.append(url)
    return PEM


fetch_ok.calls = []


# ------------------------------------------------------------------ 1. self verification
def test_self_verify_success_uses_crc32_of_raw_body_and_caches_cert():
    fetch_ok.calls.clear()
    raw = b'{"id":"WH-1",  "event_type":"PAYMENT.CAPTURE.REFUNDED"}'
    h = signed_headers(raw)
    assert wv.self_verify(h, raw, WEBHOOK_ID, fetch=fetch_ok) == "SUCCESS"
    assert wv.self_verify(h, raw, WEBHOOK_ID, fetch=fetch_ok) == "SUCCESS"
    assert fetch_ok.calls == [CERT_URL]  # cached


def test_self_verify_rejects_tampered_body_wrong_webhook_id_and_wrong_key():
    raw = b'{"id":"WH-1"}'
    h = signed_headers(raw)
    assert wv.self_verify(h, raw + b" ", WEBHOOK_ID, fetch=fetch_ok) == "FAILURE"   # re-serialised body
    assert wv.self_verify(h, raw, "WH-OTHER", fetch=fetch_ok) == "FAILURE"
    other_key, _ = _keypair()
    assert wv.self_verify(signed_headers(raw, key=other_key), raw, WEBHOOK_ID, fetch=fetch_ok) == "FAILURE"


@pytest.mark.parametrize("url", ["http://api.sandbox.paypal.com/v1/notifications/certs/x",
                                 "https://evil.example.com/v1/notifications/certs/x",
                                 "https://paypal.com.evil.com/v1/notifications/certs/x",
                                 "https://api.paypal.com/other/path",
                                 "https://api.paypal.com:8443/v1/notifications/certs/x"])
def test_cert_only_from_paypal_and_never_fetched_otherwise(url):
    raw = b"{}"
    fetch = MagicMock(return_value=PEM)
    assert wv.self_verify(signed_headers(raw, cert_url=url), raw, WEBHOOK_ID, fetch=fetch) == "FAILURE"
    fetch.assert_not_called()


def test_expired_cert_fails():
    key, pem = _keypair(days_valid=-0)  # valid window ends now
    raw = b"{}"
    later = datetime.now(timezone.utc) + timedelta(days=2)
    assert wv.self_verify(signed_headers(raw, key=key), raw, WEBHOOK_ID, fetch=lambda u, t: pem, now=later) == "FAILURE"


def test_unavailable_when_headers_missing_or_cert_unreachable():
    with pytest.raises(wv.SelfVerifyUnavailable):
        wv.self_verify({"paypal-transmission-sig": "x"}, b"{}", WEBHOOK_ID)

    def down(url, timeout):
        raise httpx.ConnectError("down")
    with pytest.raises(wv.SelfVerifyUnavailable):
        wv.self_verify(signed_headers(b"{}"), b"{}", WEBHOOK_ID, fetch=down)


def test_simulator_style_id_only_matches_its_own_id():
    """Docs: for self-verification, mock (simulator) events are signed with webhook id 'WEBHOOK_ID'."""
    raw = b'{"id":"WH-SIM"}'
    h = signed_headers(raw, webhook_id="WEBHOOK_ID")
    assert wv.self_verify(h, raw, "WEBHOOK_ID", fetch=fetch_ok) == "SUCCESS"
    assert wv.self_verify(h, raw, WEBHOOK_ID, fetch=fetch_ok) == "FAILURE"  # not accepted for our real webhook


def app_with(settings, mock=None, **kw):
    pp = MagicMock(wraps=mock or MockPayPalClient(), is_mock=True)
    s = Settings(db_path=settings.db_path, rate_limit_per_minute=100, rate_limit_per_hour=100,
                 paypal_webhook_id=WEBHOOK_ID, **kw)
    app = create_app(settings=s, paypal=pp, extractor=FakeExtractor(), note_writer=TemplateNoteWriter())
    return TestClient(app), pp, app.state.workflow


def run_a(client):
    case_id = case_from(client.post("/demo/run/A", follow_redirects=False))
    client.post(f"/cases/{case_id}/approve", follow_redirects=False)
    return case_id


def refund_event(rid, etype="PAYMENT.CAPTURE.REFUNDED", status="COMPLETED", eid="WH-1", details=None):
    res = {"id": rid, "status": status}
    if details:
        res["status_details"] = details
    return {"id": eid, "event_type": etype, "resource": res}


def test_endpoint_self_verifies_and_records_method(settings, monkeypatch):
    monkeypatch.setattr(wv, "_http_fetch", lambda url, timeout: PEM)
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    raw = json.dumps(refund_event(wf.db.get_case(case_id)["refund_id"])).encode()
    r = client.post("/webhooks/paypal", content=raw, headers=signed_headers(raw))
    assert r.json()["verified"] is True and r.json()["method"] == "self"
    pp.verify_webhook_signature.assert_not_called()  # no PayPal API call needed
    assert wf.db.webhook_events(case_id)[0]["verify_method"] == "self"
    assert wf.db.get_case(case_id)["webhook"]["verify_method"] == "self"


def test_failed_self_check_is_rejected_without_postback(settings, monkeypatch):
    monkeypatch.setattr(wv, "_http_fetch", lambda url, timeout: PEM)
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    raw = json.dumps(refund_event(wf.db.get_case(case_id)["refund_id"])).encode()
    h = signed_headers(raw)
    h["paypal-transmission-sig"] = "valid-mock-signature"  # would pass the mock postback; must not be used
    r = client.post("/webhooks/paypal", content=raw, headers=h)
    assert r.json()["verified"] is False and r.json()["method"] == "self"
    pp.verify_webhook_signature.assert_not_called()
    assert wf.db.get_case(case_id)["webhook_status"] is None


def test_falls_back_to_postback_when_self_check_cannot_run(settings, monkeypatch):
    def down(url, timeout):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(wv, "_http_fetch", down)
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    raw = json.dumps(refund_event(wf.db.get_case(case_id)["refund_id"])).encode()
    pp.verify_webhook_signature.side_effect = lambda headers, body, wid: "SUCCESS"  # PayPal's API says OK
    r = client.post("/webhooks/paypal", content=raw, headers=signed_headers(raw))
    assert r.json()["method"] == "postback" and r.json()["verified"] is True
    pp.verify_webhook_signature.assert_called_once()


# ------------------------------------------------------------------ 2. refund events
SIG = {"paypal-transmission-sig": "valid-mock-signature"}


def pending_case(settings):
    client, pp, wf = app_with(settings, mock=MockPayPalClient(refund_status="PENDING"))
    case_id = run_a(client)
    return client, pp, wf, case_id, wf.db.get_case(case_id)["refund_id"]


def post(client, ev, headers=SIG):
    return client.post("/webhooks/paypal", content=json.dumps(ev), headers=headers).json()


def test_refund_pending_event_records_reason(settings):
    client, pp, wf, case_id, rid = pending_case(settings)
    post(client, refund_event(rid, "PAYMENT.REFUND.PENDING", "PENDING", details={"reason": "ECHECK"}))
    case = wf.db.get_case(case_id)
    assert case["status"] == "REFUND_PENDING" and case["refund"]["status_details"]["reason"] == "ECHECK"
    assert [e["outcome"] for e in wf.db.webhook_events(case_id)] == ["PENDING_CONFIRMED"]
    assert "ECHECK" in client.get(f"/?case={case_id}").text


def test_refund_failed_event_needs_human_and_never_refunds(settings):
    client, pp, wf, case_id, rid = pending_case(settings)
    post(client, refund_event(rid, "PAYMENT.REFUND.FAILED", "FAILED"))
    case = wf.db.get_case(case_id)
    assert case["status"] == "REFUND_FAILED" and case["refund_status"] == "FAILED"
    assert pp.refund_capture.call_count == 1
    assert "needs a human" in client.get(f"/?case={case_id}").text


def test_refund_failed_or_pending_never_downgrades_completed(settings):
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    rid = wf.db.get_case(case_id)["refund_id"]
    post(client, refund_event(rid, "PAYMENT.REFUND.FAILED", "FAILED", eid="E1"))
    post(client, refund_event(rid, "PAYMENT.REFUND.PENDING", "PENDING", eid="E2"))
    case = wf.db.get_case(case_id)
    assert case["status"] == "REFUND_COMPLETED" and case["refund_status"] == "COMPLETED"
    assert [e["outcome"] for e in wf.db.webhook_events(case_id)] == ["NO_CHANGE", "NO_CHANGE"]


def test_refund_events_dedupe_and_unverified_ignored(settings):
    client, pp, wf, case_id, rid = pending_case(settings)
    post(client, refund_event(rid, "PAYMENT.REFUND.FAILED", "FAILED", eid="E9"), {"paypal-transmission-sig": "x"})
    assert wf.db.get_case(case_id)["status"] == "REFUND_PENDING"
    post(client, refund_event(rid, "PAYMENT.REFUND.PENDING", "PENDING", eid="E1"))
    post(client, refund_event(rid, "PAYMENT.REFUND.PENDING", "PENDING", eid="E1"))
    outs = [e["outcome"] for e in wf.db.webhook_events(case_id)]
    assert outs == ["UNVERIFIED_IGNORED", "PENDING_CONFIRMED", "DUPLICATE_IGNORED"]


@pytest.mark.parametrize("etype", ["PAYMENT.CAPTURE.REVERSED", "PAYMENT.CAPTURE.DECLINED"])
def test_capture_warning_events_are_log_only(settings, etype):
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    case = wf.db.get_case(case_id)
    r = post(client, {"id": "E-CAP", "event_type": etype, "resource": {"id": case["capture_id"], "status": "REVERSED"}})
    assert r["case"] == case_id
    after = wf.db.get_case(case_id)
    assert after["status"] == case["status"] and after["refund_json"] == case["refund_json"]
    assert [e["outcome"] for e in wf.db.webhook_events(case_id)] == ["WARNING_NEEDS_HUMAN"]
    assert any("needs a human" in e["title"] for e in wf.db.timeline(case_id))
    assert pp.refund_capture.call_count == 1


def test_reversed_event_with_refund_shaped_resource_matches_by_up_link(settings):
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    case = wf.db.get_case(case_id)
    cap = case["capture_id"]
    ev = {"id": "E-REV", "event_type": "PAYMENT.CAPTURE.REVERSED",
          "resource": {"id": "REVERSAL-REFUND-1", "status": "COMPLETED", "note_to_payer": "Payment reversed",
                       "links": [{"rel": "up", "href": f"https://api.sandbox.paypal.com/v2/payments/captures/{cap}"}]}}
    assert post(client, ev)["case"] == case_id
    after = wf.db.get_case(case_id)
    assert after["refund_id"] == case["refund_id"] and after["status"] == case["status"]
    assert [e["outcome"] for e in wf.db.webhook_events(case_id)] == ["WARNING_NEEDS_HUMAN"]


# ------------------------------------------------------------------ 3. unknown refund outcome
def flaky_refund(pp, exc):
    real = pp._mock_wraps.refund_capture
    state = {"n": 0}

    def side(*a, **k):
        state["n"] += 1
        if state["n"] == 1:
            real(*a, **k)  # PayPal DID create the refund...
            raise exc       # ...but our call timed out / got a 5xx
        return real(*a, **k)
    pp.refund_capture.side_effect = side


@pytest.mark.parametrize("exc", [PayPalError("Could not reach PayPal: ReadTimeout"),
                                 PayPalError("INTERNAL_SERVER_ERROR", status_code=503, name="SERVICE_UNAVAILABLE")])
def test_timeout_or_5xx_triggers_paypal_check_then_retry_same_request_id(settings, exc):
    client, pp, wf = app_with(settings)
    flaky_refund(pp, exc)
    case_id = run_a(client)
    case = wf.db.get_case(case_id)
    assert case["status"] == "REFUND_ERROR"
    titles = [e["title"] for e in wf.db.timeline(case_id)]
    assert any(t.startswith("Checked with PayPal after the failed refund call: capture is REFUNDED") for t in titles)
    r = client.post(f"/cases/{case_id}/refund", follow_redirects=False)
    assert r.status_code == 303
    calls = wf.db.paypal_calls(case_id, "refund_capture")
    assert {c["request_id"] for c in calls} == {f"tradeos-refund-{case_id}"}  # same PayPal-Request-Id
    assert len(pp._mock_wraps.refunds_by_request) == 1                     # one refund at PayPal
    assert wf.db.get_case(case_id)["status"] == "REFUND_COMPLETED"


def test_retry_blocked_while_check_is_running(settings):
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    wf.db.update_case(case_id, status="REFUND_ERROR", refund_status=None, refund_id=None)
    wf._refund_checks[case_id] = "CHECKING"
    r = client.post(f"/cases/{case_id}/refund", follow_redirects=False)
    assert r.status_code == 409 and "Checking with PayPal" in r.text


def test_422_business_error_does_not_trigger_check(settings):
    client, pp, wf = app_with(settings)
    case_id = case_from(client.post("/demo/run/R", follow_redirects=False))
    client.post(f"/cases/{case_id}/approve", follow_redirects=False)
    assert not any("Checked with PayPal after" in e["title"] for e in wf.db.timeline(case_id))
    assert case_id not in wf._refund_checks


def test_check_runs_off_request_thread_when_backgrounded(settings):
    import threading
    import time
    client, pp, wf = app_with(settings, reconcile_in_background=True)
    flaky_refund(pp, PayPalError("Could not reach PayPal: ReadTimeout"))
    gate = threading.Event()
    real_get = pp._mock_wraps.get_capture
    case_id = case_from(client.post("/demo/run/A", follow_redirects=False))
    pp.get_capture.side_effect = lambda cid, timeout=None: (gate.wait(3), real_get(cid))[1]
    t0 = time.monotonic()
    client.post(f"/cases/{case_id}/approve", follow_redirects=False)
    assert time.monotonic() - t0 < 2  # approve did not wait for the GET
    assert wf.refund_check_pending(case_id)
    gate.set()
    for _ in range(50):
        if not wf.refund_check_pending(case_id):
            break
        time.sleep(0.05)
    assert not wf.refund_check_pending(case_id)


# ------------------------------------------------------------------ register script
def test_register_webhook_updates_in_place_and_is_idempotent():
    import importlib.util
    spec = importlib.util.spec_from_file_location("reg", "scripts/register_webhook.py")
    reg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reg)
    url = "https://tradeos.example/webhooks/paypal"
    state = {"events": ["PAYMENT.CAPTURE.REFUNDED"], "patched": 0, "created": 0}

    def handler(request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if request.method == "GET":
            return httpx.Response(200, json={"webhooks": [{"id": "WH-SAME", "url": url,
                                                          "event_types": [{"name": n} for n in state["events"]]}]})
        if request.method == "PATCH":
            body = json.loads(request.content)
            assert request.url.path == "/v1/notifications/webhooks/WH-SAME"
            assert body[0]["op"] == "replace" and body[0]["path"] == "/event_types"
            state["events"] = [e["name"] for e in body[0]["value"]]
            state["patched"] += 1
            return httpx.Response(200, json={"id": "WH-SAME", "event_types": body[0]["value"]})
        state["created"] += 1
        return httpx.Response(201, json={"id": "WH-NEW", "event_types": []})

    pp = PayPalClient("id", "s", "https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    assert reg.main(pp, url, apply=False)["action"] == "update" and state["patched"] == 0  # dry run
    assert reg.main(pp, url, apply=True) == {"action": "update", "id": "WH-SAME", "applied": True}
    assert sorted(state["events"]) == sorted(reg.EVENTS) and state["created"] == 0
    assert reg.main(pp, url, apply=True)["action"] == "none" and state["patched"] == 1
