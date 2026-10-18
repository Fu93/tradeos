"""Post-deploy Sandbox check for the PayPal depth work (#10-#12, #20) and the autonomy path (#23).

    python scripts/sandbox_verify.py https://<your-render-host>
    AUTO_ENABLED=1 uvicorn app.main:app --port 8000   # then, in another shell:
    python scripts/sandbox_verify.py http://localhost:8000 --allow-autonomy

Creates ONE new Case A (one Sandbox order + one Sandbox refund of the demo amount), ONE Case B, ONE exchange
(0 refund calls) and ONE Case R (a forced 422 refund failure, then a retry that refunds).
It needs no credentials: it only talks to the app it is pointed at.

Case A is asserted against the target's ACTUAL autonomy setting, read from /healthz:
with autonomy OFF the case must wait for a person and make no refund call until one approves; with autonomy
ON the same case must already be REFUND_COMPLETED with no approve call, approval_source=auto on the hash
chain, and a page that credits the merchant's policy rather than a human. Exit code 0 = all checks passed.

Optional extra (opt-in, NOT part of the default 31 checks): ``--mixed`` appends the mixed-order partial-refund check,
which does ONE real Sandbox partial refund (a 4-line order: 3 returned, 1 exchanged) and confirms the amount PayPal
reports equals the amount the code computed, with the PayPal-Debug-Id captured. ``--mixed-only`` runs just that check.
Against a local app on PAYPAL_MOCK=1 add ``--allow-mock``: the same assertions run against the mock and are labelled
"MOCK - not live proof" (no real PayPal-Debug-Id, no signed webhook). Live runs happen only after deploy.

Autonomy is experimental and must be OFF on the hosted demo, so the run FAILS if /healthz reports
auto_enabled or auto_exchange_enabled true, unless --allow-autonomy (or ALLOW_AUTONOMY=1) is given, which is
meant for local runs of the opt-in path only. deploy-verify never passes it.
"""
from __future__ import annotations

import os
import sys
import time

import httpx


def mixed_checks(c: httpx.Client, check, allow_mock: bool = False) -> None:
    """Mixed order, ONE partial refund: PayPal-reported amount must equal the computed amount (PayPal proves)."""
    tag = " [MOCK - not live proof]" if allow_mock else ""

    def api(case_id: str) -> dict:
        return c.get(f"/api/cases/{case_id}").json()

    r = c.post("/demo/run/M")
    if r.status_code != 303:
        check(False, f"POST /demo/run/M -> {r.status_code} (expected 303): {r.text[:200]}")
        return
    cid = r.headers["location"].split("case=")[1]
    d = api(cid)
    mixed, batches = d["mixed"], d["mixed"]["batches"]
    res = sorted(i["resolution"] for i in mixed["items"])
    check(res == ["EXCHANGE", "REFUND", "REFUND", "REFUND"], f"Mixed {cid}: 3 items resolved REFUND, 1 EXCHANGE ({res})")
    check(len(batches) == 1 and batches[0]["status"] == "PROPOSED" and batches[0]["amount_minor"] > 0,
          f"Mixed {cid}: one batch awaits approval (computed {batches[0]['amount_minor'] if batches else None} minor units)")
    check(not [x for x in d["paypal_calls"] if x["operation"] == "refund_capture"], "Mixed: no refund call before a person approves")
    b = batches[0]
    cur = b["currency"]
    value = f"{b['amount_minor'] // 100}.{b['amount_minor'] % 100:02d}"  # the demo order is two-decimal (USD)
    check(c.post(f"/cases/{cid}/approve").status_code == 409, "Mixed: whole-case Approve refused (approval is per batch)")
    stale = c.post(f"/cases/{cid}/batches/{b['id']}/approve", data={"expected_total": "0.01", "expected_hash": b["items_hash"]})
    check(stale.status_code == 409 and not [x for x in api(cid)["paypal_calls"] if x["operation"] == "refund_capture"],
          "Mixed: approval carrying a different total than the screen is refused, no refund call")
    ok = c.post(f"/cases/{cid}/batches/{b['id']}/approve", data={"expected_total": value, "expected_hash": b["items_hash"]})
    check(ok.status_code == 303, f"Mixed: batch approved by a person with the exact total {value} {cur}")
    d = api(cid)
    nb = d["mixed"]["batches"][0]
    calls = [x for x in d["paypal_calls"] if x["operation"] == "refund_capture"]
    check(len(calls) == 1 and calls[0]["request_id"] == nb["request_id"] and str(nb["request_id"]).startswith("tos-mx-")
          and len(nb["request_id"]) <= 38, f"Mixed: exactly one refund call, deterministic PayPal-Request-Id {nb['request_id']}")
    dbg = calls[0].get("debug_id") if calls else None
    check(bool(dbg) and (allow_mock or not str(dbg).startswith("mock")), f"Mixed: PayPal-Debug-Id captured on the refund call: {dbg}{tag}")
    check(nb["status"] in ("COMPLETED", "PENDING") and nb["paypal_amount"] == f"{value} {cur}",
          f"Mixed: PayPal-reported amount {nb['paypal_amount']} equals computed {value} {cur} (batch {nb['status']}){tag}")
    check(c.post(f"/cases/{cid}/batches/{b['id']}/approve", data={"expected_total": value, "expected_hash": b["items_hash"]}).status_code == 409
          and len([x for x in api(cid)["paypal_calls"] if x["operation"] == "refund_capture"]) == 1,
          "Mixed: second approval of the same batch -> 409, still one refund call")
    led = d["mixed"]["ledger"]
    check(led["committed_minor"] == b["amount_minor"] and led["remaining_minor"] == led["captured_minor"] - b["amount_minor"],
          f"Mixed: ledger refunded {led['committed_minor']} + remaining {led['remaining_minor']} == captured {led['captured_minor']}")
    check(c.post(f"/cases/{cid}/refund").status_code == 409, "Mixed: legacy single-refund endpoint refused (409)")
    if allow_mock:
        print("SKIP signed-webhook check (mock mode: PayPal sends nothing)")
    else:
        status = None
        for _ in range(18):
            status = api(cid)["case"].get("webhook_status")
            if status == "VERIFIED":
                break
            time.sleep(5)
        check(status == "VERIFIED", f"Mixed: signed PAYMENT.CAPTURE.REFUNDED matched the batch refund id (webhook_status={status})")
    c.post(f"/cases/{cid}/refresh-refund")
    tl = api(cid)["timeline"]
    rec = [e for e in tl if e["stage"] == "reconcile"]
    check(bool(rec) and rec[-1]["title"].startswith("Reconciled with PayPal"), f"Mixed: reconcile result: {rec[-1]['title'] if rec else 'none'}")
    chain = c.get(f"/cases/{cid}/audit/verify").json()
    check(chain.get("ok") is True, f"Mixed: audit trail intact: {chain.get('entries')} entries")
    print(f"Manual step: look up debug id {dbg} in the PayPal Developer Dashboard (Sandbox) logs.")


