"""Admin token (TRADEOS_ADMIN_TOKEN), the sandbox-only PayPal client, and the terminal-state guard
in db.update_case — regression tests for the P1 findings of the 2026-10-11 audit:

- P1-1: the money-action endpoints (approve / decline / refund / capture / reset) are open by design
  in the old code; with a token configured they must refuse visitors and accept the token only.
- P1-2: a mistyped PAYPAL_BASE_URL used to point a card payload or refund at the live API.
- P1-3 (guard half): a slow duplicate run of the same case could flip a completed refund back to
  PENDING_APPROVAL and re-point its evidence at a fresh capture; db.update_case must refuse that.
"""
import threading

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from app.config import Settings
from app.db import CaseFinalized
from app.main import create_app
from app.notes import TemplateNoteWriter
from app.paypal_client import PayPalClient, PayPalError
from app.paypal_mock import MockPayPalClient
from app.workflow import AWAITING_BUYER, NEW, PENDING_APPROVAL, REFUND_COMPLETED
from tests.test_upgrade import FakeExtractor, case_from

TOKEN = "sekret-admin-token"


def make(settings, **kw):
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    s = Settings(db_path=settings.db_path, rate_limit_per_minute=5, rate_limit_per_hour=30,
                 rate_limit_global_per_hour=200, **kw)
    app = create_app(settings=s, paypal=pp, extractor=FakeExtractor(), note_writer=TemplateNoteWriter())
    return TestClient(app), pp, app.state.workflow


# ---------------------------------------------------------------- (1) admin token
def test_money_actions_need_the_token_when_configured(settings):
    client, pp, wf = make(settings, admin_token=TOKEN)
    case = case_from(client.post("/demo/run/A", follow_redirects=False))
    for path in (f"/cases/{case}/approve", f"/cases/{case}/decline", f"/cases/{case}/refund", "/demo/reset"):
        r = client.post(path, follow_redirects=False)
        assert r.status_code == 401, path
        assert "admin token" in r.text
    assert pp.refund_capture.call_count == 0
    ok = client.post(f"/cases/{case}/approve", data={"admin_token": TOKEN}, follow_redirects=False)
    assert ok.status_code == 303
    assert pp.refund_capture.call_count == 1


def test_admin_token_header_works_for_scripts(settings):
    client, pp, wf = make(settings, admin_token=TOKEN)
    case = case_from(client.post("/demo/run/A", follow_redirects=False))
    wrong = client.post(f"/cases/{case}/approve", headers={"x-admin-token": "nope"}, follow_redirects=False)
    assert wrong.status_code == 401
    ok = client.post(f"/cases/{case}/approve", headers={"x-admin-token": TOKEN}, follow_redirects=False)
    assert ok.status_code == 303 and pp.refund_capture.call_count == 1


def test_admin_login_logout_session(settings):
    client, pp, wf = make(settings, admin_token=TOKEN)
    assert client.post("/admin/login", data={"token": "wrong"}, follow_redirects=False).status_code == 401
    r = client.post("/admin/login", data={"token": TOKEN}, follow_redirects=False)
    assert r.status_code == 303 and "tradeos_admin" in r.headers["set-cookie"]
    case = case_from(client.post("/demo/run/A", follow_redirects=False))
    assert client.post(f"/cases/{case}/approve", follow_redirects=False).status_code == 303
    assert client.post("/admin/logout", follow_redirects=False).status_code == 303
    # the session was discarded server-side: the next money action needs the token again
    case2 = case_from(client.post("/demo/run/A", follow_redirects=False))
    assert client.post(f"/cases/{case2}/approve", follow_redirects=False).status_code == 401
    assert pp.refund_capture.call_count == 1


def test_unlock_form_follows_the_session(settings):
    client, pp, wf = make(settings, admin_token=TOKEN)
    assert "/admin/login" in client.get("/").text
    client.post("/admin/login", data={"token": TOKEN}, follow_redirects=False)
    assert "/admin/logout" in client.get("/").text


def test_no_token_configured_means_open(settings):
    client, pp, wf = make(settings)
    case = case_from(client.post("/demo/run/A", follow_redirects=False))
    assert client.post(f"/cases/{case}/approve", follow_redirects=False).status_code == 303
    assert client.post("/demo/reset", follow_redirects=False).status_code == 303
    assert client.post("/admin/login", data={"token": "x"}, follow_redirects=False).status_code == 400
    assert client.get("/healthz").json()["admin_required"] is False


def test_approve_twice_is_behind_the_token_too(settings):
    # approve-twice calls approve(): leaving it open would bypass the guard on /approve itself.
    client, pp, wf = make(settings, admin_token=TOKEN)
    case = case_from(client.post("/demo/run/D", follow_redirects=False))
    assert client.post(f"/cases/{case}/approve-twice", follow_redirects=False).status_code == 401
    assert pp.refund_capture.call_count == 0
    r = client.post(f"/cases/{case}/approve-twice", headers={"x-admin-token": TOKEN}, follow_redirects=False)
    assert r.status_code == 303
    assert pp.refund_capture.call_count == 2  # the approve + the replay with the SAME request id


