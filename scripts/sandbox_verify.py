"""Post-deploy Sandbox check for the PayPal depth work (#10-#12, #20). Read-mostly; uses the public demo endpoints.

    python scripts/sandbox_verify.py https://<your-render-host>

Creates ONE new Case A (one Sandbox order + one Sandbox refund of the demo amount), ONE Case B and ONE
Case R (a forced 422 refund failure, then a retry that refunds).
It needs no credentials: it only talks to the deployed app. Exit code 0 = all checks passed.
"""
from __future__ import annotations

import sys
import time

import httpx


def main(base: str) -> int:
    c = httpx.Client(base_url=base.rstrip("/"), timeout=90, follow_redirects=False)
    fails: list[str] = []

    def check(ok: bool, label: str) -> None:
        print(("PASS " if ok else "FAIL ") + label)
        if not ok:
            fails.append(label)

    health = c.get("/healthz").json()
    check(health.get("paypal_mode") == "sandbox", f"PayPal mode is sandbox (got {health.get('paypal_mode')})")
    check(bool(health.get("webhook_configured")), "PAYPAL_WEBHOOK_ID configured")

    # Case A: one real Sandbox refund
    r = c.post("/demo/run/A")
    case_a = r.headers["location"].split("case=")[1]
    check(c.post(f"/cases/{case_a}/approve").status_code == 303, f"Case A {case_a} approved")
    data = c.get(f"/api/cases/{case_a}").json()
    case, calls = data["case"], data["paypal_calls"]
    check(case["refund_status"] in ("COMPLETED", "PENDING"), f"refund {case['refund_id']} status {case['refund_status']}")
    refund_calls = [x for x in calls if x["operation"] == "refund_capture"]
    check(len(refund_calls) == 1, "exactly one refund call")
    dbg = refund_calls[0].get("debug_id") if refund_calls else None
    check(bool(dbg) and not str(dbg).startswith("mock"), f"real PayPal-Debug-Id on the refund call: {dbg}")
    check(all(x.get("request_id") for x in calls if x["operation"] in ("create_order_with_card", "refund_capture")),
          "PayPal-Request-Id recorded on order + refund")
    check(c.post(f"/cases/{case_a}/refund").status_code == 409, "retry on a finished refund -> 409, no new call")

    # Signed webhook (arrived 16-18 s after the refund in earlier live tests)
    status = None
    for _ in range(18):
        status = c.get(f"/api/cases/{case_a}").json()["case"].get("webhook_status")
        if status == "VERIFIED":
            break
        time.sleep(5)
    check(status == "VERIFIED", f"signed PAYMENT.CAPTURE.REFUNDED verified (webhook_status={status})")
    method = (c.get(f"/api/cases/{case_a}").json()["case"].get("webhook") or {}).get("verify_method")
    check(method in ("self", "postback"), f"webhook verification method recorded: {method} (self expected)")

    # Check against PayPal (reconciliation)
    c.post(f"/cases/{case_a}/refresh-refund")
    tl = c.get(f"/api/cases/{case_a}").json()["timeline"]
    rec = [e for e in tl if e["stage"] == "reconcile"]
    check(bool(rec) and rec[-1]["title"].startswith("Reconciled with PayPal"),
          f"reconcile result: {rec[-1]['title'] if rec else 'none'}")

    # Hash-chained audit trail
    chain_a = c.get(f"/cases/{case_a}/audit/verify").json()
    check(chain_a.get("ok") is True, f"Case A audit trail intact: {chain_a.get('entries')} entries, head "
          f"{(chain_a.get('head') or '')[:12]}")

    # Case B: blocked, refund API never called
    r = c.post("/demo/run/B")
    case_b = r.headers["location"].split("case=")[1]
    check(c.post(f"/cases/{case_b}/approve").status_code == 409, f"Case B {case_b} approve -> 409")
    b_calls = c.get(f"/api/cases/{case_b}").json()["paypal_calls"]
    check(not any(x["operation"] == "refund_capture" for x in b_calls), "Case B: refund API not called")
    chain_b = c.get(f"/cases/{case_b}/audit/verify").json()
    check(chain_b.get("ok") is True, f"Case B audit trail intact: {chain_b.get('entries')} entries")
    page = c.get(f"/?case={case_a}").text
    check("Audit trail intact:" in page, "audit trail badge rendered on Case A page")

    # Logic-review fixes (#20): chained case state, how COMPLETED was confirmed, GET without side effects
    case = c.get(f"/api/cases/{case_a}").json()["case"]
    st_a = c.get(f"/cases/{case_a}/audit/verify").json().get("chained_state") or {}
    check(st_a.get("decision") == "ELIGIBLE" and st_a.get("human_decision") == "APPROVED"
          and st_a.get("status") == case["status"],
          f"Case A decision/approval/status on the hash chain: {st_a}")
    check(case.get("refund_request_id") == f"tradeos-refund-{case_a}"
          and case.get("completed_via") in ("refund_api", "webhook", "reconcile"),
          f"Case A request id {case.get('refund_request_id')}, COMPLETED confirmed via {case.get('completed_via')}")
    st_b = c.get(f"/cases/{case_b}/audit/verify").json().get("chained_state") or {}
    check(st_b.get("decision") == "REJECTED" and st_b.get("human_decision") is None,
          f"Case B rejection on the hash chain, no approval: {st_b}")
    before = c.get(f"/api/cases/{case_a}").json()["case"]["status"]
    r = c.get(f"/cases/{case_a}/paypal-return")
    check(r.status_code == 200 and c.get(f"/api/cases/{case_a}").json()["case"]["status"] == before,
          "GET /paypal-return changes nothing")

    # Refund failure (PayPal 422) -> 'PayPal refused, no money moved' -> retry COMPLETED (same request id)
    r = c.post("/demo/run/R")
    case_r = r.headers["location"].split("case=")[1]
    c.post(f"/cases/{case_r}/approve")
    rc = c.get(f"/api/cases/{case_r}").json()["case"]
    page = c.get(f"/?case={case_r}").text
    check(rc["status"] == "REFUND_ERROR" and "no money moved" in page,
          f"Case R {case_r}: PayPal 422 shown as refused, no money moved (status {rc['status']})")
    c.post(f"/cases/{case_r}/refund")
    data = c.get(f"/api/cases/{case_r}").json()
    rcalls = [x for x in data["paypal_calls"] if x["operation"] == "refund_capture"]
    check(data["case"]["status"] == "REFUND_COMPLETED" and len(rcalls) == 2
          and {x["request_id"] for x in rcalls} == {f"tradeos-refund-{case_r}"},
          f"Case R retry COMPLETED with the same PayPal-Request-Id ({len(rcalls)} calls)")

    print(f"\nManual step: look up debug id {dbg} in the PayPal Developer Dashboard (Sandbox) logs.")
    print("RESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: sandbox_verify.py https://<host>")
    sys.exit(main(sys.argv[1]))
