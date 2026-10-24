"""A payment whose outcome PayPal did not confirm: never a second order, never "nothing was charged".

PayPal's rule (developer.paypal.com/api/rest/reference/idempotency/): a call that timed out or got a 5xx may have
succeeded, and re-sending it with the SAME PayPal-Request-Id returns the first result instead of doing the work
again. Keys are kept for 6 hours (Orders v2 capture reference). So:

* A card charge whose reply was lost is asked again once with the same request id. It is never followed by a
  second (wallet) order, which would ask the buyer to pay twice.
* If PayPal still does not answer, the case says the outcome is UNKNOWN (not "payment failed, nothing to refund")
  and "Check the payment with PayPal" re-sends the same request inside the 6-hour window.
* The same holds for the buyer-approval capture and for mixed orders. A definite PayPal "no" (4xx) keeps the old
  behaviour: the card path falls back to buyer approval.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import inbox
from app.agent_desk import next_step
from app.paypal_client import PayPalError
from app.paypal_mock import MockPayPalClient
from app.workflow import PAYMENT_UNKNOWN, RefundNotAllowed
from tests.helpers import make_wf


def timeout() -> PayPalError:
    return PayPalError("Read timed out", status_code=None, sent=True)


def lose_replies(pp, method: str, charged: int = 1, silent: int = 0) -> None:
    """The first `charged` calls reach PayPal and do the work, then the reply is lost; the next `silent` calls
    time out without reaching PayPal; later calls go through."""
    real = getattr(pp._mock_wraps, method)
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= charged:
            real(*args, **kwargs)
            raise timeout()
        if calls["n"] <= charged + silent:
            raise timeout()
        return real(*args, **kwargs)
    getattr(pp, method).side_effect = flaky


def captures(pp) -> int:
    return len(pp._mock_wraps.captures)


def test_a_lost_card_reply_is_asked_again_never_followed_by_a_second_order(settings):
    wf, pp = make_wf(settings)
    lose_replies(pp, "create_order_with_card")
    case_id = wf.run_scenario("A")
    case = wf.db.get_case(case_id)
    assert pp.create_order.call_count == 0  # no wallet order: the buyer is never asked to pay a second time
    assert captures(pp) == 1 and case["capture_id"] and case["status"] == "PENDING_APPROVAL"
    ids = {c.args[4] for c in pp.create_order_with_card.call_args_list}
    assert ids == {f"tradeos-order-{case_id}"}  # both attempts carried the same PayPal-Request-Id


def test_an_unconfirmed_payment_says_so_and_can_be_checked_without_charging_twice(settings):
    wf, pp = make_wf(settings)
    lose_replies(pp, "create_order_with_card", charged=1, silent=1)
    case_id = wf.run_scenario("A")
    case = wf.db.get_case(case_id)
    assert case["status"] == "ERROR" and case["order_status"] == PAYMENT_UNKNOWN and not case["capture_id"]
    assert pp.create_order.call_count == 0 and captures(pp) == 1  # PayPal did charge, TradeOS does not know yet
    row = {r["id"]: r for r in inbox.inbox_rows(wf)}[case_id]
    assert row["bucket"] == "needs_you" and "did not confirm" in row["next_step"]
    assert "nothing to refund" not in row["next_step"]
    wf.retry_payment(case_id)
    case = wf.db.get_case(case_id)
    assert case["capture_id"] and case["status"] == "PENDING_APPROVAL" and captures(pp) == 1  # the same charge
    with pytest.raises(RefundNotAllowed):
        wf.retry_payment(case_id)  # nothing left to check


def test_a_definite_card_refusal_still_falls_back_to_buyer_approval(settings):
    wf, pp = make_wf(settings)
    pp.create_order_with_card.side_effect = PayPalError("Card refused", status_code=422, name="UNPROCESSABLE_ENTITY")
    case_id = wf.run_scenario("A")
    assert wf.db.get_case(case_id)["status"] == "AWAITING_BUYER_APPROVAL" and pp.create_order.call_count == 1


def test_a_lost_buyer_approval_capture_reply_is_recoverable(settings):
    from unittest.mock import MagicMock
    wf, pp = make_wf(settings, paypal=MagicMock(wraps=MockPayPalClient(card_capture=False), is_mock=True))
    case_id = wf.run_scenario("A")
    assert wf.db.get_case(case_id)["status"] == "AWAITING_BUYER_APPROVAL"
    lose_replies(pp, "capture_order", charged=1, silent=0)
    wf.complete_buyer_approval(case_id)
    case = wf.db.get_case(case_id)
    assert case["status"] == "ERROR" and case["order_status"] == PAYMENT_UNKNOWN and captures(pp) == 1
    wf.retry_payment(case_id)
    case = wf.db.get_case(case_id)
    assert case["capture_id"] and case["status"] == "PENDING_APPROVAL" and captures(pp) == 1


def test_a_mixed_order_with_a_lost_card_reply_recovers_as_a_mixed_order(settings):
    wf, pp = make_wf(settings)
    lose_replies(pp, "create_order_with_card", charged=1, silent=1)
    case_id = wf.run_scenario("M")
    case = wf.db.get_case(case_id)
    assert case["status"] == "ERROR" and case["order_status"] == PAYMENT_UNKNOWN and captures(pp) == 1
    wf.retry_payment(case_id)
    case = wf.db.get_case(case_id)
    assert case["capture_id"] and case["decision"] == "MIXED" and captures(pp) == 1


def test_the_check_is_refused_once_paypal_has_forgotten_the_request_id(settings):
    """After 6 hours PayPal no longer recognises the request id, so re-sending it could charge again. A person
    checks PayPal by hand instead."""
    wf, pp = make_wf(settings)
    lose_replies(pp, "create_order_with_card", charged=1, silent=1)
    case_id = wf.run_scenario("A")
    late = datetime.now(timezone.utc) + timedelta(hours=6, minutes=1)
    wf.today = lambda: late.date()
    wf._now = lambda: late.isoformat()
    with pytest.raises(RefundNotAllowed, match="6 hours"):
        wf.retry_payment(case_id)
    assert captures(pp) == 1 and pp.create_order_with_card.call_count == 2


def test_a_check_is_refused_for_a_payment_paypal_definitely_refused(settings):
    wf, pp = make_wf(settings)
    pp.create_order_with_card.side_effect = PayPalError("Card refused", status_code=422)
    pp.create_order.side_effect = PayPalError("Bad request", status_code=400)
    case_id = wf.run_scenario("A")
    case = wf.db.get_case(case_id)
    assert case["status"] == "ERROR" and case["order_status"] != PAYMENT_UNKNOWN
    with pytest.raises(RefundNotAllowed):
        wf.retry_payment(case_id)
    row = {r["id"]: r for r in inbox.inbox_rows(wf)}[case_id]
    assert row["bucket"] == "closed" and "nothing to refund" in row["next_step"]


def test_an_agent_is_told_not_to_order_again_while_the_payment_is_unconfirmed(settings):
    wf, pp = make_wf(settings)
    lose_replies(pp, "create_order_with_card", charged=1, silent=1)
    order = wf.agents.place_order("Maria", agent="Shop assistant")
    words = next_step(wf.db.get_case(order))
    assert "Do not place a new order" in words and "No payment was captured" not in words
    with pytest.raises(ValueError, match="Do not place a new order"):
        wf.agents.submit_request(order, "wrong colour", agent="Shop assistant", on_behalf_of="Maria")


def test_a_policy_retry_and_a_demo_reset_never_overlap(settings):
    """The policy retry used to run outside the in-flight registry, so a demo reset could archive the case
    underneath it. It now claims the case like a run does."""
    wf, pp = make_wf(settings)
    pp.get_capture.side_effect = [PayPalError("timeout", status_code=503)]
    case_id = wf.run_scenario("A")
    assert wf.db.get_case(case_id)["status"] == "ERROR"
    assert wf.begin_reset()
    try:
        with pytest.raises(RefundNotAllowed, match="reset"):
            wf.retry_policy_check(case_id)
    finally:
        wf.end_reset()


def test_dashboard_and_mcp_show_an_unconfirmed_payment_honestly(settings):
    from tests.helpers import make_app
    client, pp, wf = make_app(settings)
    lose_replies(pp, "create_order_with_card", charged=1, silent=1)
    r = client.post("/demo/run/A", follow_redirects=False)
    case_id = r.headers["location"].split("=")[1]
    page = client.get(f"/?case={case_id}").text
    assert "Payment not confirmed by PayPal" in page and f'action="/cases/{case_id}/retry-payment"' in page
    assert client.post(f"/cases/{case_id}/retry-payment", follow_redirects=False).status_code == 303
    assert wf.db.get_case(case_id)["status"] == "PENDING_APPROVAL" and captures(pp) == 1
    again = client.post(f"/cases/{case_id}/retry-payment")
    assert again.status_code == 409 and "Only a payment PayPal did not confirm" in again.text


def test_the_mcp_tool_tells_the_agent_not_to_order_again(settings):
    import anyio
    from mcp import Client

    from app.agent_gateway import build_mcp_server
    wf, pp = make_wf(settings)
    lose_replies(pp, "create_order_with_card", charged=1, silent=1)

    async def go():
        async with Client(build_mcp_server(wf, settings)) as client:
            return await client.call_tool("place_demo_order", {"buyer_name": "Maria", "agent_name": "x"})
    result = anyio.run(go)
    text = result.content[0].text
    assert result.is_error and "Do not place a new order" in text and "may have been taken" in text


# partial refunds: PayPal does not document how long it keeps a refund's request id ------------------------------
def unknown_partial_refund(settings):
    """A mixed order's batch refund reaches PayPal and is made, the reply is lost, and the follow-up GET cannot
    reach PayPal either: the batch stays UNKNOWN with the money already refunded."""
    from unittest.mock import MagicMock
    mock = MockPayPalClient()
    real_refund, real_capture = mock.refund_capture, mock.get_capture
    state = {"refunds": 0, "down": False}

    def refund_then_lose_reply(*args, **kwargs):
        state["refunds"] += 1
        result = real_refund(*args, **kwargs)
        if state["refunds"] == 1:
            state["down"] = True  # and PayPal stays unreachable for the follow-up check
            raise timeout()
        return result

    def capture_read(*args, **kwargs):
        if state["down"]:
            raise timeout()
        return real_capture(*args, **kwargs)
    mock.refund_capture, mock.get_capture = refund_then_lose_reply, capture_read
    wf, pp = make_wf(settings, paypal=MagicMock(wraps=mock, is_mock=True))
    case_id = wf.run_scenario("M")
    batch = wf.db.get_batch(f"{case_id}-B1")
    from app import lineitems as li
    with pytest.raises(PayPalError):
        wf.mixed.approve_batch(case_id, batch["id"], li.to_str(batch["amount_minor"], batch["currency"]),
                               batch["items_hash"])
    assert wf.db.get_batch(batch["id"])["status"] == "UNKNOWN" and len(mock.refunds_by_request) == 1
    return wf, mock, case_id, batch["id"], state


def test_an_old_unknown_partial_refund_is_not_re_sent(settings):
    """After the window, the same request id might be a new request to PayPal: a second partial refund of money
    already refunded. Neither the automatic recovery nor a retry click re-sends it; a person checks PayPal."""
    wf, mock, case_id, batch_id, state = unknown_partial_refund(settings)
    sent, state["down"] = state["refunds"], False
    late = datetime.now(timezone.utc) + timedelta(hours=6, minutes=1)
    wf._now = lambda: late.isoformat()
    assert wf.mixed.recover_unknown(case_id, "startup") is False
    with pytest.raises(RefundNotAllowed, match="6 hours"):
        wf.mixed.retry_batch(case_id, batch_id)
    assert state["refunds"] == sent and wf.db.get_batch(batch_id)["status"] == "UNKNOWN"
    assert any("check PayPal by hand" in e["title"] for e in wf.db.timeline(case_id))


def test_a_recent_unknown_partial_refund_is_still_recovered_with_the_same_request_id(settings):
    wf, mock, case_id, batch_id, state = unknown_partial_refund(settings)
    state["down"] = False
    wf.mixed.retry_batch(case_id, batch_id)
    assert wf.db.get_batch(batch_id)["status"] == "COMPLETED" and len(mock.refunds_by_request) == 1


def test_the_window_starts_when_paypal_first_saw_the_request_id(settings):
    """A later re-send of the same id (say, a recovery attempt that also got no answer) does not restart PayPal's
    clock: the key was stored at the first request."""
    wf, mock, case_id, batch_id, state = unknown_partial_refund(settings)
    state["down"] = False
    request_id = wf.db.get_batch(batch_id)["request_id"]
    seven_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat().replace("+00:00", "Z")
    with wf.db.connect() as conn:
        conn.execute("UPDATE paypal_calls SET ts=? WHERE case_id=? AND request_id=?",
                     (seven_hours_ago, case_id, request_id))
        conn.execute("INSERT INTO paypal_calls (case_id, ts, operation, ok, request_id) VALUES (?, ?, ?, 0, ?)",
                     (case_id, datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "refund_capture",
                      request_id))
    with pytest.raises(RefundNotAllowed, match="6 hours"):
        wf.mixed.retry_batch(case_id, batch_id)


def test_a_check_that_also_times_out_does_not_restart_paypals_clock(settings):
    """PayPal stored the key at the first request. A check five hours later that also got no answer re-sent it,
    but the window still ends six hours after the FIRST send."""
    wf, pp = make_wf(settings)
    lose_replies(pp, "create_order_with_card", charged=1, silent=3)  # the run asks twice, the check twice

    def age_calls(hours: float, before_id: int | None = None) -> None:
        then = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
        with wf.db.connect() as conn:
            conn.execute("UPDATE paypal_calls SET ts=? WHERE case_id=? AND operation='create_order_with_card'"
                         + (" AND id<?" if before_id else ""), (then, case_id, *((before_id,) if before_id else ())))

    case_id = wf.run_scenario("A")
    first_two = max(c["id"] for c in wf.db.paypal_calls(case_id, "create_order_with_card")) + 1
    age_calls(5)                     # the run was five hours ago
    wf.retry_payment(case_id)        # still no answer: unknown again (its two calls are logged now)
    assert wf.db.get_case(case_id)["order_status"] == PAYMENT_UNKNOWN
    age_calls(7, before_id=first_two)  # the first request is now seven hours old; the check's calls are recent
    with pytest.raises(RefundNotAllowed, match="6 hours"):
        wf.retry_payment(case_id)
    assert captures(pp) == 1


def test_the_whole_page_tells_one_story_for_an_unconfirmed_payment(settings):
    """The card said 'not confirmed' while the pipeline said 'order / capture failed', the heading 'PayPal error'
    and the case chip 'ERROR'. Every part now says the same thing, and the inbox does not call an unread message
    'Unclear'."""
    from tests.helpers import make_app
    client, pp, wf = make_app(settings)
    lose_replies(pp, "create_order_with_card", charged=1, silent=1)
    case_id = client.post("/demo/run/A", follow_redirects=False).headers["location"].split("=")[1]
    page = client.get(f"/?case={case_id}").text
    assert "payment not confirmed by PayPal" in page and "PayPal order / capture failed" not in page
    assert "Pending action: confirm the payment with PayPal" in page and "Result: PayPal error" not in page
    assert '<span class="chip warn">Payment not confirmed</span>' in page
    assert {r["id"]: r for r in inbox.inbox_rows(wf)}[case_id]["request"] == "Not read yet"
