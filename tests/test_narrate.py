"""narrate() must never say the opposite of what the audit title says.

The two regression cases here were real: "Autonomy: AUTO — approval refused …" was rendered as
"the merchant's policy auto-approved this case", and the approved-exchange "Refund API NOT CALLED —
exchange arranged …" was rendered as "the policy rejected the case".
"""
from app.views import narrate


def ev(title, detail=None, stage="workflow"):
    return {"stage": stage, "title": title, "detail": detail or {}}


def test_autonomy_refusal_is_not_narrated_as_an_approval():
    out = narrate(ev("Autonomy: AUTO — approval refused, the case changed meanwhile",
                     {"reason": "the case is no longer awaiting approval"}))
    assert "auto-approved this case" not in out
    assert "refused" in out and "no money moved" in out


def test_autonomy_already_approved_is_not_narrated_as_a_fresh_approval():
    out = narrate(ev("Autonomy: AUTO — this case was already approved, nothing left to do",
                     {"approver": "auto", "source": "auto"}))
    assert "auto-approved this case" not in out
    assert "already approved" in out


def test_autonomy_within_limits_still_reads_as_an_auto_approval():
    out = narrate(ev("Autonomy: AUTO — within the merchant's limits, no human needed",
                     {"why": "the amount is within AUTO_REFUND_MAX_AMOUNT"}))
    assert "auto-approved this case" in out and "AUTO_REFUND_MAX_AMOUNT" in out


def test_exchange_not_called_is_not_narrated_as_a_policy_rejection():
    out = narrate(ev("Refund API NOT CALLED — exchange arranged (replacement via the MOCK supplier), no refund",
                     {"refund_id": None}, stage="paypal"))
    assert "policy rejected" not in out
    assert "exchange was approved" in out


def test_policy_rejection_keeps_its_wording():
    out = narrate(ev("Refund API NOT CALLED — policy rejected the case", {"refund_id": None}, stage="paypal"))
    assert "policy rejected" in out


def test_refund_unknown_chain_is_narrated():
    assert "UNKNOWN" in narrate(ev("Refund outcome UNKNOWN — no reply from PayPal; checking",
                                   {"status_code": None}, stage="paypal"))
    out = narrate(ev("Checked with PayPal after the unanswered refund call: capture is REFUNDED — the request "
                     "went through. Recovering the refund with the same PayPal-Request-Id.",
                     {"capture_status": "REFUNDED"}, stage="paypal"))
    assert "went through" in out
    out = narrate(ev("Checked with PayPal after the unanswered refund call: capture is COMPLETED, no refund "
                     "seen yet. Retry is safe: it reuses the same PayPal-Request-Id.",
                     {"capture_status": "COMPLETED"}, stage="paypal"))
    assert "retry stays safe" in out
    assert "re-sent once" in narrate(ev("Recovered the refund from PayPal (reconcile): same PayPal-Request-Id "
                                        "re-sent once, PayPal returned the refund it had already made",
                                        {"refund_id": "R1", "status": "COMPLETED", "trigger": "reconcile"},
                                        stage="paypal"))


def test_run_skip_and_stop_titles_are_narrated():
    assert "reset" in narrate(ev("Run skipped — a demo reset is in progress", {"status": "NEW"}))
    assert "already in flight" in narrate(ev("Run skipped — another run of this case is already in flight",
                                             {"status": "NEW"}))
    assert "finalized" in narrate(ev("Run stopped — the case was already finalized (a duplicate run arrived "
                                     "after the case was completed / rejected / declined)", {}))


def test_webhook_family_all_get_the_period_treatment():
    for title in ("Verified PayPal webhook moved refund PENDING → COMPLETED",
                  "Late PayPal webhook PAYMENT.CAPTURE.REFUNDED (sent 2026-10-08T22:00:00Z) — payload not "
                  "trusted for a state change; refund re-read from PayPal instead",
                  "Duplicate PayPal webhook delivery ignored (event already processed)"):
        assert narrate(ev(title, {}, stage="webhook")).endswith(".")
