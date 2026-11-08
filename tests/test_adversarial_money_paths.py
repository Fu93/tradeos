"""Adversarial checks on public-demo and money-path boundaries introduced in the hardening commit."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.paypal_client import PayPalError
from app.paypal_mock import MockPayPalClient
from app.workflow import RefundNotAllowed
from tests.helpers import make_app
from tests.test_mixed_orders import approve, only_batch, start


def test_public_demo_hides_private_capture_import_and_revoke(settings):
    client, _, _ = make_app(settings)
    assert client.post("/merchant/import-sandbox-capture",
                       data={"capture_id": "CAP-1", "buyer_name": "X"}).status_code == 404
    assert client.post("/merchant/orders/A-1/revoke-return-pass").status_code == 404


def test_csrf_blocks_cross_origin_money_post_on_public_demo(settings):
    client, _, wf = make_app(settings)
    cid = wf.run_scenario("A")
    blocked = client.post(f"/cases/{cid}/approve",
                          headers={"Origin": "https://attacker.example"}, follow_redirects=False)
    assert blocked.status_code == 403
    assert wf.db.get_case(cid)["status"] == "PENDING_APPROVAL"
    assert not wf.db.paypal_calls(cid, "refund_capture")


def test_mixed_and_single_refund_cannot_double_spend_same_capture(settings):
    wf, pp, cid = start(settings)
    batch = only_batch(wf, cid)
    approve(wf, cid, batch)
    assert only_batch(wf, cid)["status"] == "COMPLETED"
    with pytest.raises(RefundNotAllowed, match="per batch|mixed"):
        wf.execute_refund(cid)
    assert pp.refund_capture.call_count == 1


def test_mixed_error_retry_mints_new_request_id_after_six_hours(settings):
    mock = MockPayPalClient()
    wf, pp, cid = start(settings, pp=MagicMock(wraps=mock, is_mock=True))
    batch = only_batch(wf, cid)
    mock.fail_refund = True
    with pytest.raises(PayPalError):
        approve(wf, cid, batch)
    prior = only_batch(wf, cid)["request_id"]
    assert only_batch(wf, cid)["status"] == "ERROR"
    mock.fail_refund = False
    wf._now = lambda: (datetime.now(timezone.utc) + timedelta(hours=7)).isoformat()
    wf.mixed.retry_batch(cid, batch["id"])
    from app.paypal_client import PAYPAL_REQUEST_ID_MAX_LEN, mint_retry_request_id
    done = only_batch(wf, cid)
    assert done["status"] == "COMPLETED"
    assert done["request_id"] == mint_retry_request_id(prior)
    assert len(done["request_id"]) <= PAYPAL_REQUEST_ID_MAX_LEN
    assert {c.args[1] for c in pp.refund_capture.call_args_list} == {prior, done["request_id"]}


def test_confirm_refund_endpoint_is_csrf_guarded_and_get_only_on_money(settings):
    client, pp, wf = make_app(settings)
    # Force UNKNOWN via workflow then hit HTTP confirm with cross-origin → 403 before PayPal GET.
    cid = wf.run_scenario("A")
    original = pp._mock_wraps.refund_capture

    def lost(*a, **k):
        original(*a, **k)
        raise PayPalError("timeout", status_code=408)

    pp.refund_capture.side_effect = lost
    with pytest.raises(PayPalError):
        wf.approve(cid)
    assert client.post(f"/cases/{cid}/confirm-refund", data={"refund_id": "X"},
                       headers={"Origin": "https://evil.example"}, follow_redirects=False).status_code == 403
    assert wf.db.get_case(cid)["status"] == "REFUND_OUTCOME_UNKNOWN"
