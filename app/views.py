"""View-model helpers for the dashboard (keeps templates dumb)."""

from __future__ import annotations

from .db import Database


def fmt_ts(ts: str | None) -> str:
    if not ts:
        return "—"
    return ts.replace("T", " ").replace("Z", "") + " UTC"


def _refund_api_calls(db: Database, case_id: str) -> int:
    return len(db.paypal_calls(case_id, "refund_capture"))


def evidence_a(db: Database, case: dict | None) -> list[dict] | None:
    if not case or case["status"] == "NEW":
        return None
    policy = case.get("policy") or {}
    refund_status = case.get("refund_status")
    rows = [
        ("PayPal Order ID", case.get("order_id") or "—", bool(case.get("order_id"))),
        ("Capture ID", case.get("capture_id") or "—", bool(case.get("capture_id"))),
        ("Refund ID", case.get("refund_id") or "—", bool(case.get("refund_id"))),
        ("Policy", (policy.get("decision") or "—").lower(), policy.get("decision") == "ELIGIBLE"),
        ("Supplier", "replacement approved (MOCK)" if case.get("supplier_reply") == "REPLACEMENT_APPROVED"
         else (case.get("supplier_reply") or "—"), case.get("supplier_reply") == "REPLACEMENT_APPROVED"),
        ("Human", (case.get("human_decision") or "awaiting approval").lower(), case.get("human_decision") == "APPROVED"),
        ("Refund", refund_status or "not yet executed", refund_status == "COMPLETED"),
    ]
    return [{"label": l, "value": v, "ok": ok} for l, v, ok in rows]


def evidence_b(db: Database, case: dict | None) -> list[dict] | None:
    if not case or case["status"] == "NEW":
        return None
    intent = case.get("intent") or {}
    policy = case.get("policy") or {}
    understood = intent.get("intent") not in (None, "UNKNOWN")
    window = next((c for c in policy.get("checks", []) if c["name"] == "return_window"), None)
    if window and not window["passed"]:
        policy_text = window["detail"]
    else:
        policy_text = "; ".join(policy.get("reasons", [])) or (policy.get("decision") or "—")
    calls = _refund_api_calls(db, case["id"])
    rows = [
        ("PayPal Order ID", case.get("order_id") or "—", bool(case.get("order_id"))),
        ("Customer request", f"understood — {intent.get('intent')} / {intent.get('reason')}" if understood
         else "not understood", understood),
        ("Policy", policy_text, window is not None and not window["passed"]),
        ("Decision", case.get("decision") or "—", case.get("decision") == "REJECTED"),
        ("Refund API", "NOT CALLED" if calls == 0 else f"CALLED {calls}×", calls == 0),
        ("Refund ID", case.get("refund_id") or "none", not case.get("refund_id")),
    ]
    return [{"label": l, "value": v, "ok": ok} for l, v, ok in rows]
