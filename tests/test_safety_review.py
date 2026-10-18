"""Safety review 'mark reviewed': human-gated, records a note + decision on the hash chain, NO money, NO refund flow."""
from __future__ import annotations

import pytest

from app.workflow import SAFETY_NOTE_MAX
from tests.helpers import FakeExtractor, case_from, make_app
from tests.test_safety_gate import ES_BURN, MISREAD

NOTE = "Read the message; phoned the customer; escalated to the product-safety lead."


def assert_no_money_no_supplier(wf, pp, cid):
    case = wf.db.get_case(cid)
    assert not wf.db.paypal_calls(cid, "refund_capture") and not pp.refund_capture.called
    assert not case.get("supplier_draft") and not case.get("supplier_reply") and not case.get("refund_id")
    assert case["decision"] != "ELIGIBLE" and case["human_decision"] in (None, "SAFETY_REVIEWED")


def safety_case(settings, **kw):
    client, pp, wf = make_app(settings, extractor=FakeExtractor(core=MISREAD), **kw)
    cid = case_from(client.post("/cases/free", data={"message": ES_BURN}, follow_redirects=False))
    assert wf.db.get_case(cid)["status"] == "NEEDS_HUMAN_SAFETY_REVIEW"
    return client, pp, wf, cid


def post(client, cid, note=NOTE):
    return client.post(f"/cases/{cid}/safety-reviewed", data={"note": note}, follow_redirects=False)


def test_mark_reviewed_records_note_decision_on_chain_without_money(settings):
    client, pp, wf, cid = safety_case(settings)
    assert "Mark reviewed" in client.get(f"/?case={cid}").text
    assert post(client, cid).status_code == 303
    case = wf.db.get_case(cid)
    assert case["status"] == "SAFETY_REVIEWED" and case["human_decision"] == "SAFETY_REVIEWED"
    assert case["decision"] == "NEEDS_HUMAN_SAFETY_REVIEW"
    ev = [e for e in wf.db.timeline(cid) if e["title"].startswith("Human marked the safety case reviewed")]
    assert len(ev) == 1 and ev[0]["detail"]["note"] == NOTE and ev[0]["detail"]["money_moved"] is False
    assert wf.db.verify_chain(cid)["ok"] is True
    state = wf.db.chained_case_state(cid)
    assert state["status"] == "SAFETY_REVIEWED" and state["human_decision"] == "SAFETY_REVIEWED"
    assert_no_money_no_supplier(wf, pp, cid)
    page = client.get(f"/?case={cid}").text
    assert "Safety case reviewed by a person" in page and NOTE in page
    assert "Approve &amp; refund" not in page and "/approve" not in page and "Mark reviewed" not in page


@pytest.mark.parametrize("path", ["approve", "refund", "decline", "approve-twice", "retry-policy"])
def test_reviewed_case_never_reenters_refund_flow(settings, path):
    client, pp, wf, cid = safety_case(settings)
    post(client, cid)
    r = client.post(f"/cases/{cid}/{path}", follow_redirects=False)
    assert r.status_code in (404, 409, 303, 422) and wf.db.get_case(cid)["status"] == "SAFETY_REVIEWED"
    assert_no_money_no_supplier(wf, pp, cid)


def test_double_submit_is_idempotent(settings):
    client, pp, wf, cid = safety_case(settings)
    assert post(client, cid).status_code == 303
    n = len(wf.db.timeline(cid))
    chain_n = len(wf.db.chain_entries(cid))
    assert post(client, cid, "A DIFFERENT NOTE").status_code == 303
    assert len(wf.db.timeline(cid)) == n and len(wf.db.chain_entries(cid)) == chain_n
    notes = [e["detail"]["note"] for e in wf.db.timeline(cid) if e["title"].startswith("Human marked")]
    assert notes == [NOTE]


@pytest.mark.parametrize("scenario", ["A", "B"])
def test_direct_post_on_non_safety_case_refused(settings, scenario):
    client, pp, wf = make_app(settings)
    cid = case_from(client.post(f"/demo/run/{scenario}", follow_redirects=False))
    before = wf.db.get_case(cid)["status"]
    r = post(client, cid)
    assert r.status_code == 409
    assert wf.db.get_case(cid)["status"] == before
    assert not [e for e in wf.db.timeline(cid) if e["title"].startswith("Human marked")]


def test_unknown_case_404(settings):
    client, *_ = make_app(settings)
    assert post(client, "A-DEADBEEF").status_code == 404


