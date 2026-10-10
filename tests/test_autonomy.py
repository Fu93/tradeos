"""Autonomy: the merchant's own policy may approve a refund — nothing else may.

Two things matter beyond the happy path, and both are asserted here:

* an auto approval is the SAME path as a human one — same per-case lock, same
  ``_guard_refund`` hard guard, same idempotent PayPal call;
* it is never *reported* as a human one. An audit trail that says "Human approved"
  for a decision no human made would be worse than no audit trail at all.
"""
from dataclasses import replace
from decimal import Decimal
import re
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.autonomy import decide, decide_detailed
from app.db import Database
from app.intent import KeywordIntentExtractor
from app.main import create_app
from app.paypal_mock import MockPayPalClient
from app.policy import PolicyResult
from app.views import narrate, pipeline, result_card, timeline_view
from app.workflow import RefundNotAllowed, Workflow

AUTO_TITLE = "Auto-approved by the merchant's policy — no human involved"
NEEDS_PERSON = "Autonomy: HUMAN — this case needs a person"


def mk(settings, **kw):
    db = Database(settings.db_path)
    db.init(reset=True)
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    wf = Workflow(db, replace(settings, **kw), KeywordIntentExtractor(), paypal=pp)
    wf.seed_demo()
    return wf, pp


def titles(wf, case_id):
    return [e["title"] for e in wf.db.timeline(case_id)]


# ---------------------------------------------------------------- defaults
def test_autonomy_is_off_by_default(settings):
    """A merchant has to opt in. Out of the box nothing is approved without a person."""
    assert settings.auto_enabled is False
    assert settings.auto_exchange_enabled is False
    wf, pp = mk(settings)
    cid = wf.run_scenario("A")
    case = wf.db.get_case(cid)
    assert case["status"] == "PENDING_APPROVAL"
    assert case["approval_source"] is None
    assert NEEDS_PERSON in titles(wf, cid)
    pp.refund_capture.assert_not_called()


