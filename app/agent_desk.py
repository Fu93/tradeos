"""The agent gateway's side of the workflow: what an AI agent acting for a buyer may do with an order.

An agent can place a (Sandbox demo) order, ask for a return on it, and read the outcome. It cannot approve, decline
or refund: there is no method for that here, and the MCP tools in app/agent_gateway.py only call these. Amount,
currency, capture and purchase date come from PayPal and the merchant's own record, never from the agent. A request
runs the same _after_capture() loop as a dashboard case, and Workflow._autonomy_verdict sends every agent case to a
person.

Reached as ``wf.agents`` (like ``wf.mixed`` and ``wf.disputes``): it holds the workflow and uses its case lock,
run registry and money-operation guard, so an agent request is serialised exactly like a dashboard run.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .db import CaseFinalized
from .workflow import (AGENT, AGENT_ORDERED, AWAITING_BUYER, DECLINED, ERROR, EXCHANGE_ARRANGED, NEEDS_HUMAN,
                       NEEDS_SAFETY, PAYMENT_UNKNOWN, PENDING_APPROVAL, REFUND_COMPLETED, REFUND_ERROR, REFUND_FAILED,
                       REFUND_PENDING, REFUND_UNKNOWN, REJECTED, SCENARIOS, CaseNotFound, RefundNotAllowed, clean_message)

if TYPE_CHECKING:  # pragma: no cover
    from .workflow import Workflow

AGENT_NO_REQUEST = "(no request yet: order placed by an AI agent for the buyer)"
AGENT_TEXT_MAX = 80  # agent / buyer names are labels, not free text


class AgentDesk:
    def __init__(self, wf: "Workflow") -> None:
        self.wf = wf

    def case(self, case_id: str, caller: dict | None = None, *, check_owner: bool = True,
             include_archived: bool = False) -> dict:
        """An agent may only see orders that were placed through the agent gateway. Any other id, including a real
        dashboard case, is reported as not found, so an agent cannot probe or act on other customers' cases.

        An order placed under a verified credential belongs to that credential: any other caller, including one
        with no credential (the open gateway, or an in-process agent such as the live LLM demo), gets "not found"
        too. Orders placed without a credential stay open to every caller, as the open demo gateway always was.
        check_owner=False is for the server's own bookkeeping (recording a run), never for a tool."""
        case = self.wf.db.get_case(case_id) if isinstance(case_id, str) else None
        if not case or case.get("scenario") != AGENT or (case.get("archived_at") and not include_archived):
            raise CaseNotFound(case_id)
        if check_owner:
            owner = self.owner(case_id)
            if owner is not None and (caller or {}).get("credential") != owner:
                raise CaseNotFound(case_id)
        return case

    def owner(self, case_id: str) -> str | None:
        """The verified credential that placed the order (None for an order placed without one), read from the
        order's own hash-chained placement entry."""
        for event in self.wf.db.timeline(case_id):
            if event["stage"] == "agent" and event["title"].startswith("Order placed"):
                return (event.get("detail") or {}).get("credential")
        return None

    def place_order(self, buyer: str, agent: str = "", days_ago: int | None = None,
                    caller: dict | None = None) -> str:
        """Sandbox demo: the agent buys the demo product with a Sandbox test card, so it has an order to return.

        The case starts AGENT_ORDERED with no request on it. days_ago > 0 seeds an older purchase date (labelled
        demo data, like Case B) so the return window can be shown rejecting a late request."""
        buyer = clean_message(buyer, AGENT_TEXT_MAX) or SCENARIOS[AGENT]["customer_name"]
        agent = clean_message(agent, AGENT_TEXT_MAX)
        with self.wf._money_op():
            case_id = self.wf.new_case(AGENT, message=AGENT_NO_REQUEST, days_ago=days_ago or None,
                                    customer_name=buyer, status=AGENT_ORDERED)
            self.wf.db.audit(case_id, "agent", "Order placed by an AI agent for the buyer (Sandbox demo)",
                          {"agent": agent or None, "buyer": buyer, "channel": "mcp", **caller_fields(caller),
                           "purchase_date_seeded": self.wf._case(case_id)["purchase_date_seeded"]})
            self.wf._order_and_capture(case_id)
        return case_id

    def submit_request(self, case_id: str, message: str, agent: str, on_behalf_of: str,
                       caller: dict | None = None) -> bool:
        """An agent asks for a return / exchange on an order it placed. Runs the same _after_capture() loop as a
        dashboard case (AI intent, Safety Gate, PayPal GET capture, deterministic policy), then stops at the
        approval step: autonomy treats every agent-originated case as HUMAN.

        Idempotent: only an AGENT_ORDERED case is evaluated. A second request on the same order changes nothing
        and returns False, so an agent cannot re-roll the decision by rephrasing."""
        limit = self.wf.settings.free_text_max_chars
        text = clean_message(message, len(message or "") + 1)
        if not text:
            raise ValueError("Message is empty.")
        if len(text) > limit:
            # Same rule as the dashboard (422 above the limit). Never truncate: a fault or injury mentioned after
            # the cut would be invisible to the Safety Gate, and the policy would judge a different request.
            raise ValueError(f"Message too long: {len(text)} characters (limit {limit}). Send the buyer's "
                             "request in fewer words.")
        agent = clean_message(agent, AGENT_TEXT_MAX)
        on_behalf_of = clean_message(on_behalf_of, AGENT_TEXT_MAX)
        if not agent:
            raise ValueError("agent_name is required: the audit trail records which agent asked.")
        self.case(case_id, caller)
        with self.wf._locks_guard:
            if self.wf._resetting:
                raise RefundNotAllowed("A demo reset is in progress — try again in a moment.")
            if case_id in self.wf._running:
                return False
            self.wf._running.add(case_id)
        try:
            case = self.wf._case(case_id)
            if case["status"] == AWAITING_BUYER:
                raise ValueError("This order has no PayPal capture yet: the buyer has to approve the payment at "
                                 "PayPal first (buyer_approval_url in get_case_status).")
            if case["status"] == ERROR and case.get("order_status") == PAYMENT_UNKNOWN:
                raise ValueError("PayPal has not confirmed this order's payment yet: the merchant checks it with "
                                 "PayPal. Do not place a new order; call get_case_status later.")
            if case["status"] == ERROR and not case.get("capture_id"):
                raise ValueError("This order failed at PayPal before any payment was captured, so there is "
                                 "nothing to return. Place a new order.")
            if case["status"] != AGENT_ORDERED:
                return False
            self.wf.db.update_case(case_id, customer_message=text)
            self.wf.db.audit(case_id, "agent", "Return requested by an AI agent for the buyer",
                          {"agent": agent, "on_behalf_of": on_behalf_of or None, "channel": "mcp",
                           **caller_fields(caller), "message": text, "agent_can_approve": False})
            self.wf._after_capture(case_id)
            return True
        except CaseFinalized as exc:
            self.wf.db.audit(case_id, "workflow", "Agent request stopped — the case was already finalized",
                          {"reason": str(exc)})
            return False
        finally:
            with self.wf._locks_guard:
                self.wf._running.discard(case_id)

    def provenance(self, case_id: str) -> dict:
        """Who asked, for whom, and what the server could verify, read from the case's hash-chained timeline (the
        request entry wins over the order entry). agent / on_behalf_of are what the agent declared; credential is
        what the gateway verified (None when the gateway is open or the call was in-process)."""
        info: dict[str, Any] = {"agent": None, "on_behalf_of": None, "requested": False, "credential": None,
                                "identity_verified": False, "transport": None}
        for event in self.wf.db.timeline(case_id):
            if event["stage"] != "agent":
                continue
            detail = event.get("detail") or {}
            is_request = event["title"].startswith("Return requested")
            if is_request or not info["requested"]:
                info.update(agent=detail.get("agent"), requested=is_request,
                            on_behalf_of=detail.get("on_behalf_of") if is_request else detail.get("buyer"),
                            credential=detail.get("credential"), transport=detail.get("transport"),
                            identity_verified=bool(detail.get("identity_verified")))
        return info

    def record_run(self, case_id: str, record: dict) -> None:
        """A live LLM agent's run (goal, model, every tool call it made, its final report) goes onto the order's hash
        chain, so what the model tried is part of the audit trail. Recording changes no state and moves no money.

        The server records this itself (not a tool), so ownership is not checked, and an order a demo reset archived
        while the model was still working is still recorded: archiving keeps the chain, and the run is evidence."""
        self.case(case_id, check_owner=False, include_archived=True)
        self.wf.db.audit(case_id, "agent", f"Live AI agent run ({record.get('model')}): "
                      f"{len(record.get('steps') or [])} tool calls, {record.get('stop_reason')}", record)

    def view(self, case_id: str, caller: dict | None = None) -> dict:
        """What the agent may read back: the outcome and the evidence, never the dashboard's controls."""
        case = self.case(case_id, caller)
        policy = case.get("policy") or {}
        chain_result = self.wf.db.verify_chain(case_id)
        refund_calls = self.wf.db.paypal_calls(case_id, "refund_capture")
        return {
            "order_id": case_id,
            "status": case["status"],
            "policy_decision": case.get("decision"),
            "policy_reasons": policy.get("reasons") or [],
            "amount": f"{case['amount']} {case['currency']}",
            "capture_id": case.get("capture_id"),
            "purchase_date_seeded": case.get("purchase_date_seeded"),
            "approval": {"decision": case.get("human_decision"), "by": case.get("approval_source")},
            "refund": {"id": case.get("refund_id"), "status": case.get("refund_status")},
            "refund_api_calls": len(refund_calls),
            "buyer_approval_url": case.get("approve_url") if case["status"] == AWAITING_BUYER else None,
            "audit_trail": {"intact": chain_result["ok"], "entries": chain_result["entries"],
                            "head": chain_result["head"]},
            "requested_by": self.provenance(case_id),
            "next_step": next_step(case),
            "evidence_url": f"{self.wf.settings.public_base_url.rstrip('/')}/cases/{case_id}/evidence",
        }