def test_note_is_html_escaped(settings):
    client, pp, wf, cid = safety_case(settings)
    evil = '<script>alert(1)</script><img src=x onerror=alert(2)>'
    post(client, cid, evil)
    page = client.get(f"/?case={cid}").text
    assert evil not in page and "&lt;script&gt;" in page


def test_note_required_and_length_limited(settings):
    client, pp, wf, cid = safety_case(settings)
    for bad in ("", "   \n ", "\x00\u200b"):
        assert post(client, cid, bad).status_code == 422
    assert post(client, cid, "x" * (SAFETY_NOTE_MAX + 1)).status_code == 422
    assert post(client, cid, "y" * 100_000).status_code == 422
    assert wf.db.get_case(cid)["status"] == "NEEDS_HUMAN_SAFETY_REVIEW"
    assert post(client, cid, "z" * SAFETY_NOTE_MAX).status_code == 303
    assert wf.db.get_case(cid)["status"] == "SAFETY_REVIEWED"


def test_csrf_cross_origin_refused(settings):
    client, pp, wf, cid = safety_case(settings)
    r = client.post(f"/cases/{cid}/safety-reviewed", data={"note": NOTE}, headers={"origin": "https://evil.example"},
                    follow_redirects=False)
    assert r.status_code == 403
    assert wf.db.get_case(cid)["status"] == "NEEDS_HUMAN_SAFETY_REVIEW"


def test_rate_limited_like_other_money_endpoints(settings):
    client, pp, wf, cid = safety_case(settings, money_rate_limit_per_minute=1)
    codes = [post(client, cid, "x" * 600).status_code for _ in range(3)]
    assert 429 in codes


def test_backstop_refuses_reviewed_status_even_if_decision_tampered(settings):
    client, pp, wf, cid = safety_case(settings)
    post(client, cid)
    from app.workflow import RefundNotAllowed
    case = dict(wf.db.get_case(cid), decision="ELIGIBLE")
    with pytest.raises(RefundNotAllowed):
        wf._refuse_if_safety(case)


def test_terminal_state_is_frozen(settings):
    client, pp, wf, cid = safety_case(settings)
    post(client, cid)
    from app.db import CaseFinalized
    with pytest.raises(CaseFinalized):
        wf.db.update_case(cid, status="PENDING_APPROVAL")


# ------------------------------------------------------------------ Case M2 (two-step, multi-batch) on the mock
def test_case_m2_two_batches_one_capture_then_overrefund_refused(settings):
    client, pp, wf = make_app(settings)
    cid = case_from(client.post("/demo/run/M2", follow_redirects=False))
    api = lambda: client.get(f"/api/cases/{cid}").json()  # noqa: E731
    d = api()
    b1 = d["mixed"]["batches"][0]
    assert sorted(i["resolution"] for i in d["mixed"]["items"]) == ["EXCHANGE", "NEEDS_HUMAN", "NEEDS_HUMAN", "REFUND"]
    val = lambda b: f"{b['amount_minor'] // 100}.{b['amount_minor'] % 100:02d}"  # noqa: E731
    assert client.post(f"/cases/{cid}/batches/{b1['id']}/approve",
                       data={"expected_total": val(b1), "expected_hash": b1["items_hash"]}).status_code in (200, 303)
    assert client.post(f"/cases/{cid}/lines/2/resolve", data={"action": "RETURN", "reason": "CHANGED_MIND"}).status_code in (200, 303)
    d = api()
    b2 = [b for b in d["mixed"]["batches"] if b["batch_no"] == 2][0]
    assert client.post(f"/cases/{cid}/batches/{b2['id']}/approve",
                       data={"expected_total": val(b2), "expected_hash": b2["items_hash"]}).status_code in (200, 303)
    d = api()
    calls = [x for x in d["paypal_calls"] if x["operation"] == "refund_capture"]
    assert len(calls) == 2 and calls[0]["request_id"] != calls[1]["request_id"]
    led = d["mixed"]["ledger"]
    assert led["committed_minor"] == b1["amount_minor"] + b2["amount_minor"] <= led["captured_minor"]
    # third attempts: re-approve either batch, re-resolve a refunded line, repropose with nothing open
    assert client.post(f"/cases/{cid}/batches/{b1['id']}/approve",
                       data={"expected_total": val(b1), "expected_hash": b1["items_hash"]}).status_code == 409
    assert client.post(f"/cases/{cid}/lines/1/resolve", data={"action": "RETURN", "reason": "DAMAGED"}).status_code == 409
    assert len([x for x in api()["paypal_calls"] if x["operation"] == "refund_capture"]) == 2
