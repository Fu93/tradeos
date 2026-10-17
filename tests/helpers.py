"""Shared test helpers.

Moved out of the test files they grew in (test_upgrade, test_hardening) so a signature change here
stops breaking five other files through import chains. test_upgrade still owns the *other*
refund_event shape (the one with a capture up-link and a fixed event id) — its tests assert on it.
"""
import re
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.intent import AssistFields, Extraction, IntentResult, KeywordIntentExtractor
from app.main import create_app
from app.notes import TemplateNoteWriter
from app.paypal_mock import MockPayPalClient
from app.workflow import Workflow

CORE = {"intent": "REFUND_REQUEST", "reason": "NOT_AS_DESCRIBED", "requested_action": "REFUND"}  # return for a refund
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


def make_wf(settings, extractor=None, paypal=None, note_writer=None):
    db = Database(settings.db_path)
    db.init(reset=True)
    pp = paypal or MagicMock(wraps=MockPayPalClient(), is_mock=True)
    wf = Workflow(db, settings, extractor or KeywordIntentExtractor(), paypal=pp, note_writer=note_writer)
    wf.seed_demo()
    return wf, pp


def make_app(settings, mock=None, webhook_id="WH-TEST", extractor=None, note_writer=None, **kw):
    """The one HTTP app factory: real-ish PayPal semantics (MagicMock-wrapped) + FakeExtractor."""
    pp = MagicMock(wraps=mock or MockPayPalClient(), is_mock=True)
    s = Settings(db_path=settings.db_path, rate_limit_per_minute=100, rate_limit_per_hour=100,
                 paypal_webhook_id=webhook_id, **kw)
    app = create_app(settings=s, paypal=pp, extractor=extractor or FakeExtractor(),
                     note_writer=note_writer or TemplateNoteWriter())
    return TestClient(app), pp, app.state.workflow


@pytest.fixture
def app_ctx(settings):
    return make_app(settings)


def case_from(resp):
    assert resp.status_code == 303, resp.text[:300]
    return re.search(r"case=([A-Z]-[0-9A-F]+)", resp.headers["location"]).group(1)


def app_with(settings, mock=None, **kw):
    return make_app(settings, mock=mock, **kw)


def run_a(client):
    case_id = case_from(client.post("/demo/run/A", follow_redirects=False))
    client.post(f"/cases/{case_id}/approve", follow_redirects=False)
    return case_id


SIG = {"paypal-transmission-sig": "valid-mock-signature"}
SIG_OK = {**SIG, "Content-Type": "application/json"}
SIG_BAD = {"paypal-transmission-sig": "forged", "Content-Type": "application/json"}


def refund_event(rid, etype="PAYMENT.CAPTURE.REFUNDED", status="COMPLETED", eid="WH-1", details=None):
    res = {"id": rid, "status": status}
    if details:
        res["status_details"] = details
    return {"id": eid, "event_type": etype, "resource": res}


def pending_case(settings):
    """A case approved and refunded while PayPal reports it PENDING (e.g. eCheck)."""
    client, pp, wf = app_with(settings, mock=MockPayPalClient(refund_status="PENDING"))
    case_id = run_a(client)
    return client, pp, wf, case_id, wf.db.get_case(case_id)["refund_id"]