def caller_fields(caller: dict | None) -> dict:
    """What the audit chain records about the caller. Only a credential the gateway verified counts as identity; the
    agent's name argument stays a self-declared label."""
    caller = caller or {}
    credential = caller.get("credential")
    return {"transport": caller.get("transport") or "in-process", "credential": credential,
            "identity_verified": credential is not None}


def next_step(case: dict) -> str:
    """Plain words for the agent: what happens next and who does it. The agent never does the approving."""
    status = case["status"]
    if status == AGENT_ORDERED:
        return "No request yet. Call request_return with the buyer's own words."
    if status == PENDING_APPROVAL:
        return ("The merchant's policy allows it; a person at the merchant must approve it. "
                "Nothing has been refunded. Check back with get_case_status.")
    if status == REJECTED:
        return "The merchant's policy rejected the request. No refund was made. Tell the buyer the reasons."
    if status == NEEDS_SAFETY:
        return "Possible safety issue: a person at the merchant reviews it first. No refund was made."
    if status == NEEDS_HUMAN:
        return "A person at the merchant has to decide. No refund was made."
    if status == REFUND_COMPLETED:
        return "PayPal reports the refund COMPLETED."
    if status == EXCHANGE_ARRANGED:
        return "The merchant approved an exchange. No money moves."
    if status == DECLINED:
        return "A person at the merchant declined the request. No refund was made."
    if status == AWAITING_BUYER:
        return ("The buyer has to approve the payment at PayPal (buyer_approval_url). After that, call "
                "request_return.")
    if status == ERROR:
        if case.get("order_status") == PAYMENT_UNKNOWN:
            return ("PayPal did not confirm the payment: it may have been taken. A person at the merchant checks it "
                    "with PayPal. Do not place a new order, and do not tell the buyer nothing was charged.")
        if case.get("capture_id"):
            return ("PayPal could not be read while checking the request. A person at the merchant will re-check "
                    "it. No refund was made.")
        return "The order failed at PayPal. No payment was captured and nothing can be returned."
    if status == REFUND_PENDING:
        return "Approved. PayPal reports the refund PENDING: it is not completed yet. Do not tell the buyer it is."
    if status == REFUND_UNKNOWN:
        return ("Approved. The refund's outcome is being checked with PayPal: it is not confirmed. Do not tell "
                "the buyer it is refunded.")
    if status in (REFUND_FAILED, REFUND_ERROR):
        return "Approved, but PayPal did not complete the refund. A person at the merchant handles it."
    return f"Status {status}. A person at the merchant handles it from here. Nothing is confirmed as refunded."