def test_autonomy_off_by_env_default(monkeypatch):
    from app.config import Settings as S
    for name in ("AUTO_ENABLED", "AUTO_EXCHANGE_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    assert S.from_env().auto_enabled is False
    assert S.from_env().auto_exchange_enabled is False


# ---------------------------------------------------------------- the auto path
def test_auto_refunds_within_the_merchant_limit(settings):
    wf, pp = mk(settings, auto_enabled=True)
    cid = wf.run_scenario("A")
    case = wf.db.get_case(cid)

    assert case["status"] == "REFUND_COMPLETED" and case["refund_status"] == "COMPLETED"
    assert case["approval_source"] == "auto"
    # exactly what a human approval sends: same capture, same idempotency key, same payer note
    pp.refund_capture.assert_called_once_with(case["capture_id"], f"tradeos-refund-{cid}",
                                              note_to_payer=case["payer_note"]["text"])
    assert case["note"]["outcome"] == "COMPLETED_NOTE"


def test_auto_approval_is_on_the_hash_chain(settings):
    wf, _ = mk(settings, auto_enabled=True)
    cid = wf.run_scenario("A")
    assert wf.db.verify_chain(cid)["ok"] is True
    chained = wf.db.chained_case_state(cid)
    # the guard re-derives the approval from the chain, so it has to be there — with its origin
    assert chained["human_decision"] == "APPROVED"
    assert chained["approval_source"] == "auto"
    assert chained["decision"] == "ELIGIBLE"


def test_the_limit_is_inclusive(settings):
    wf, _ = mk(settings, auto_enabled=True, auto_refund_max_amount=Decimal("49.99"))
    assert wf.db.get_case(wf.run_scenario("A"))["status"] == "REFUND_COMPLETED"


def test_auto_approval_leaves_the_case_terminal_so_a_stray_click_cannot_refund_twice(settings):
    wf, pp = mk(settings, auto_enabled=True)
    cid = wf.run_scenario("A")
    with pytest.raises(RefundNotAllowed):
        wf.approve(cid)  # no longer awaiting approval
    assert pp.refund_capture.call_count == 1


# ---------------------------------------------------------------- escalation
def test_above_the_limit_goes_to_a_human(settings):
    wf, pp = mk(settings, auto_enabled=True, auto_refund_max_amount=Decimal("10.00"))
    cid = wf.run_scenario("A")
    case = wf.db.get_case(cid)
    assert case["status"] == "PENDING_APPROVAL"
    assert case["approval_source"] is None
    ts = titles(wf, cid)
    assert NEEDS_PERSON in ts and "Waiting for human approval of the refund" in ts
    assert "above the automatic refund limit" in str([e for e in wf.db.timeline(cid)
                                                      if e["title"] == NEEDS_PERSON][0]["detail"])
    pp.refund_capture.assert_not_called()


def test_autonomy_cannot_override_a_policy_rejection(settings):
    """Case B is outside the return window. Autonomy is not a second policy engine."""
    wf, pp = mk(settings, auto_enabled=True)
    cid = wf.run_scenario("B")
    case = wf.db.get_case(cid)
    assert case["status"] == "REJECTED" and case["decision"] == "REJECTED"
    assert case["approval_source"] is None
    pp.refund_capture.assert_not_called()
    assert wf.db.paypal_calls(cid, "refund_capture") == []


# ---------------------------------------------------------------- honesty
def test_auto_path_never_claims_a_human_approved(settings):
    wf, _ = mk(settings, auto_enabled=True)
    cid = wf.run_scenario("A")
    ts = titles(wf, cid)
    assert AUTO_TITLE in ts
    assert [t for t in ts if "Human approved" in t] == []
    assert [t for t in ts if t.startswith("Waiting for human")] == []


def test_a_real_approval_still_says_human(settings):
    """The other direction matters just as much: a person's approval is recorded as one."""
    wf, _ = mk(settings, auto_enabled=True, auto_refund_max_amount=Decimal("10.00"))
    cid = wf.run_scenario("A")
    wf.approve(cid)
    case = wf.db.get_case(cid)
    assert case["approval_source"] == "human"
    assert "Human approved the refund" in titles(wf, cid)
    assert AUTO_TITLE not in titles(wf, cid)


def test_decline_records_a_human_source(settings):
    wf, _ = mk(settings, auto_enabled=True, auto_refund_max_amount=Decimal("10.00"))
    cid = wf.run_scenario("A")  # above the limit, so it waits for a person
    assert wf.db.get_case(cid)["status"] == "PENDING_APPROVAL"
    wf.decline(cid)
    assert wf.db.get_case(cid)["approval_source"] == "human"


# ---------------------------------------------------------------- what the judge sees
def test_pipeline_and_result_card_name_the_approver(settings):
    wf, _ = mk(settings, auto_enabled=True)
    cid = wf.run_scenario("A")
    case = wf.db.get_case(cid)

    step = next(s for s in pipeline(wf.db, case) if s["key"] == "human")
    assert step["state"] == "done"
    assert step["detail"] == "auto-approved by the merchant's policy"

    card = result_card(wf.db, case)
    assert card["title"] == "Refund COMPLETED"
    assert "no human involved" in card["subtitle"]
    assert dict(card["rows"])["Approved by"] == "auto — merchant policy (no human)"


def test_result_card_says_human_when_a_human_approved(settings):
    wf, _ = mk(settings)
    cid = wf.run_scenario("A")
    wf.approve(cid)
    card = result_card(wf.db, wf.db.get_case(cid))
    assert "Approved by a human." in card["subtitle"]
    assert dict(card["rows"])["Approved by"] == "human (merchant)"


def test_timeline_narration_explains_an_auto_approval(settings):
    wf, _ = mk(settings, auto_enabled=True)
    cid = wf.run_scenario("A")
    lines = [e["text"] for e in timeline_view(wf.db.timeline(cid))]
    assert any("No human was involved" in line for line in lines)
    assert "The merchant approved the refund." not in lines


# ---------------------------------------------------------------- the module itself
ELIGIBLE = PolicyResult(decision="ELIGIBLE", action="REFUND")
REJECTED = PolicyResult(decision="REJECTED", action="REFUND")


def kw(**over):
    base = dict(amount=Decimal("49.99"), auto_enabled=True, auto_refund_max_amount=Decimal("50.00"),
                auto_exchange_enabled=False, injection_suspected=False, intent_is_unknown=False,
                action="REFUND")
    return {**base, **over}


def test_decide_never_automates_a_rejected_policy():
    result = decide_detailed(REJECTED, **kw())
    assert result.decision == "BLOCK"
    assert "never automated" in result.reason


def test_decide_escalates_an_instruction_like_or_unreadable_request():
    assert decide(ELIGIBLE, **kw(injection_suspected=True)) == "HUMAN"
    assert decide(ELIGIBLE, **kw(intent_is_unknown=True)) == "HUMAN"


def test_decide_needs_the_master_switch():
    assert decide(ELIGIBLE, **kw(auto_enabled=False)) == "HUMAN"


def test_decide_refund_threshold_boundary():
    assert decide(ELIGIBLE, **kw(amount=Decimal("50.00"))) == "AUTO"
    assert decide(ELIGIBLE, **kw(amount=Decimal("50.01"))) == "HUMAN"


def test_decide_exchange_needs_its_own_switch():
    assert decide(ELIGIBLE, **kw(action="EXCHANGE", auto_exchange_enabled=False)) == "HUMAN"
    assert decide(ELIGIBLE, **kw(action="EXCHANGE", auto_exchange_enabled=True)) == "AUTO"


def test_decide_never_automates_an_unsupported_action():
    assert decide(ELIGIBLE, **kw(action=None)) == "HUMAN"


def test_narrate_covers_the_new_timeline_titles(settings):
    wf, _ = mk(settings, auto_enabled=True)
    cid = wf.run_scenario("A")
    for event in wf.db.timeline(cid):
        assert narrate(event)  # every event has a plain-English line


# ---------------------------------------------------------------- through the app
def http_app(settings, **kw):
    pp = MagicMock(wraps=MockPayPalClient(), is_mock=True)
    s = replace(settings, rate_limit_per_minute=100, rate_limit_per_hour=100, **kw)
    app = create_app(settings=s, paypal=pp, extractor=KeywordIntentExtractor())
    return TestClient(app), pp


def run_case_a(client):
    resp = client.post("/demo/run/A", follow_redirects=False)
    assert resp.status_code == 303, resp.text[:300]
    return re.search(r"case=([A-Z]-[0-9A-F]+)", resp.headers["location"]).group(1)


def test_dashboard_completes_the_case_with_no_approve_button_when_autonomy_is_on(settings):
    """The judge-facing claim, asserted end to end: no Approve button, and the page says why."""
    client, pp = http_app(settings, auto_enabled=True)
    cid = run_case_a(client)
    html = client.get(f"/?case={cid}").text
    assert "Refund COMPLETED" in html
    assert "no human involved" in html
    assert "Autonomy <strong>ON</strong>" in html
    assert f"/cases/{cid}/approve" not in html  # nothing to approve: it is already done
    pp.refund_capture.assert_called_once()


def test_dashboard_still_waits_for_a_person_by_default(settings):
    client, pp = http_app(settings)  # AUTO_ENABLED unset
    cid = run_case_a(client)
    html = client.get(f"/?case={cid}").text
    assert "Awaiting human approval of the refund" in html
    assert f"/cases/{cid}/approve" in html
    assert "Autonomy <strong>OFF</strong>" in html
    pp.refund_capture.assert_not_called()