def test_buyer_capture_is_behind_the_token(settings):
    client, pp, wf = make(settings, admin_token=TOKEN)
    pp.create_order_with_card.side_effect = PayPalError("card capture unavailable")
    case = case_from(client.post("/demo/run/A", follow_redirects=False))
    assert wf.db.get_case(case)["status"] == AWAITING_BUYER
    assert client.post(f"/cases/{case}/paypal-return", follow_redirects=False).status_code == 401
    r = client.post(f"/cases/{case}/paypal-return", headers={"x-admin-token": TOKEN}, follow_redirects=False)
    assert r.status_code == 303
    assert wf.db.get_case(case)["status"] == PENDING_APPROVAL


# ---------------------------------------------------------------- (2) sandbox-only client
def test_non_sandbox_base_url_refused_unless_allow_live():
    with pytest.raises(PayPalError, match="not the PayPal Sandbox"):
        PayPalClient("id", "s", "https://api-m.paypal.com")
    live = PayPalClient("id", "s", "https://api-m.paypal.com", allow_live=True)
    assert live.is_sandbox is False
    with pytest.raises(PayPalError, match="only allowed against the PayPal Sandbox"):
        live.create_order_with_card("49.99", "USD", "ref", "d", "rid-1")
    assert PayPalClient("id", "s", "https://api-m.sandbox.paypal.com").is_sandbox is True


def test_workflow_refuses_to_build_a_live_client(settings):
    s = Settings(db_path=settings.db_path, paypal_client_id="id", paypal_client_secret="s",
                 paypal_base_url="https://api-m.paypal.com")
    app = create_app(settings=s, extractor=FakeExtractor(), note_writer=TemplateNoteWriter())
    with pytest.raises(PayPalError, match="not the PayPal Sandbox"):
        app.state.workflow.paypal()


# ---------------------------------------------------------------- (3) terminal-state guard
def test_finalized_case_cannot_be_overwritten(settings):
    client, pp, wf = make(settings)
    case = case_from(client.post("/demo/run/A", follow_redirects=False))
    client.post(f"/cases/{case}/approve", follow_redirects=False)
    assert wf.db.get_case(case)["status"] == REFUND_COMPLETED
    db = wf.db
    with pytest.raises(CaseFinalized, match="final"):
        db.update_case(case, status=PENDING_APPROVAL)
    with pytest.raises(CaseFinalized, match="capture_id"):
        db.update_case(case, capture_id="CAP-OTHER")
    with pytest.raises(CaseFinalized, match="human_decision"):
        db.update_case(case, human_decision="DECLINED")
    assert db.get_case(case)["status"] == REFUND_COMPLETED
    assert pp.refund_capture.call_count == 1
    # same-status writes stay legal (webhook confirmations) and non-money writes are untouched
    db.update_case(case, status=REFUND_COMPLETED, webhook_status="VERIFIED")
    db.update_case(case, archived_at="2026-10-11T00:00:00Z")
    assert db.get_case(case)["webhook_status"] == "VERIFIED"


def test_duplicate_process_run_stops_cleanly(settings):
    """The P1-3 race: a second run of the same case arrives after the refund completed. The guard
    refuses the overwrite at the first frozen field and process() records why instead of 500ing."""
    client, pp, wf = make(settings)
    case = case_from(client.post("/demo/run/A", follow_redirects=False))
    client.post(f"/cases/{case}/approve", follow_redirects=False)
    before = wf.db.get_case(case)
    assert pp.create_order_with_card.call_count == 1
    wf.process(case)  # a late duplicate of the Run
    after = wf.db.get_case(case)
    assert pp.create_order_with_card.call_count == 2  # the duplicate really did run again
    assert after["status"] == REFUND_COMPLETED
    assert after["capture_id"] == before["capture_id"]  # the evidence was NOT re-pointed
    assert after["refund_id"] == before["refund_id"]
    titles = [e["title"] for e in wf.db.timeline(case)]
    assert any("already finalized" in t for t in titles)


def test_terminal_guard_is_atomic_under_concurrency(settings):
    client, pp, wf = make(settings)
    case = case_from(client.post("/demo/run/A", follow_redirects=False))
    client.post(f"/cases/{case}/approve", follow_redirects=False)
    barrier = threading.Barrier(4)
    results: list[str] = []

    def attempt():
        barrier.wait()
        try:
            wf.db.update_case(case, status=PENDING_APPROVAL)
            results.append("wrote")
        except CaseFinalized:
            results.append("refused")

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == ["refused"] * 4
    assert wf.db.get_case(case)["status"] == REFUND_COMPLETED


def test_non_terminal_transitions_still_allowed(settings):
    client, pp, wf = make(settings)
    case = case_from(client.post("/demo/run/A", follow_redirects=False))
    wf.db.update_case(case, status="ERROR")
    wf.db.update_case(case, status=NEW)  # ERROR is not terminal: the retry path must keep working
    assert wf.db.get_case(case)["status"] == NEW
