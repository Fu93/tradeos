"""Refund/capture webhook JSON is untrusted even when signed (OWASP Webhook Security / Input Validation):
wrong-typed ids/resources must never 500 (PayPal would retry for 3 days), never change state, never reach the DB
as junk."""
import json
import random

import pytest

from app.webhook_verify import sanitize_payment_event
from tests.helpers import SIG_OK, make_app, run_a

ETYPES = ["PAYMENT.CAPTURE.REFUNDED", "PAYMENT.REFUND.PENDING", "PAYMENT.REFUND.FAILED",
          "PAYMENT.CAPTURE.REVERSED", "PAYMENT.CAPTURE.DECLINED"]
BAD = [{"a": 1}, 10**400, -10**400, [1], True, 1.5, "x" * 100000, "a\x00b\ud83d", None, 5, "str", [1, "a"]]


def post(client, event):
    return client.post("/webhooks/paypal", content=json.dumps(event), headers=SIG_OK)


@pytest.mark.parametrize("et", ETYPES)
@pytest.mark.parametrize("bad", range(len(BAD)), ids=range(len(BAD)))
def test_wrong_typed_fields_never_500_and_never_change_state(settings, et, bad):
    client, _, wf = make_app(settings)
    case_id = run_a(client)
    before = wf.db.get_case(case_id)
    value = BAD[bad]
    shapes = [
        {"id": value, "event_type": et, "resource": {"id": before["refund_id"], "status": "COMPLETED"}},
        {"id": "E1", "event_type": et, "resource": value},
        {"id": "E2", "event_type": et, "resource": {"id": value, "status": value, "links": value,
                                                    "status_details": value, "amount": value}},
        {"id": "E3", "event_type": et, "resource": {"id": "x", "links": [value, {"rel": value, "href": value}]}},
    ]
    for ev in shapes:
        r = post(client, ev)
        assert r.status_code < 500, (ev.keys(), r.status_code, r.text[:200])
    after = wf.db.get_case(case_id)
    assert (after["refund_id"], after["refund_status"], after["status"]) == \
        (before["refund_id"], before["refund_status"], before["status"])
    assert client.get("/").status_code == 200


def test_sanitizer_is_allowlist_and_bounded():
    ev = {"id": "E" * 500, "event_type": "PAYMENT.CAPTURE.REFUNDED", "evil": "x", "resource": {
        "id": "R1", "status": "COMPLETED", "junk": "J" * 10**6, "amount": {"value": "1.00", "currency_code": "USD", "x": 1},
        "status_details": {"reason": "ECHECK", "other": "y"},
        "links": [{"rel": "up", "href": "https://api/captures/C1", "method": "GET"}] * 50}}
    out = sanitize_payment_event(ev)
    assert len(out["id"]) == 120 and "evil" not in out
    res = out["resource"]
    assert "junk" not in res and res["amount"] == {"value": "1.00", "currency_code": "USD"}
    assert res["status_details"] == {"reason": "ECHECK"} and len(res["links"]) == 20
    assert sanitize_payment_event({"id": 10**400, "resource": 5}) == \
        {"id": None, "event_type": None, "create_time": None, "resource": {}}
    assert sanitize_payment_event({"resource": {"id": True}})["resource"] == {}  # bool is not an id
    assert sanitize_payment_event({"resource": {"id": 12345}})["resource"]["id"] == "12345"  # small ints still ok


def test_sanitized_event_still_completes_a_legitimate_refund(settings):
    from tests.helpers import pending_case, refund_event
    client, _, wf, case_id, rid = pending_case(settings)
    assert wf.db.get_case(case_id)["refund_status"] == "PENDING"
    r = post(client, refund_event(rid, status="COMPLETED", eid="WH-OK"))
    assert r.status_code == 200 and r.json()["verified"] is True
    assert wf.db.get_case(case_id)["refund_status"] == "COMPLETED"


def test_random_mutation_fuzz_never_500(settings):
    client, _, wf = make_app(settings)
    case_id = run_a(client)
    rid = wf.db.get_case(case_id)["refund_id"]
    rng = random.Random(1337)

    def junk(depth=0):
        return rng.choice([lambda: rng.choice(BAD), lambda: {"k": junk(depth + 1)} if depth < 3 else 0,
                           lambda: [junk(depth + 1)] if depth < 3 else 0, lambda: rid, lambda: "up"])()

    for _ in range(300):
        res = {"id": rid, "status": "COMPLETED", "links": [{"rel": "up", "href": "https://x/captures/C"}]}
        for k in rng.sample(list(res) + ["amount", "status_details", "create_time"], 2):
            res[k] = junk()
        ev = {"id": junk() if rng.random() < .4 else f"F{rng.random()}", "event_type": rng.choice(ETYPES),
              "resource": res if rng.random() < .9 else junk()}
        assert post(client, ev).status_code < 500, ev