def main(base: str, allow_autonomy: bool = False, mixed: bool = False, mixed_only: bool = False,
         allow_mock: bool = False) -> int:
    allow_autonomy = allow_autonomy or os.environ.get("ALLOW_AUTONOMY") == "1"
    c = httpx.Client(base_url=base.rstrip("/"), timeout=90, follow_redirects=False)
    fails: list[str] = []

    def check(ok: bool, label: str) -> None:
        print(("PASS " if ok else "FAIL ") + label)
        if not ok:
            fails.append(label)

    if mixed_only:
        health = c.get("/healthz").json()
        check(health.get("paypal_mode") == ("mock" if allow_mock else "sandbox"),
              f"PayPal mode is {'mock (--allow-mock)' if allow_mock else 'sandbox'} (got {health.get('paypal_mode')})")
        mixed_checks(c, check, allow_mock)
        print("RESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
        return 0 if not fails else 1

    health = c.get("/healthz").json()
    check(health.get("paypal_mode") == "sandbox", f"PayPal mode is sandbox (got {health.get('paypal_mode')})")
    check(bool(health.get("webhook_configured")), "PAYPAL_WEBHOOK_ID configured")
    auto = bool(health.get("auto_enabled"))
    auto_ex = bool(health.get("auto_exchange_enabled"))
    check("auto_exchange_enabled" in health, "/healthz reports auto_exchange_enabled")
    if auto or auto_ex:
        print("::warning::AUTONOMY IS ON at the target (auto_enabled=%s auto_exchange_enabled=%s)" % (auto, auto_ex))
        check(allow_autonomy, "autonomy is OFF at the target (experimental; must stay off in the hosted demo; "
                              "pass --allow-autonomy only for deliberate local runs)")
        if not allow_autonomy:
            return 1  # stop before creating any case against an unexpectedly autonomous target
    print(f"Autonomy {'ON' if auto else 'OFF'} (auto_refund_max_amount={health.get('auto_refund_max_amount')})")

    def run_case(path: str) -> str:
        """POST an endpoint that must redirect to a case; a 429/409 page fails loudly with its
        flash text instead of dying on a KeyError later (e.g. the order-creation rate limit when
        this script runs twice within a minute, or visitors burning the demo budget)."""
        r = c.post(path)
        if r.status_code != 303:
            check(False, f"POST {path} -> {r.status_code} (expected 303): {r.text[:200]}")
            raise SystemExit(1)
        return r.headers["location"].split("case=")[1]

    # Case A: one real Sandbox refund. Who approves it depends on the target's autonomy setting, so
    # the run asserts the configuration it found instead of assuming the one it was written for.
    case_a = run_case("/demo/run/A")
    case = c.get(f"/api/cases/{case_a}").json()["case"]
    if auto:
        check(case["status"] == "REFUND_COMPLETED" and case.get("approval_source") == "auto",
              f"Case A {case_a} completed with no human (status {case['status']}, "
              f"approval_source {case.get('approval_source')!r})")
        page = c.get(f"/?case={case_a}").text
        # No apostrophes in these: Jinja escapes them (merchant&#39;s), so matching the raw text would
        # fail on a correct page.
        check("no human involved" in page and "auto-approved by the merchant" in page,
              "the page credits the merchant's policy, not a human")
        check("Human approved the refund" not in page, "the page never claims a human approved it")
        check(c.post(f"/cases/{case_a}/approve").status_code == 409,
              "Approve on an already-completed case -> 409 (nothing left to approve)")
    else:
        check(case["status"] == "PENDING_APPROVAL" and case.get("approval_source") is None,
              f"Case A {case_a} waits for a person (status {case['status']})")
        check(not [x for x in c.get(f"/api/cases/{case_a}").json()["paypal_calls"]
                   if x["operation"] == "refund_capture"], "no refund call before a person approves")
        check(c.post(f"/cases/{case_a}/approve").status_code == 303, f"Case A {case_a} approved by a person")
        case = c.get(f"/api/cases/{case_a}").json()["case"]
        check(case.get("approval_source") == "human",
              f"approval_source recorded as human (got {case.get('approval_source')!r})")

    data = c.get(f"/api/cases/{case_a}").json()
    case, calls = data["case"], data["paypal_calls"]
    check((case.get("intent") or {}).get("requested_action") == "REFUND", f"Case A is a return for a refund: {case.get('intent')}")
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
    case_b = run_case("/demo/run/B")
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
          and st_a.get("status") == case["status"]
          and st_a.get("approval_source") == ("auto" if auto else "human"),
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

    # Exchange (size swap): supplier replacement (MOCK), human approval, Refund API NOT CALLED
    r = c.post("/cases/free", data={"message": "The shoes are too small. Can I exchange size 42 for size 43?"})
    if r.status_code != 303:
        check(False, f"POST /cases/free -> {r.status_code} (expected 303): {r.text[:200]}")
        raise SystemExit(1)
    case_x = r.headers["location"].split("case=")[1]
    xc = c.get(f"/api/cases/{case_x}").json()["case"]
    check(xc["status"] == "PENDING_APPROVAL" and xc["decision"] == "EXCHANGE_ELIGIBLE",
          f"Exchange {case_x}: awaiting approval of the exchange (status {xc['status']}, decision {xc['decision']})")
    c.post(f"/cases/{case_x}/approve")
    data = c.get(f"/api/cases/{case_x}").json()
    x_refunds = [x for x in data["paypal_calls"] if x["operation"] == "refund_capture"]
    check(data["case"]["status"] == "EXCHANGE_ARRANGED" and not x_refunds and not data["case"]["refund_id"],
          f"Exchange {case_x}: EXCHANGE_ARRANGED with 0 refund calls ({len(x_refunds)})")
    check(c.post(f"/cases/{case_x}/refund").status_code == 409, "Exchange: refund endpoint refused (409)")
    chain_x = c.get(f"/cases/{case_x}/audit/verify").json()
    check(chain_x.get("ok") is True and (chain_x.get("chained_state") or {}).get("decision") == "EXCHANGE_ELIGIBLE",
          f"Exchange audit trail intact: {chain_x.get('entries')} entries")

    # Refund failure (PayPal 422) -> 'PayPal refused, no money moved' -> retry COMPLETED (same request id)
    case_r = run_case("/demo/run/R")
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

    if mixed:
        mixed_checks(c, check, allow_mock)

    print(f"\nManual step: look up debug id {dbg} in the PayPal Developer Dashboard (Sandbox) logs.")
    print("RESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    flags = ("--allow-autonomy", "--mixed", "--mixed-only", "--allow-mock")
    args = [a for a in sys.argv[1:] if a not in flags]
    if len(args) != 1:
        raise SystemExit(__doc__)
    sys.exit(main(args[0], allow_autonomy="--allow-autonomy" in sys.argv[1:], mixed="--mixed" in sys.argv[1:],
                  mixed_only="--mixed-only" in sys.argv[1:], allow_mock="--allow-mock" in sys.argv[1:]))
