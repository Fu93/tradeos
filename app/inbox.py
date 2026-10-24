"""The returns inbox: what a merchant opens on Monday morning.

Every return request in one list, whoever sent it: a customer typing in any language, or a buyer's AI agent through
the MCP gateway. For each one it says what it needs from the merchant right now, why the policy decided what it
decided, and what PayPal has actually done. The dashboard (/) stays the place to work one case; this is the queue.

Rows are built from the cases table and each case's audit chain. Nothing here decides anything or calls PayPal.
"""
from __future__ import annotations

from typing import Any

from .mixed import MIXED, S_ATTENTION, S_DONE, S_NEEDS, S_PENDING, S_PROGRESS, S_UNKNOWN
from .workflow import (AGENT, AGENT_ORDERED, AWAITING_BUYER, DECLINED, ERROR, EXCHANGE_ARRANGED, NEEDS_HUMAN,
                       NEEDS_SAFETY, NEW, PENDING_APPROVAL, REFUND_COMPLETED, REFUND_ERROR, REFUND_FAILED,
                       REFUND_PENDING, REFUND_UNKNOWN, REJECTED, SAFETY_REVIEWED, Workflow)

MAX_ROWS = 200  # newest first; the demo is shared and a reset archives everything anyway

NEEDS_YOU, WAITING, CLOSED = "needs_you", "waiting", "closed"
BUCKET_LABELS = {NEEDS_YOU: "Needs you", WAITING: "Waiting on someone else", CLOSED: "Closed"}

# status -> (bucket, what the merchant should know or do, in plain words)
NEXT_STEP: dict[str, tuple[str, str]] = {
    PENDING_APPROVAL: (NEEDS_YOU, "Policy says eligible. Approve to refund, or decline."),
    NEEDS_HUMAN: (NEEDS_YOU, "The supplier cannot exchange it. Decide whether to offer a refund."),
    NEEDS_SAFETY: (NEEDS_YOU, "Possible safety issue. Read it and record what you did; no money moves."),
    REFUND_FAILED: (NEEDS_YOU, "PayPal refused the refund. Read why, then retry or contact the buyer."),
    REFUND_ERROR: (NEEDS_YOU, "PayPal returned an error; no refund was made. Retry when ready."),
    REFUND_UNKNOWN: (NEEDS_YOU, "PayPal did not answer. Check with PayPal before doing anything else."),
    ERROR: (NEEDS_YOU, "Something failed before PayPal was asked. Open the case for the error."),
    AWAITING_BUYER: (WAITING, "Waiting for the buyer to approve the payment in PayPal."),
    REFUND_PENDING: (WAITING, "Refund sent; PayPal reports it pending. Shown as done only when PayPal says so."),
    REFUND_COMPLETED: (CLOSED, "Refunded. PayPal confirmed COMPLETED."),
    EXCHANGE_ARRANGED: (CLOSED, "Exchange arranged with the supplier. No refund."),
    REJECTED: (CLOSED, "Rejected by the return policy. The Refund API was never called."),
    DECLINED: (CLOSED, "You declined it. No refund."),
    SAFETY_REVIEWED: (CLOSED, "Safety review recorded. No money moved."),
    # A mixed order (some items returned, some exchanged) moves through its own statuses, batch by batch.
    S_PENDING: (NEEDS_YOU, "A partial refund batch is proposed. Review the items and approve or decline."),
    S_NEEDS: (NEEDS_YOU, "Part of the order needs a decision (e.g. an exchange the supplier cannot fill)."),
    S_ATTENTION: (NEEDS_YOU, "A refund batch failed. Open the order to see which items and why."),
    S_UNKNOWN: (NEEDS_YOU, "PayPal did not answer for a refund batch. Check with PayPal first."),
    S_PROGRESS: (WAITING, "A partial refund is pending at PayPal."),
    S_DONE: (CLOSED, "Every item is settled: refunded, exchanged or refused."),
}
NOT_A_REQUEST = (NEW, AGENT_ORDERED)  # a seeded case not run yet, or an agent's order with no request on it

REQUEST_LABELS = {"REFUND": "Refund", "EXCHANGE": "Exchange", "INFO": "Question", "UNKNOWN": "Unclear"}


def _request_kind(case: dict) -> str:
    if case["status"] in (NEEDS_SAFETY, SAFETY_REVIEWED):
        return "Safety report"
    if case.get("decision") == MIXED:
        return "Mixed: partial refund + exchange"
    action = (case.get("intent") or {}).get("requested_action") or "UNKNOWN"
    return REQUEST_LABELS.get(action, action.title())


def _why(case: dict) -> str:
    reasons = (case.get("policy") or {}).get("reasons") or []
    return str(reasons[0]) if reasons else ""


def inbox_rows(wf: Workflow, limit: int = MAX_ROWS, *, evidence: bool = True) -> list[dict[str, Any]]:
    """One row per return request, newest first. evidence=False skips everything per case that reads more than the
    cases table (agent provenance, the chain check, the PayPal call count): the dashboard's strip renders on every
    page view and only needs counts."""
    cases = [c for c in wf.db.list_cases() if c["status"] not in NOT_A_REQUEST]
    cases.sort(key=lambda c: c["created_at"], reverse=True)
    rows = []
    for case in cases[:limit]:
        bucket, step = NEXT_STEP.get(case["status"], (NEEDS_YOU, "Open the case."))
        from_agent = case["scenario"] == AGENT
        row: dict[str, Any] = {
            "id": case["id"], "received": case["created_at"], "label": case.get("label") or "",
            "channel": "AI agent (MCP)" if from_agent else "Customer message",
            "from_agent": from_agent, "requested_by": case["customer_name"], "verified": None,
            "buyer": case["customer_name"], "request": _request_kind(case),
            "amount": f"{case['amount']} {case['currency']}", "decision": case.get("decision") or "",
            "status": case["status"], "bucket": bucket, "bucket_label": BUCKET_LABELS[bucket], "next_step": step,
            "why": _why(case), "approved_by": case.get("approval_source") or "",
        }
        if from_agent and evidence:
            who = wf.agents.provenance(case["id"])
            row["requested_by"] = who["agent"] or "an AI agent"
            row["buyer"] = who["on_behalf_of"] or case["customer_name"]
            row["verified"] = who["identity_verified"]
        if evidence:
            row["refund_api_calls"] = len(wf.db.paypal_calls(case["id"], "refund_capture"))
            row["chain_ok"] = bool(wf.db.verify_chain(case["id"])["ok"])
        rows.append(row)
    return rows


def inbox_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts for the page header and the dashboard's strip. agent_approved counts agent requests that were approved
    by anything other than a person; the gateway's design makes it 0, and the page shows the live number."""
    agent_rows = [r for r in rows if r["from_agent"]]
    return {
        "total": len(rows),
        "needs_you": sum(r["bucket"] == NEEDS_YOU for r in rows),
        "needs_you_agents": sum(r["bucket"] == NEEDS_YOU and r["from_agent"] for r in agent_rows),
        "waiting": sum(r["bucket"] == WAITING for r in rows),
        "closed": sum(r["bucket"] == CLOSED for r in rows),
        "agents": len(agent_rows),
        "agent_approved": sum(bool(r["approved_by"]) and r["approved_by"] != "human" for r in agent_rows),
    }
