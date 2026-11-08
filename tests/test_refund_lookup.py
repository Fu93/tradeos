"""Read-only recovery of real-Sandbox-like refunds whose POST response was lost."""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app import lineitems as li
from app.main import create_app
from app.paypal_client import PayPalClient, PayPalError
from app.paypal_mock import MockPayPalClient
from app.workflow import RefundNotAllowed
from tests.helpers import FakeExtractor, make_wf


def lost_reply_case(settings, mixed=False):
    mock = MockPayPalClient()
    pp = MagicMock(wraps=mock, is_mock=False)
    wf, _ = make_wf(settings, paypal=pp)
    cid = wf.run_scenario("M" if mixed else "A")
    batch = wf.db.get_batch(f"{cid}-B1") if mixed else None
    original = mock.refund_capture

    def post_then_timeout(*args, **kwargs):
        original(*args, **kwargs)
        raise PayPalError("refund reply lost", status_code=408)

    pp.refund_capture.side_effect = post_then_timeout
    with pytest.raises(PayPalError):
        if batch:
            wf.mixed.approve_batch(cid, batch["id"], li.to_str(batch["amount_minor"], batch["currency"]),
                                   batch["items_hash"])
        else:
            wf.approve(cid)
    rid = next(iter(mock.refunds_by_request.values()))["id"]
    capture_id = wf.db.get_case(cid)["capture_id"]
    base = mock.get_refund(rid)
    base["links"] = [{"rel": "up", "href": f"https://api-m.sandbox.paypal.com/v2/payments/captures/{capture_id}"}]
    return wf, pp, cid, batch, rid, base


def test_single_unknown_resolves_from_exact_paypal_get_without_second_refund(settings):
    wf, pp, cid, _, rid, proof = lost_reply_case(settings)
    pp.get_refund.side_effect = lambda *_a, **_kw: proof
    wf.confirm_unknown_refund(cid, rid)
    case = wf.db.get_case(cid)
    assert case["status"] == "REFUND_COMPLETED" and case["refund_id"] == rid
    assert case["completed_via"] == "verified_get"
    assert pp.refund_capture.call_count == 1 and pp.get_refund.call_count == 1
    assert wf.db.verify_chain(cid)["ok"]


@pytest.mark.parametrize("patch, error", [
    ({"id": "OTHER-REFUND"}, "different refund ID"),
    ({"custom_id": "OTHER-CASE"}, "custom_id"),
    ({"amount": {"currency_code": "USD", "value": "1.00"}}, "amount"),
    ({"amount": {"currency_code": "EUR", "value": "49.99"}}, "currency"),
    ({"links": []}, "capture link"),
    ({"links": [{"rel": "up", "href": "https://api-m.sandbox.paypal.com/v2/payments/captures/OTHER"}]},
     "another capture"),
])
def test_single_unknown_rejects_unbound_refund_proof(settings, patch, error):
    wf, pp, cid, _, rid, proof = lost_reply_case(settings)
    pp.get_refund.side_effect = lambda *_a, **_kw: {**proof, **patch}
    with pytest.raises(RefundNotAllowed, match=error):
        wf.confirm_unknown_refund(cid, rid)
    assert wf.db.get_case(cid)["status"] == "REFUND_OUTCOME_UNKNOWN"
    assert pp.refund_capture.call_count == 1
    assert wf.db.verify_chain(cid)["ok"]


def test_refund_lookup_rejects_non_paypal_capture_link(settings):
    wf, pp, cid, _, rid, proof = lost_reply_case(settings)
    proof["links"][0]["href"] = proof["links"][0]["href"].replace("api-m.sandbox.paypal.com", "evil.example")
    pp.get_refund.side_effect = lambda *_a, **_kw: proof
    with pytest.raises(RefundNotAllowed, match="no matching capture link"):
        wf.confirm_unknown_refund(cid, rid)
    assert wf.db.get_case(cid)["status"] == "REFUND_OUTCOME_UNKNOWN"
    assert pp.refund_capture.call_count == 1


def test_single_lookup_refuses_if_case_changes_during_paypal_get(settings):
    wf, pp, cid, _, rid, proof = lost_reply_case(settings)

    def changed_during_get(*_args, **_kwargs):
        wf.db.update_case(cid, amount="50.00")
        return proof

    pp.get_refund.side_effect = changed_during_get
    with pytest.raises(RefundNotAllowed, match="changed while PayPal was checked"):
        wf.confirm_unknown_refund(cid, rid)
    assert wf.db.get_case(cid)["status"] == "REFUND_OUTCOME_UNKNOWN"
    assert pp.refund_capture.call_count == 1
    assert wf.db.verify_chain(cid)["ok"]


def test_invalid_refund_id_is_rejected_before_paypal_get(settings):
    wf, pp, cid, _, _, _ = lost_reply_case(settings)
    with pytest.raises(RefundNotAllowed, match="valid PayPal refund ID"):
        wf.confirm_unknown_refund(cid, "../orders/OTHER")
    pp.get_refund.assert_not_called()
    assert pp.refund_capture.call_count == 1


def test_partial_unknown_resolves_only_for_its_batch(settings):
    wf, pp, cid, batch, rid, proof = lost_reply_case(settings, mixed=True)
    assert batch is not None
    pp.get_refund.side_effect = lambda *_a, **_kw: proof
    wf.mixed.confirm_unknown_refund(cid, batch["id"], rid)
    saved = wf.db.get_batch(batch["id"])
    assert saved["status"] == "COMPLETED" and saved["refund_id"] == rid
    assert pp.refund_capture.call_count == 1 and pp.get_refund.call_count == 1
    # Even a later row rewrite cannot make a verified refund payable again: the chain remembers it.
    wf.db.update_batch(batch["id"], status="APPROVED", refund_id=None)
    with pytest.raises(RefundNotAllowed, match="audit trail already records"):
        wf.mixed.retry_batch(cid, batch["id"])
    assert pp.refund_capture.call_count == 1
    assert wf.db.verify_chain(cid)["ok"]


