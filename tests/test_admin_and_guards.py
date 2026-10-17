"""Sandbox-only PayPal client and the terminal-state guard in db.update_case.

Regression tests retained after removal of the optional TRADEOS_ADMIN_TOKEN gate
(the money-action endpoints are now open by design for the shared hackathon demo;
rate limits, policy hard guards, and the audit chain remain).
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
from app.workflow import NEW, PENDING_APPROVAL, REFUND_COMPLETED
from tests.helpers import FakeExtractor, case_from


def make(settings, **kw):
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    s = Settings(db_path=settings.db_path, rate_limit_per_minute=5, rate_limit_per_hour=30,
                 rate_limit_global_per_hour=200, **kw)
    app = create_app(settings=s, paypal=pp, extractor=FakeExtractor(), note_writer=TemplateNoteWriter())
    return TestClient(app), pp, app.state.workflow


# ---------------------------------------------------------------- sandbox-only client
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


# ---------------------------------------------------------------- terminal-state guard
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


def test_duplicate_process_run_skips_cleanly(settings):
    """The P1-3 race, closed at the front: the slower duplicate run loses the _running claim (or
    finds the case no longer NEW) and stops before paying for a second order."""
    client, pp, wf = make(settings)
    case = case_from(client.post("/demo/run/A", follow_redirects=False))
    client.post(f"/cases/{case}/approve", follow_redirects=False)
    before = wf.db.get_case(case)
    wf.process(case)  # a late duplicate of the Run
    after = wf.db.get_case(case)
    assert pp.create_order_with_card.call_count == 1  # no second order was created
    assert after["status"] == before["status"] == REFUND_COMPLETED
    assert after["capture_id"] == before["capture_id"]  # the evidence was NOT re-pointed
    assert after["refund_id"] == before["refund_id"]
    titles = [e["title"] for e in wf.db.timeline(case)]
    assert any("Run skipped" in t for t in titles)


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