@pytest.mark.parametrize("patch, error", [
    ({"custom_id": "OTHER-BATCH"}, "custom_id"),
    ({"amount": {"currency_code": "USD", "value": "1.00"}}, "amount"),
    ({"links": []}, "capture link"),
])
def test_partial_unknown_rejects_unbound_refund_proof(settings, patch, error):
    wf, pp, cid, batch, rid, proof = lost_reply_case(settings, mixed=True)
    assert batch is not None
    pp.get_refund.side_effect = lambda *_a, **_kw: {**proof, **patch}
    with pytest.raises(RefundNotAllowed, match=error):
        wf.mixed.confirm_unknown_refund(cid, batch["id"], rid)
    assert wf.db.get_batch(batch["id"])["status"] == "UNKNOWN"
    assert pp.refund_capture.call_count == 1
    assert wf.db.verify_chain(cid)["ok"]


def test_partial_lookup_refuses_if_batch_changes_during_paypal_get(settings):
    wf, pp, cid, batch, rid, proof = lost_reply_case(settings, mixed=True)
    assert batch is not None

    def changed_during_get(*_args, **_kwargs):
        wf.db.update_batch(batch["id"], amount_minor=batch["amount_minor"] + 1)
        return proof

    pp.get_refund.side_effect = changed_during_get
    with pytest.raises(RefundNotAllowed, match="changed while PayPal was checked"):
        wf.mixed.confirm_unknown_refund(cid, batch["id"], rid)
    assert wf.db.get_batch(batch["id"])["status"] == "UNKNOWN"
    assert pp.refund_capture.call_count == 1
    assert wf.db.verify_chain(cid)["ok"]


def test_dashboard_refund_id_form_uses_get_only(settings):
    mock = MockPayPalClient()
    pp = MagicMock(wraps=mock, is_mock=False)
    app = create_app(settings=settings, paypal=pp, extractor=FakeExtractor())
    client = TestClient(app)
    wf = app.state.workflow
    cid = wf.run_scenario("A")
    original = mock.refund_capture

    def post_then_timeout(*args, **kwargs):
        original(*args, **kwargs)
        raise PayPalError("refund reply lost", status_code=408)

    pp.refund_capture.side_effect = post_then_timeout
    with pytest.raises(PayPalError):
        wf.approve(cid)
    rid = next(iter(mock.refunds_by_request.values()))["id"]
    capture_id = wf.db.get_case(cid)["capture_id"]
    proof = {**mock.get_refund(rid), "links": [{"rel": "up", "href":
             f"https://api-m.sandbox.paypal.com/v2/payments/captures/{capture_id}"}]}
    pp.get_refund.side_effect = lambda *_a, **_kw: proof

    html = client.get(f"/?case={cid}").text
    assert f'/cases/{cid}/confirm-refund' in html
    response = client.post(f"/cases/{cid}/confirm-refund", data={"refund_id": rid}, follow_redirects=False)
    assert response.status_code == 303
    assert "a PayPal GET of the merchant-identified refund" in client.get(f"/?case={cid}").text
    assert wf.db.get_case(cid)["refund_id"] == rid
    assert pp.refund_capture.call_count == 1


def test_live_paypal_client_is_not_mislabelled_sandbox(settings):
    live = PayPalClient("id", "secret", "https://api-m.paypal.com", allow_live=True)
    wf, _ = make_wf(settings, paypal=live)
    assert wf.paypal_mode == "live"
    with pytest.raises(RefundNotAllowed, match="only for real Sandbox refunds"):
        wf.confirm_unknown_refund("A-UNRELATED", "REFUND123")


def test_mixed_batch_refund_id_form_uses_get_only(settings):
    mock = MockPayPalClient()
    pp = MagicMock(wraps=mock, is_mock=False)
    app = create_app(settings=settings, paypal=pp, extractor=FakeExtractor())
    client = TestClient(app)
    wf = app.state.workflow
    cid = wf.run_scenario("M")
    batch = wf.db.get_batch(f"{cid}-B1")
    original = mock.refund_capture

    def post_then_timeout(*args, **kwargs):
        original(*args, **kwargs)
        raise PayPalError("refund reply lost", status_code=408)

    pp.refund_capture.side_effect = post_then_timeout
    with pytest.raises(PayPalError):
        wf.mixed.approve_batch(cid, batch["id"], li.to_str(batch["amount_minor"], batch["currency"]),
                               batch["items_hash"])
    rid = next(iter(mock.refunds_by_request.values()))["id"]
    capture_id = wf.db.get_case(cid)["capture_id"]
    proof = {**mock.get_refund(rid), "links": [{"rel": "up", "href":
             f"https://api-m.sandbox.paypal.com/v2/payments/captures/{capture_id}"}]}
    pp.get_refund.side_effect = lambda *_a, **_kw: proof

    path = f"/cases/{cid}/batches/{batch['id']}/confirm-refund"
    assert path in client.get(f"/?case={cid}").text
    response = client.post(path, data={"refund_id": rid}, follow_redirects=False)
    assert response.status_code == 303
    assert wf.db.get_batch(batch["id"])["refund_id"] == rid
    assert pp.refund_capture.call_count == 1
