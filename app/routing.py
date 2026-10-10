"""Supplier routing — EXPERIMENT, MVP 1 ("reliable triage only"), rules 0.2.0 (round 2: three dimensions).

    message -> AI extracts issue_type + customer_goal (app/routing_extract.py, non-decisional)
            -> deterministic rules (this file) compute required_action:
               DIRECT_WORKFLOW | CREATE_SUPPLIER_TASK | CLARIFY_WITH_CUSTOMER | HUMAN_REVIEW

Gate 1  Intent rules             injection / safety -> human; mixed goals -> clarify; INFORMATION -> human (answer,
                                 not a complaint); REFUND -> existing refund policy flow (DIRECT_WORKFLOW, never a
                                 supplier task); no outcome -> clarify; else issue x goal -> one of four families
                                 (EXCHANGE / RESHIP / DEFECT / PART_REPLACEMENT). Text cues (deterministic) can only
                                 make this more conservative.
Gate 2  Case matches order?      order number, ownership, product line and the type-specific identifier
                                 (size/colour, part number, fault) are present in the TEXT and match the
                                 (MOCK) order. The AI never fills a gap: missing => ask; conflicting => human.
Gate 3  Supplier necessary?      existing data (order, MOCK inventory, MOCK logistics, policy, MOCK supplier
                                 responsibility table) is checked first. If it resolves the case => DIRECT_WORKFLOW.
                                 "No data found" is NOT "ask the supplier": the supplier is only chosen when the
                                 responsibility table names it as the next actor / source of truth.
Gate 4  Confidence + duplicates  confidence may only DEMOTE an automatic action to human review (never promote),
                                 then "no open task for this order/item/family".

Only if all four pass is an INTERNAL supplier task created (DRAFT_READY). Nothing is ever sent.

Independence from money: this module never reads or writes the refund columns of the `cases`
table, and the refund guard (Workflow._guard_refund) never reads anything written here. The
routing state lives in its own tables (routing_cases / supplier_tasks / routing_log).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Callable, Iterator

from .routing_data import CATALOG, INVENTORY, MOCK_LABEL, PARTS, order_with_dates
from .routing_extract import ACTION_GOALS, SUPPORTED_TYPES, RoutingExtraction, RoutingExtractor, _SAFETY

RULE_VERSION = "supplier-routing-rules/0.2.0 (MVP 1 experiment, round 2)"

# ----------------------------------------------------------------------------- statuses
CASE_RECEIVED = "CASE_RECEIVED"
CLASSIFYING = "CLASSIFYING"
DIRECT_WORKFLOW = "DIRECT_WORKFLOW"
NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
SUPPLIER_REQUIRED = "SUPPLIER_REQUIRED"
SUPPLIER_TASK_OPEN = "SUPPLIER_TASK_OPEN"
CASE_STATUSES = (CASE_RECEIVED, CLASSIFYING, DIRECT_WORKFLOW, NEEDS_CLARIFICATION, NEEDS_HUMAN_REVIEW,
                 SUPPLIER_REQUIRED, SUPPLIER_TASK_OPEN)
ROUTES = (DIRECT_WORKFLOW, NEEDS_CLARIFICATION, NEEDS_HUMAN_REVIEW, SUPPLIER_REQUIRED)
# The third dimension (computed, never extracted). Case statuses keep their round-1 names.
REQUIRED_ACTION = {DIRECT_WORKFLOW: "DIRECT_WORKFLOW", SUPPLIER_REQUIRED: "CREATE_SUPPLIER_TASK",
                   NEEDS_CLARIFICATION: "CLARIFY_WITH_CUSTOMER", NEEDS_HUMAN_REVIEW: "HUMAN_REVIEW"}
AUTOMATIC_ROUTES = (DIRECT_WORKFLOW, SUPPLIER_REQUIRED)  # what confidence may demote (never promote into)

CASE_TRANSITIONS: dict[str, set[str]] = {
    CASE_RECEIVED: {CLASSIFYING},
    CLASSIFYING: {DIRECT_WORKFLOW, NEEDS_CLARIFICATION, NEEDS_HUMAN_REVIEW, SUPPLIER_REQUIRED},
    SUPPLIER_REQUIRED: {SUPPLIER_TASK_OPEN},
    NEEDS_HUMAN_REVIEW: {SUPPLIER_REQUIRED},  # human confirms a gate-passing supplier route that was demoted
    DIRECT_WORKFLOW: set(), NEEDS_CLARIFICATION: set(), SUPPLIER_TASK_OPEN: set(),
}

# Supplier task status (separate from the case status AND from the refund status).
T_NOT_REQUIRED = "NOT_REQUIRED"
T_DRAFT_READY = "DRAFT_READY"
T_AWAITING_RESPONSE = "AWAITING_RESPONSE"
T_RESPONSE_RECEIVED = "RESPONSE_RECEIVED"
T_RESOLVED = "RESOLVED"
T_NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
TASK_STATUSES = (T_NOT_REQUIRED, T_DRAFT_READY, T_AWAITING_RESPONSE, T_RESPONSE_RECEIVED, T_RESOLVED,
                 T_NEEDS_HUMAN_REVIEW)
TASK_TRANSITIONS: dict[str, set[str]] = {
    T_NOT_REQUIRED: {T_DRAFT_READY},
    T_DRAFT_READY: {T_AWAITING_RESPONSE, T_NEEDS_HUMAN_REVIEW},   # AWAITING_RESPONSE needs a send (MVP 2)
    T_AWAITING_RESPONSE: {T_RESPONSE_RECEIVED, T_NEEDS_HUMAN_REVIEW},
    T_RESPONSE_RECEIVED: {T_RESOLVED, T_NEEDS_HUMAN_REVIEW},
    T_RESOLVED: set(), T_NEEDS_HUMAN_REVIEW: set(),
}
MVP1_REACHABLE_TASK_STATUSES = (T_NOT_REQUIRED, T_DRAFT_READY)  # nothing is sent in MVP 1
OPEN_TASK_STATUSES = (T_DRAFT_READY, T_AWAITING_RESPONSE, T_RESPONSE_RECEIVED, T_NEEDS_HUMAN_REVIEW)
TASK_STATUS_TEXT = {
    T_NOT_REQUIRED: "Not required",
    T_DRAFT_READY: "Draft ready — NOT sent, supplier NOT contacted",
    T_AWAITING_RESPONSE: "Sent, awaiting response",
    T_RESPONSE_RECEIVED: "Response received",
    T_RESOLVED: "Resolved",
    T_NEEDS_HUMAN_REVIEW: "Needs human review",
}


class InvalidTransition(Exception):
    pass


def check_case_transition(old: str, new: str) -> None:
    if new not in CASE_TRANSITIONS.get(old, set()):
        raise InvalidTransition(f"case {old} -> {new} not allowed")


def check_task_transition(old: str, new: str, mvp1: bool = True) -> None:
    if new not in TASK_TRANSITIONS.get(old, set()):
        raise InvalidTransition(f"task {old} -> {new} not allowed")
    if mvp1 and new not in MVP1_REACHABLE_TASK_STATUSES:
        raise InvalidTransition(f"task status {new} is not reachable in MVP 1 (nothing is ever sent)")


# ----------------------------------------------------------------------------- config
@dataclass(frozen=True)
class RoutingConfig:
    """Confidence is UNCALIBRATED. It is used one way only: an automatic action (DIRECT_WORKFLOW or a supplier
    task) whose confidence is below `demote_below` is demoted to HUMAN_REVIEW. Nothing is ever promoted: a case
    that fails a hard gate or a routing rule stays where it is at any confidence. Override via env."""

    demote_below: float = 0.90         # < : automatic action demoted to human review (initial assumption)
    keyword_confidence_cap: float = 0.85  # keyword fallback is always below the floor => never automatic
    return_window_days: int = 30
    identifier_penalty: float = 0.25   # per AI identifier not found in the customer's text
    keyword_disagreement_penalty: float = 0.10
    injection_cap: float = 0.50

    def __post_init__(self) -> None:
        if not (0 <= self.demote_below <= 1):
            raise ValueError("need 0 <= ROUTING_DEMOTE_BELOW <= 1")

    @classmethod
    def from_env(cls) -> "RoutingConfig":
        def f(name, default):
            raw = (os.environ.get(name) or "").strip()
            return float(raw) if raw else default
        return cls(demote_below=f("ROUTING_DEMOTE_BELOW", f("ROUTING_AUTO_THRESHOLD", 0.90)),
                   keyword_confidence_cap=f("ROUTING_KEYWORD_CONFIDENCE_CAP", 0.85),
                   return_window_days=int(f("RETURN_WINDOW_DAYS", 30)))


# ----------------------------------------------------------------------------- deterministic scanners
def norm(text: str) -> str:
    """NFKC: full-width digits/letters (common in JA/zh input) become ASCII."""
    return unicodedata.normalize("NFKC", text or "")


_ORDER_RX = re.compile(r"(?<![A-Za-z0-9])TO[-\s]?(\d{4,6})(?![0-9])", re.I)
_PART_RX = re.compile(r"(?<![A-Za-z0-9-])([A-Z]{2}(?:-[A-Z0-9]+){1,3})(?![A-Za-z0-9])", re.I)


def scan_order_refs(text: str) -> list[str]:
    seen: list[str] = []
    for m in _ORDER_RX.finditer(norm(text)):
        ref = f"TO-{m.group(1)}"
        if ref not in seen:
            seen.append(ref)
    return seen


def normalize_order_ref(value: str | None) -> str | None:
    if not value:
        return None
    refs = scan_order_refs(value)
    return refs[0] if len(refs) == 1 else None


def scan_part_numbers(text: str) -> list[str]:
    out: list[str] = []
    for m in _PART_RX.finditer(norm(text)):
        p = m.group(1).upper()
        if p.startswith("TO-") or p in out:
            continue
        out.append(p)
    return out


def scan_products(text: str) -> list[str]:
    """SKUs whose (multilingual) aliases appear in the text. Longest alias first; matched spans are
    blanked so e.g. 靴下 (socks) is not also read as 靴 (shoes)."""
    t = norm(text)
    aliases = sorted(((a, sku) for sku, p in CATALOG.items() for a in p["aliases"]), key=lambda x: -len(x[0]))
    found: list[str] = []
    for alias, sku in aliases:
        rx = (re.compile(rf"(?<![A-Za-z]){re.escape(alias)}", re.I) if alias.isascii()
              else re.compile(re.escape(alias), re.I))
        if rx.search(t):
            t = rx.sub(lambda m: " " * len(m.group(0)), t)
            if sku not in found:
                found.append(sku)
    return found


def _token_rx(token: str) -> re.Pattern:
    if token.isascii() and token.isalnum() and token.isupper() or token.isdigit():
        # sizes such as 43 / M / XL: must stand alone (CJK neighbours are fine: 43號, Lサイズ)
        return re.compile(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])")
    if token.isascii():
        return re.compile(rf"(?<![A-Za-z]){re.escape(token)}(?![A-Za-z])", re.I)
    return re.compile(re.escape(token), re.I)


def canonical_variant(sku: str, value: str | None) -> str | None:
    """Map a model-provided variant ('43', 'EU 43', 'Green', 'verde') to the catalog key, or None."""
    if not value:
        return None
    v = re.sub(r"(?i)^(eu|size|talla|größe|grösse|サイズ|尺寸|尺碼)\s*", "", norm(value).strip()).strip()
    v = re.sub(r"(號|号|码|碼|サイズ)$", "", v).strip()
    for key, aliases in CATALOG[sku]["variants"].items():
        for a in [key, *aliases]:
            if a.lower() == v.lower():
                return key
    return None


def variant_in_text(sku: str, key: str, text: str) -> bool:
    t = norm(text)
    for token in [key, *CATALOG[sku]["variants"].get(key, [])]:
        if token and _token_rx(token).search(t):
            return True
    return False


def scan_variants(sku: str, text: str) -> list[str]:
    return [k for k in CATALOG[sku]["variants"] if variant_in_text(sku, k, text)]


def part_in_text(part: str, text: str) -> bool:
    return part.upper() in scan_part_numbers(text)


# ----------------------------------------------------------------------------- decision objects
@dataclass
class Gate:
    gate: int
    name: str
    passed: bool
    reason: str
    outcome: str | None = None  # route when the gate stops the case


@dataclass
class Decision:
    gates: list[Gate] = field(default_factory=list)
    proposed_route: str | None = None
    final_route: str | None = None
    complaint_type: str | None = None   # internal family (EXCHANGE/RESHIP/DEFECT/PART_REPLACEMENT), rule-derived
    issue_type: str | None = None       # dimension 1 (AI-extracted, text-checked)
    customer_goal: str | None = None    # dimension 2 (AI-extracted, text-checked)
    mixed: bool = False
    decided_by: str = ""                # which gate / rule produced the final route
    confidence: dict = field(default_factory=dict)
    data_used: list[dict] = field(default_factory=list)
    identifiers: dict = field(default_factory=dict)
    trigger_reason: str = ""
    dedup_key: str | None = None
    rule_version: str = RULE_VERSION

    def stop(self, gate: int, name: str, route: str, reason: str) -> "Decision":
        self.gates.append(Gate(gate, name, False, reason, route))
        self.proposed_route = route
        self.decided_by = f"gate {gate} ({name}): {reason}"
        return self

    def ok(self, gate: int, name: str, reason: str) -> None:
        self.gates.append(Gate(gate, name, True, reason))

    def use(self, source: str, key: str, value, mock: bool = True) -> None:
        self.data_used.append({"source": source, "key": key, "value": value, "mock": mock})

    @property
    def all_gates_passed(self) -> bool:
        return bool(self.gates) and all(g.passed for g in self.gates)

    @property
    def required_action(self) -> str | None:
        return REQUIRED_ACTION.get(self.final_route)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["all_gates_passed"] = self.all_gates_passed
        d["required_action"] = self.required_action
        return d


@dataclass
class CaseContext:
    """Trusted context from the system (never from the message): the customer account and,
    optionally, the order the case is attached to. `order_override` is used for TradeOS demo cases."""

    customer: str | None = None
    linked_order_id: str | None = None
    order_override: dict | None = None


# ----------------------------------------------------------------------------- confidence
def compute_confidence(ex: RoutingExtraction, discarded: list[str], cfg: RoutingConfig) -> dict:
    """Honest description: base = the model's self-reported probability (validated 0..1; 0.5 if missing).
    Keyword mode has no model, so base is a fixed rule score (0.80 one clear goal, else 0.60), capped below the
    demotion floor. Penalties are rule-based signals. Nothing here is calibrated, and the result is used ONLY to
    demote an automatic action to human review (never to promote anything)."""
    llm_mode = ex.extractor.startswith("llm:")
    f = ex.fields
    signals: list[dict] = []
    if llm_mode:
        base = ex.llm_confidence if ex.llm_confidence is not None else 0.5
        signals.append({"signal": "llm_self_report" if ex.llm_confidence is not None else "llm_confidence_missing",
                        "value": base})
    else:
        clear = len(ex.cues.goals) == 1 and f.issue_type != "UNCLEAR"
        base = 0.80 if clear else 0.60
        signals.append({"signal": "keyword_rule_score", "value": base})
    score = base
    for name in discarded:
        score -= cfg.identifier_penalty
        signals.append({"signal": f"ai_identifier_not_in_text:{name}", "value": -cfg.identifier_penalty})
    if llm_mode:
        if ex.cues.issues and f.issue_type in ("SIZE_MISMATCH", "DEFECT", "MISSING_ITEM", "PART_NEED") \
                and f.issue_type not in ex.cues.issues:
            score -= cfg.keyword_disagreement_penalty
            signals.append({"signal": "keyword_scan_disagrees_issue", "value": -cfg.keyword_disagreement_penalty,
                            "keyword_issues": ex.cues.issues})
        if ex.cues.goals and f.customer_goal in (*ACTION_GOALS, "REFUND") and f.customer_goal not in ex.cues.goals:
            score -= cfg.keyword_disagreement_penalty
            signals.append({"signal": "keyword_scan_disagrees_goal", "value": -cfg.keyword_disagreement_penalty,
                            "keyword_goals": ex.cues.goals})
    cap = 1.0
    if not llm_mode:
        cap = min(cap, cfg.keyword_confidence_cap)
        signals.append({"signal": "keyword_mode_cap", "value": cfg.keyword_confidence_cap})
    if ex.injection_like:
        cap = min(cap, cfg.injection_cap)
        signals.append({"signal": "instruction_like_text_cap", "value": cfg.injection_cap})
    combined = round(max(0.0, min(score, cap)), 3)
    band = "NOT_DEMOTED" if combined >= cfg.demote_below else "DEMOTE_IF_AUTOMATIC"
    return {"llm": ex.llm_confidence, "base": base, "signals": signals, "combined": combined, "band": band,
            "thresholds": {"demote_below": cfg.demote_below,
                           "note": "uncalibrated; demote-only (an automatic action below the floor goes to a "
                                   "human); never promotes"}}


# ----------------------------------------------------------------------------- rule 1: issue x goal -> family
def _family(issue: str, goal: str) -> str | None:
    """Deterministic issue x goal table (rules 0.2.0). None => the combination is not actionable as stated."""
    if goal == "EXCHANGE":
        return {"SIZE_MISMATCH": "EXCHANGE", "NO_ISSUE_INQUIRY": "EXCHANGE", "UNCLEAR": "EXCHANGE",
                "DEFECT": "DEFECT"}.get(issue)
    if goal == "RESHIP":
        return {"MISSING_ITEM": "RESHIP", "UNCLEAR": "RESHIP", "DEFECT": "DEFECT"}.get(issue)
    if goal == "REPAIR":
        return {"DEFECT": "DEFECT", "UNCLEAR": "DEFECT", "PART_NEED": "PART_REPLACEMENT"}.get(issue)
    if goal == "BUY_PART":
        return {"PART_NEED": "PART_REPLACEMENT", "DEFECT": "PART_REPLACEMENT", "UNCLEAR": "PART_REPLACEMENT",
                "NO_ISSUE_INQUIRY": "PART_REPLACEMENT"}.get(issue)
    return None


def effective_dimensions(ex: RoutingExtraction) -> tuple[str, str, list[str]]:
    """Text cross-checks on the AI's two dimensions. They can only make the outcome MORE conservative
    (towards 'not a complaint' / 'ask' / 'human'); they never create an action the AI did not extract."""
    f, cues = ex.fields, ex.cues
    issue, goal, notes = f.issue_type, f.customer_goal, []
    if issue == "DEFECT" and (cues.problem_negated or (cues.inquiry and "DEFECT" not in cues.issues)):
        notes.append("AI said DEFECT, but the text " + ("explicitly negates a problem" if cues.problem_negated
                     else "is a question without any defect wording") + ": treated as NO_ISSUE_INQUIRY.")
        issue = "NO_ISSUE_INQUIRY"
        if goal in ACTION_GOALS:
            notes.append(f"AI goal {goal} on a non-problem question: treated as INFORMATION.")
            goal = "INFORMATION"
    return issue, goal, notes


# ----------------------------------------------------------------------------- the gates
def decide(ex: RoutingExtraction, message: str, ctx: CaseContext, cfg: RoutingConfig, today: date,
           open_task_for: Callable[[str], dict | None] = lambda key: None) -> Decision:
    d = Decision()
    f = ex.fields
    issue, goal, notes = effective_dimensions(ex)
    d.issue_type, d.customer_goal, d.mixed = issue, goal, bool(f.mixed_goals)
    d.use("ai_extraction", "issue_type / customer_goal / mixed",
          f"{f.issue_type}/{f.customer_goal}/{'mixed' if f.mixed_goals else 'single'}", mock=False)
    for n in notes:
        d.use("text cross-check", "dimension override (conservative)", n, mock=False)

    # Verify AI identifiers against the text (the AI can never supply a value the customer did not write).
    discarded: list[str] = []
    llm_mode = ex.extractor.startswith("llm:")
    ai_order = normalize_order_ref(f.order_ref) if f.order_ref else None
    text_orders = scan_order_refs(message)
    if f.order_ref and (ai_order is None or ai_order not in text_orders):
        discarded.append("order_ref")
    ai_part = f.part_model.upper().strip() if f.part_model else None
    if ai_part and not part_in_text(ai_part, message):
        discarded.append("part_model")
        ai_part = None

    def finish(route_stop: Decision) -> Decision:
        """Non-automatic outcomes (clarify / human) are final at any confidence; an automatic one is demoted."""
        return _apply_confidence(route_stop, ex, discarded, cfg)

    # ---------------- Gate 1: intent rules (issue x goal; first match wins)
    G1 = "intent_rules"
    if ex.injection_like:
        return finish(d.stop(1, G1, NEEDS_HUMAN_REVIEW,
                             "R1 instruction-like text in the message; it is data, a human reads it."))
    if f.safety_issue or ex.cues.safety or _SAFETY.search(message or ""):
        d.use("safety rule", "safety words / AI flag", True, mock=False)
        return finish(d.stop(1, G1, NEEDS_HUMAN_REVIEW,
                             "R2 possible safety issue (fire/smoke/sparks/shock/gas/injury): always a human first."))
    if f.mixed_goals:
        return finish(d.stop(1, G1, NEEDS_CLARIFICATION,
                             "R3 mixed / undecided goals or several items: ask the customer to separate them."))
    if goal == "INFORMATION":
        return finish(d.stop(1, G1, NEEDS_HUMAN_REVIEW,
                             f"R4 customer_goal INFORMATION (issue {issue}): a question, not a request to act; "
                             "support answers it. No supplier task."))
    if goal == "REFUND":
        return finish(d.stop(1, G1, DIRECT_WORKFLOW,
                             "R5 customer_goal REFUND: the existing refund policy flow (policy checks, human "
                             "approval, PayPal) owns it. Never a supplier task."))
    if ex.cues.refund_only and goal in ACTION_GOALS:
        return finish(d.stop(1, G1, NEEDS_HUMAN_REVIEW,
                             f"R6 the text only asks for money back but the AI goal is {goal}: conflicting reading, "
                             "a human decides (never a supplier task on a refund wish)."))
    if goal == "UNCLEAR":
        if issue == "NO_ISSUE_INQUIRY":
            return finish(d.stop(1, G1, NEEDS_HUMAN_REVIEW,
                                 "R7 no problem and no requested outcome: standard support reads it."))
        return finish(d.stop(1, G1, NEEDS_CLARIFICATION,
                             f"R7 issue {issue} but no requested outcome: ask what the customer wants."))
    if ex.cues.inquiry or ex.cues.problem_negated:
        return finish(d.stop(1, G1, NEEDS_HUMAN_REVIEW,
                             f"R8 the text is question-form{' / negates a problem' if ex.cues.problem_negated else ''}"
                             f" but the AI goal is {goal}: a human answers (no automatic action on a question)."))
    ctype = _family(issue, goal)
    if ctype is None:
        return finish(d.stop(1, G1, NEEDS_CLARIFICATION,
                             f"R9 issue {issue} with goal {goal} is not an actionable combination: ask."))
    d.complaint_type = ctype
    d.ok(1, G1, f"R10 issue {issue} + goal {goal} -> {ctype} family (a label alone does not trigger anything).")

    # ---------------- Gate 2: case matches order / product?
    order = None
    if ctx.order_override is not None:
        order = ctx.order_override
        others = [r for r in text_orders if r != order["order_id"]]
        d.use(order.get("source", "case record"), "order", order["order_id"], mock=order.get("is_mock", False))
        if others:
            return finish(d.stop(2, "matches_order", NEEDS_HUMAN_REVIEW,
                                 f"Message cites {', '.join(others)} but the case is linked to {order['order_id']}."))
    else:
        if len(text_orders) > 1:
            return finish(d.stop(2, "matches_order", NEEDS_HUMAN_REVIEW,
                                 f"Several order numbers in the message ({', '.join(text_orders)})."))
        ref = text_orders[0] if text_orders else None
        if ref and ctx.linked_order_id and ref != ctx.linked_order_id:
            return finish(d.stop(2, "matches_order", NEEDS_HUMAN_REVIEW,
                                 f"Message cites {ref} but the case is linked to {ctx.linked_order_id} "
                                 "(similar numbers are never auto-corrected)."))
        oid = ref or ctx.linked_order_id
        if not oid:
            return finish(d.stop(2, "matches_order", NEEDS_CLARIFICATION,
                                 "No order number in the message and no linked order: ask for it."))
        order = order_with_dates(oid, today)
        d.use("MOCK orders", "order lookup", oid if order else f"{oid} (not found)")
        if order is None:
            return finish(d.stop(2, "matches_order", NEEDS_CLARIFICATION,
                                 f"Order {oid} not found (no fuzzy matching): ask the customer to confirm it."))
        if not ctx.customer:
            return finish(d.stop(2, "matches_order", NEEDS_HUMAN_REVIEW,
                                 "No customer account on the case: order ownership cannot be verified."))
        if order["customer"] != ctx.customer:
            return finish(d.stop(2, "matches_order", NEEDS_HUMAN_REVIEW,
                                 f"Order {oid} belongs to a different customer (possible mistyped / similar "
                                 "order number)."))

    lines = order["lines"]
    mentioned = scan_products(message)
    order_skus = [l["sku"] for l in lines]
    # AI part number (verified in text) or, if the AI gave none, the deterministic text scan.
    text_parts = scan_part_numbers(message) if ctype == "PART_REPLACEMENT" else []
    part_candidates = ([ai_part] if ai_part else text_parts) if ctype == "PART_REPLACEMENT" else []
    if len(set(text_parts)) > 1:  # run 1 bug: the AI's single pick hid a second part number in the text
        part_candidates = text_parts
    if ctype == "PART_REPLACEMENT" and len(set(part_candidates)) > 1:
        return finish(d.stop(2, "matches_order", NEEDS_CLARIFICATION,
                             f"Several part numbers ({', '.join(part_candidates)}): ask which one."))
    part = part_candidates[0] if part_candidates else None
    if mentioned and not set(mentioned) & set(order_skus):
        names = ", ".join(CATALOG[s]["name"] for s in mentioned)
        return finish(d.stop(2, "matches_order", NEEDS_HUMAN_REVIEW,
                             f"Message is about {names}, which is not in order {order['order_id']}."))
    cand = [l for l in lines if l["sku"] in mentioned] if mentioned else list(lines)
    if part and len(cand) > 1:
        cand = [l for l in cand if part.startswith(CATALOG[l["sku"]]["part_prefix"])] or cand
    if len(cand) > 1 and f.item_mention:
        # Several items named; the AI says which one the complaint is about. Accepted only if that
        # item is itself one of the items written in the message AND in the order (no new facts).
        pick = [l for l in cand if l["sku"] in scan_products(f.item_mention)]
        if len(pick) == 1:
            cand = pick
            d.use("ai_extraction", "item_mention (among items named in the text)", f.item_mention, mock=False)
    if len(cand) != 1:
        return finish(d.stop(2, "matches_order", NEEDS_CLARIFICATION,
                             f"Order {order['order_id']} has {len(lines)} items and the message does not say "
                             "which one: ask."))
    line = cand[0]
    sku = line["sku"]
    product = CATALOG[sku]
    d.identifiers.update({"order_id": order["order_id"], "sku": sku, "product_name": product["name"],
                          "current_variant": line["variant"], "qty": line["qty"],
                          "order_date": order["order_date"]})
    d.use("MOCK catalog", sku, f"{product['name']} · fulfilment {product['fulfilment']} · supplier "
          f"{product['supplier']}")

    if ctype == "EXCHANGE":
        if not product["variants"] or list(product["variants"]) == ["standard"]:
            return finish(d.stop(2, "matches_order", NEEDS_HUMAN_REVIEW,
                                 f"{product['name']} has no size/colour variants to exchange."))
        req = None
        if llm_mode and f.requested_variant:
            req = canonical_variant(sku, f.requested_variant)
            if req is None:
                return finish(d.stop(2, "matches_order", NEEDS_CLARIFICATION,
                                     f"Requested {product['variant_kind']} '{f.requested_variant}' does not exist "
                                     f"for {product['name']}: ask."))
            if not variant_in_text(sku, req, message):
                discarded.append("requested_variant")  # the AI named a variant the customer never wrote
                req = None
        else:
            # Deterministic text scan (no AI): exactly one valid variant other than the ordered one.
            found = [v for v in scan_variants(sku, message) if v != line["variant"]]
            req = found[0] if len(found) == 1 else None
        cur = canonical_variant(sku, f.current_variant) if llm_mode else None
        if cur and not variant_in_text(sku, cur, message):
            cur = None
        if req is None:
            return finish(d.stop(2, "matches_order", NEEDS_CLARIFICATION,
                                 f"Requested {product['variant_kind']} not stated in the message: ask "
                                 "(never guessed)."))
        if cur and cur != line["variant"]:
            return finish(d.stop(2, "matches_order", NEEDS_HUMAN_REVIEW,
                                 f"Customer says they have {cur}, order shows {line['variant']}."))
        if req == line["variant"]:
            return finish(d.stop(2, "matches_order", NEEDS_CLARIFICATION,
                                 f"Requested {product['variant_kind']} equals the ordered one ({req}): ask."))
        d.identifiers["requested_variant"] = req
    elif ctype == "DEFECT":
        desc = f.defect_description
        if not desc:
            return finish(d.stop(2, "matches_order", NEEDS_CLARIFICATION, "No description of the fault: ask."))
        d.identifiers["defect_description"] = desc
    elif ctype == "PART_REPLACEMENT":
        if not part:
            return finish(d.stop(2, "matches_order", NEEDS_CLARIFICATION,
                                 "No part number in the message: ask for it (part models are never guessed)."))
        if not part.startswith(product["part_prefix"]) or (part in PARTS and PARTS[part]["sku"] != sku):
            return finish(d.stop(2, "matches_order", NEEDS_HUMAN_REVIEW,
                                 f"Part {part} does not belong to {product['name']} (expected prefix "
                                 f"{product['part_prefix']})."))
        d.identifiers["part_model"] = part
        d.identifiers["part_name"] = PARTS[part]["name"] if part in PARTS else "unknown part number"
    d.ok(2, "matches_order", f"Order {order['order_id']} ({'linked' if ctx.order_override or ctx.linked_order_id else 'cited'}), "
         f"{product['name']}" + (f", identifiers {', '.join(k for k in ('requested_variant', 'part_model', 'defect_description') if k in d.identifiers)}"
                                 if any(k in d.identifiers for k in ('requested_variant', 'part_model', 'defect_description')) else "")
         + " — all taken from the text / records.")

    # ---------------- Gate 3: supplier necessary?
    route, reason = _necessity(d, ctype, f, message, order, line, product, cfg, today)
    if route != SUPPLIER_REQUIRED:
        d.stop(3, "supplier_necessary", route, reason)
        return finish(d)
    d.ok(3, "supplier_necessary", reason)
    d.trigger_reason = reason

    # ---------------- Gate 4: confidence (demote-only) + no duplicate open task
    d.dedup_key = f"{order['order_id']}|{sku}|{ctype}"
    d.confidence = compute_confidence(ex, discarded, cfg)
    existing = open_task_for(d.dedup_key)
    if d.confidence["combined"] < cfg.demote_below:
        d.stop(4, "confidence_and_duplicates", NEEDS_HUMAN_REVIEW,
               f"Supplier task proposed, but confidence {d.confidence['combined']} < {cfg.demote_below}: demoted; "
               "a human confirms or rejects the proposal.")
        d.proposed_route = SUPPLIER_REQUIRED
        d.final_route = NEEDS_HUMAN_REVIEW
        return d
    if existing:
        d.gates.append(Gate(4, "confidence_and_duplicates", True,
                            f"Confidence {d.confidence['combined']} not below {cfg.demote_below}; an open task "
                            f"{existing['id']} already exists for {d.dedup_key}: linked, no new task."))
        d.identifiers["duplicate_of_task"] = existing["id"]
    else:
        d.ok(4, "confidence_and_duplicates", f"Confidence {d.confidence['combined']} not below {cfg.demote_below} "
             f"(no demotion); no open task for {d.dedup_key}.")
    d.proposed_route = d.final_route = SUPPLIER_REQUIRED
    d.decided_by = f"gates 1-4 passed: {reason}"
    return d


def _apply_confidence(d: Decision, ex: RoutingExtraction, discarded: list[str], cfg: RoutingConfig) -> Decision:
    """Demote-only. A non-automatic outcome (clarify / human) is never changed. An automatic outcome below the
    floor becomes HUMAN_REVIEW. There is no path from here to a more automatic route."""
    d.confidence = compute_confidence(ex, discarded, cfg)
    d.final_route = d.proposed_route
    if d.proposed_route in AUTOMATIC_ROUTES and d.confidence["combined"] < cfg.demote_below:
        d.final_route = NEEDS_HUMAN_REVIEW
        d.gates.append(Gate(4, "confidence_demotion", False,
                            f"{REQUIRED_ACTION[d.proposed_route]} proposed, but confidence "
                            f"{d.confidence['combined']} < {cfg.demote_below}: demoted to a human.", NEEDS_HUMAN_REVIEW))
        d.decided_by += f" -> demoted (confidence {d.confidence['combined']} < {cfg.demote_below})"
    return d


def _necessity(d: Decision, ctype: str, f, message: str, order: dict, line: dict, product: dict,
               cfg: RoutingConfig, today: date) -> tuple[str, str]:
    sku = line["sku"]
    days = (today - date.fromisoformat(order["order_date"])).days
    d.use("order", "days since purchase", days, mock=order.get("is_mock", True))
    if f.safety_issue or _SAFETY.search(message or ""):
        d.use("safety rule", "safety words / AI flag", True, mock=False)
        return NEEDS_HUMAN_REVIEW, "Possible safety issue (fire/smoke/shock/gas/injury): always a human first."
    cap = {k: product[k] for k in ("fulfilment", "confirms_stock", "restocks_on_request", "reships",
                                   "warranty_by", "warranty_days", "supplies_parts", "answers_compatibility")}
    d.use("MOCK supplier responsibility table", sku, cap)

    if ctype == "EXCHANGE":
        req = d.identifiers["requested_variant"]
        d.use("policy", "returnable / window", f"returnable={product['returnable']}, window={cfg.return_window_days}d",
              mock=False)
        if not product["returnable"]:
            return DIRECT_WORKFLOW, "Final-sale item: the existing policy decides (no exchange); supplier not needed."
        if days > cfg.return_window_days:
            return DIRECT_WORKFLOW, (f"Purchased {days} days ago, outside the {cfg.return_window_days}-day window: "
                                     "the existing policy decides; supplier not needed.")
        if product["fulfilment"] == "MERCHANT_WAREHOUSE":
            stock = INVENTORY.get((sku, req))
            d.use("MOCK inventory", f"{sku}/{req}", "no record" if stock is None else stock)
            if stock is None:
                return NEEDS_HUMAN_REVIEW, (f"No inventory record for {req}. No data found is not the same as "
                                            "'ask the supplier': a human checks.")
            if stock > 0:
                return DIRECT_WORKFLOW, f"{stock} × {req} in our warehouse: exchange from own stock."
            if product["restocks_on_request"]:
                return SUPPLIER_REQUIRED, (f"{req} out of stock in our warehouse; the responsibility table names "
                                           f"{product['supplier']} for restock: ask restock ETA / feasibility.")
            return NEEDS_HUMAN_REVIEW, f"{req} out of stock and the supplier has no restock responsibility."
        if product["confirms_stock"]:
            return SUPPLIER_REQUIRED, (f"Drop-shipped item: {product['supplier']} is the source of truth for {req} "
                                       "stock and exchange feasibility.")
        return NEEDS_HUMAN_REVIEW, "Drop-shipped item but no supplier stock responsibility on file."

    if ctype == "RESHIP":
        lg = line.get("logistics")
        d.use("MOCK logistics", f"{order['order_id']}/{sku}", lg or "no record")
        if not lg:
            return NEEDS_HUMAN_REVIEW, "No logistics record for this item: a human checks (not a supplier trigger)."
        status = lg["status"]
        if status == "IN_TRANSIT":
            return DIRECT_WORKFLOW, (f"Carrier shows IN_TRANSIT (ETA {lg.get('eta_days', '?')} days, tracking "
                                     f"{lg.get('tracking', 'n/a')}): share tracking, nothing to reship yet.")
        if status == "DELIVERED":
            return NEEDS_HUMAN_REVIEW, ("Carrier shows the item delivered in full; the claim conflicts with our data. "
                                        "A human investigates before anyone reships.")
        missing = line["qty"] - lg.get("delivered_qty", 0) if status == "DELIVERED_PARTIAL" else line["qty"]
        d.identifiers["missing_qty"] = missing
        d.identifiers["logistics_status"] = status
        if product["fulfilment"] == "SUPPLIER_DROPSHIP":
            if product["reships"]:
                return SUPPLIER_REQUIRED, (f"{status}: {missing} item(s) not received; {product['supplier']} "
                                           "fulfilled this shipment: confirm reship eligibility and ship time.")
            return NEEDS_HUMAN_REVIEW, f"{status} on a drop-shipped item but the supplier has no reship responsibility."
        stock = INVENTORY.get((sku, line["variant"]))
        d.use("MOCK inventory", f"{sku}/{line['variant']}", "no record" if stock is None else stock)
        if stock and stock >= missing:
            return DIRECT_WORKFLOW, f"{status}: we shipped it and have {stock} in stock: reship from our warehouse."
        return NEEDS_HUMAN_REVIEW, f"{status}: we shipped it but have no stock on record to reship."

    if ctype == "DEFECT":
        d.use("policy", "return window", f"{cfg.return_window_days}d", mock=False)
        if days <= cfg.return_window_days and product["returnable"]:
            return DIRECT_WORKFLOW, (f"Purchased {days} days ago: covered by the existing return/refund policy "
                                     f"({cfg.return_window_days} days). Supplier not needed.")
        if product["warranty_by"] == "SUPPLIER" and days <= product["warranty_days"]:
            d.identifiers["warranty_basis"] = f"{days} of {product['warranty_days']} warranty days"
            return SUPPLIER_REQUIRED, (f"Outside our {cfg.return_window_days}-day window, inside the "
                                       f"{product['warranty_days']}-day supplier warranty: {product['supplier']} "
                                       "decides repair / replacement.")
        if product["warranty_by"] == "MERCHANT" and days <= product["warranty_days"]:
            return DIRECT_WORKFLOW, f"Inside our own {product['warranty_days']}-day warranty: merchant process."
        return NEEDS_HUMAN_REVIEW, (f"Purchased {days} days ago; no applicable window or warranty "
                                    f"(warranty: {product['warranty_by']} {product['warranty_days']}d).")

    # PART_REPLACEMENT
    part = d.identifiers["part_model"]
    info = PARTS.get(part)
    d.use("MOCK parts table", part, info or "unknown part number")
    if info:
        if info["stock"] > 0:
            return DIRECT_WORKFLOW, f"{part} ({info['name']}) compatible and {info['stock']} in stock: ship it."
        if product["supplies_parts"]:
            return SUPPLIER_REQUIRED, (f"{part} ({info['name']}) compatible but 0 in stock; {product['supplier']} "
                                       "supplies parts: confirm availability and lead time.")
        return NEEDS_HUMAN_REVIEW, f"{part} out of stock and the supplier does not supply parts."
    if product["answers_compatibility"]:
        return SUPPLIER_REQUIRED, (f"{part} is not in our parts table; {product['supplier']} is responsible for "
                                   "compatibility: confirm model, compatibility and availability.")
    return NEEDS_HUMAN_REVIEW, f"{part} unknown and the supplier does not answer compatibility questions."


# ----------------------------------------------------------------------------- supplier task draft
REQUIRED_TASK_FIELDS = {
    "EXCHANGE": ("order_id", "sku", "product_name", "current_variant", "requested_variant"),
    "RESHIP": ("order_id", "sku", "product_name", "missing_qty", "logistics_status"),
    "DEFECT": ("order_id", "sku", "product_name", "order_date", "defect_description", "warranty_basis"),
    "PART_REPLACEMENT": ("order_id", "sku", "product_name", "part_model"),
}
QUESTIONS = {
    "EXCHANGE": "Please confirm stock and feasibility for an exchange to {requested_variant}.",
    "RESHIP": "Please confirm reship eligibility and ship time for {missing_qty} missing item(s).",
    "DEFECT": "Please advise on repair or replacement under your warranty.",
    "PART_REPLACEMENT": "Please confirm part model, compatibility and availability / lead time for {part_model}.",
}


def build_task_fields(decision: Decision, supplier: str) -> dict:
    ids = decision.identifiers
    ctype = decision.complaint_type
    fields = {k: ids.get(k) for k in REQUIRED_TASK_FIELDS[ctype]}
    fields["supplier"] = supplier
    fields["question"] = QUESTIONS[ctype].format(**{k: ids.get(k, "?") for k in
                                                   ("requested_variant", "missing_qty", "part_model")})
    if ctype == "PART_REPLACEMENT":
        fields["part_name"] = ids.get("part_name")
    return fields


def draft_supplier_task(case_id: str, decision: Decision, supplier: str) -> tuple[str, dict]:
    fields = build_task_fields(decision, supplier)
    lines = [
        "INTERNAL DRAFT — NOT SENT. The supplier has NOT been contacted. (MOCK supplier, experiment)",
        f"To: {supplier}",
        f"Subject: [{decision.complaint_type}] Order {fields['order_id']} — {fields['product_name']}",
        "",
        fields["question"],
        "",
    ]
    for k in REQUIRED_TASK_FIELDS[decision.complaint_type]:
        label = k.replace("_", " ")
        value = fields[k]
        if k == "defect_description":
            value = f"{value} (customer-reported, AI-extracted, unverified)"
        lines.append(f"{label}: {value}")
    if fields.get("part_name"):
        lines.append(f"part name: {fields['part_name']}")
    lines += ["", f"Why the supplier: {decision.trigger_reason}",
              f"Reference: TradeOS routing case {case_id} · rules {decision.rule_version}"]
    return "\n".join(lines), fields


def task_complete(task: dict) -> bool:
    """Draft contains every field the supplier needs for this complaint type (non-empty and in the text)."""
    fields, draft = task["fields"], task["draft"]
    for k in REQUIRED_TASK_FIELDS[task["complaint_type"]]:
        v = fields.get(k)
        if v in (None, "") or str(v) not in draft:
            return False
    return True


# ----------------------------------------------------------------------------- storage
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS routing_cases (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source TEXT NOT NULL,
    tradeos_case_id TEXT,           -- optional link to a TradeOS refund case (read-only from here)
    customer TEXT,
    linked_order_id TEXT,
    message TEXT NOT NULL,
    status TEXT NOT NULL,           -- case main status (routing), NOT the refund status
    proposed_route TEXT,
    route TEXT,
    supplier_status TEXT NOT NULL,  -- supplier task status for this case
    task_id TEXT,
    duplicate_of_task TEXT,
    confidence REAL,
    band TEXT,
    rule_version TEXT,
    decision_json TEXT,
    extraction_json TEXT
);
CREATE TABLE IF NOT EXISTS supplier_tasks (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    routing_case_id TEXT NOT NULL REFERENCES routing_cases(id),
    dedup_key TEXT NOT NULL,
    order_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    complaint_type TEXT NOT NULL,
    status TEXT NOT NULL,
    supplier TEXT NOT NULL,
    draft TEXT NOT NULL,
    fields_json TEXT NOT NULL,
    created_by TEXT NOT NULL,
    is_mock INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_supplier_tasks_one_open
    ON supplier_tasks(dedup_key) WHERE status IN ({",".join(repr(s) for s in OPEN_TASK_STATUSES)});
CREATE TABLE IF NOT EXISTS routing_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    routing_case_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    event TEXT NOT NULL,
    detail_json TEXT
);
"""
ROUTING_TABLES = ("routing_log", "supplier_tasks", "routing_cases")


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class RoutingStore:
    def __init__(self, path: str) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self, reset: bool = False) -> None:
        with self.connect() as conn:
            if reset:
                for t in ROUTING_TABLES:
                    conn.execute(f"DROP TABLE IF EXISTS {t}")
            conn.executescript(SCHEMA)

    def log(self, rcase_id: str, event: str, detail=None) -> None:
        with self.connect() as conn:
            conn.execute("INSERT INTO routing_log (routing_case_id, ts, event, detail_json) VALUES (?,?,?,?)",
                         (rcase_id, utcnow(), event, json.dumps(detail, default=str, ensure_ascii=False)
                          if detail is not None else None))

    def events(self, rcase_id: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM routing_log WHERE routing_case_id=? ORDER BY id", (rcase_id,))
            out = []
            for r in rows.fetchall():
                d = dict(r)
                d["detail"] = json.loads(d.pop("detail_json")) if d.get("detail_json") else None
                out.append(d)
        return out

    def insert_case(self, **f) -> None:
        now = utcnow()
        f.setdefault("created_at", now)
        f.setdefault("updated_at", now)
        with self.connect() as conn:
            conn.execute(f"INSERT INTO routing_cases ({','.join(f)}) VALUES ({','.join('?' for _ in f)})",
                         tuple(f.values()))

    def update_case(self, rid: str, **f) -> None:
        f["updated_at"] = utcnow()
        with self.connect() as conn:
            conn.execute(f"UPDATE routing_cases SET {','.join(k + '=?' for k in f)} WHERE id=?",
                         (*f.values(), rid))

    def get_case(self, rid: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM routing_cases WHERE id=?", (rid,)).fetchone()
        return _decode(row) if row else None

    def list_cases(self, tradeos_case_id: str | None = None, limit: int = 50) -> list[dict]:
        sql, args = "SELECT * FROM routing_cases", []
        if tradeos_case_id:
            sql += " WHERE tradeos_case_id=?"
            args.append(tradeos_case_id)
        sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        args.append(limit)
        with self.connect() as conn:
            return [_decode(r) for r in conn.execute(sql, args).fetchall()]

    def open_task_for(self, dedup_key: str) -> dict | None:
        q = ",".join("?" for _ in OPEN_TASK_STATUSES)
        with self.connect() as conn:
            row = conn.execute(f"SELECT * FROM supplier_tasks WHERE dedup_key=? AND status IN ({q})",
                               (dedup_key, *OPEN_TASK_STATUSES)).fetchone()
        return _decode_task(row) if row else None

    def insert_task(self, **f) -> bool:
        """False if an open task with the same dedup_key already exists (DB-enforced)."""
        try:
            with self.connect() as conn:
                conn.execute(f"INSERT INTO supplier_tasks ({','.join(f)}) VALUES ({','.join('?' for _ in f)})",
                             tuple(f.values()))
            return True
        except sqlite3.IntegrityError:
            return False

    def get_task(self, tid: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM supplier_tasks WHERE id=?", (tid,)).fetchone()
        return _decode_task(row) if row else None

    def list_tasks(self) -> list[dict]:
        with self.connect() as conn:
            return [_decode_task(r) for r in
                    conn.execute("SELECT * FROM supplier_tasks ORDER BY created_at DESC, rowid DESC").fetchall()]


def _decode(row) -> dict:
    d = dict(row)
    for k in ("decision_json", "extraction_json"):
        d[k.removesuffix("_json")] = json.loads(d[k]) if d.get(k) else None
    return d


def _decode_task(row) -> dict:
    d = dict(row)
    d["fields"] = json.loads(d.pop("fields_json"))
    return d


# ----------------------------------------------------------------------------- service
TRADEOS_DEMO_VARIANT = {"TRAIL-RUNNER-42": "42"}  # the Phase A demo product is EU size 42


class RoutingService:
    def __init__(self, store: RoutingStore, extractor: RoutingExtractor, config: RoutingConfig | None = None,
                 today: Callable[[], date] | None = None) -> None:
        self.store = store
        self.extractor = extractor
        self.config = config or RoutingConfig()
        self.today = today or (lambda: datetime.now(timezone.utc).date())
        self._lock = threading.Lock()

    def _status(self, rid: str, old: str, new: str, detail: dict | None = None) -> None:
        check_case_transition(old, new)
        self.store.update_case(rid, status=new)
        self.store.log(rid, f"status {old} → {new}", detail)

    def triage(self, message: str, ctx: CaseContext | None = None, source: str = "free",
               tradeos_case_id: str | None = None) -> str:
        ctx = ctx or CaseContext()
        rid = f"R-{uuid.uuid4().hex[:6].upper()}"
        self.store.insert_case(id=rid, source=source, tradeos_case_id=tradeos_case_id, customer=ctx.customer,
                               linked_order_id=ctx.linked_order_id or (ctx.order_override or {}).get("order_id"),
                               message=message, status=CASE_RECEIVED, supplier_status=T_NOT_REQUIRED,
                               rule_version=RULE_VERSION)
        self.store.log(rid, "case received", {"source": source, "tradeos_case_id": tradeos_case_id,
                                              "customer": ctx.customer, "linked_order": ctx.linked_order_id})
        self._status(rid, CASE_RECEIVED, CLASSIFYING)
        t0 = time.perf_counter()
        ex = self.extractor.extract(message)
        self.store.update_case(rid, extraction_json=ex.model_dump_json())
        self.store.log(rid, "AI extraction (information only; rules decide)",
                       {"extractor": ex.extractor, "note": ex.note, "fields": ex.fields.model_dump(),
                        "llm_confidence": ex.llm_confidence, "keyword_types": ex.keyword_types})
        with self._lock:  # decision + task creation are serialised; the DB index is the second guard
            decision = decide(ex, message, ctx, self.config, self.today(), self.store.open_task_for)
            decision_ms = round((time.perf_counter() - t0) * 1000, 1)
            self._record(rid, decision, decision_ms)
            if decision.final_route == SUPPLIER_REQUIRED:
                self._open_task(rid, decision, created_by="auto")
        return rid

    def _record(self, rid: str, decision: Decision, ms: float) -> None:
        d = decision.to_dict()
        self.store.update_case(rid, proposed_route=decision.proposed_route, route=decision.final_route,
                               confidence=decision.confidence.get("combined"), band=decision.confidence.get("band"),
                               decision_json=json.dumps(d, default=str, ensure_ascii=False))
        self._status(rid, CLASSIFYING, decision.final_route, {
            "route": decision.final_route, "proposed_route": decision.proposed_route,
            "gates": [asdict(g) for g in decision.gates], "trigger_reason": decision.trigger_reason,
            "data_used": decision.data_used, "rule_version": decision.rule_version,
            "confidence": decision.confidence, "decided_at": utcnow(), "pipeline_ms": ms})

    def _open_task(self, rid: str, decision: Decision, created_by: str) -> str | None:
        existing = self.store.open_task_for(decision.dedup_key)
        if existing is None:
            supplier = CATALOG[decision.identifiers["sku"]]["supplier"]
            tid = f"ST-{uuid.uuid4().hex[:6].upper()}"
            draft, fields = draft_supplier_task(rid, decision, supplier)
            ok = self.store.insert_task(id=tid, created_at=utcnow(), routing_case_id=rid,
                                        dedup_key=decision.dedup_key, order_id=decision.identifiers["order_id"],
                                        sku=decision.identifiers["sku"], complaint_type=decision.complaint_type,
                                        status=T_DRAFT_READY, supplier=supplier, draft=draft,
                                        fields_json=json.dumps(fields, ensure_ascii=False), created_by=created_by)
            if ok:
                check_task_transition(T_NOT_REQUIRED, T_DRAFT_READY)
                self.store.update_case(rid, task_id=tid, supplier_status=T_DRAFT_READY)
                self.store.log(rid, "Internal supplier task created — DRAFT_READY (not sent, supplier NOT contacted)",
                               {"task_id": tid, "dedup_key": decision.dedup_key, "created_by": created_by,
                                "trigger_reason": decision.trigger_reason, "rule_version": decision.rule_version})
                self._status(rid, SUPPLIER_REQUIRED, SUPPLIER_TASK_OPEN)
                return tid
            existing = self.store.open_task_for(decision.dedup_key)  # lost a race: link instead
        self.store.update_case(rid, task_id=existing["id"], duplicate_of_task=existing["id"],
                               supplier_status=existing["status"])
        self.store.log(rid, "Duplicate prevented — linked to the existing open supplier task",
                       {"task_id": existing["id"], "dedup_key": decision.dedup_key})
        self._status(rid, SUPPLIER_REQUIRED, SUPPLIER_TASK_OPEN)
        return None

    def confirm_supplier_route(self, rid: str, by: str = "merchant") -> str | None:
        """Human confirmation for the 0.70-0.89 band. Only possible when ALL hard gates passed."""
        with self._lock:
            case = self.store.get_case(rid)
            if not case:
                raise KeyError(rid)
            dec = case["decision"] or {}
            gates_ok = [g for g in dec.get("gates", []) if g["gate"] in (1, 2, 3)]
            if (case["status"] != NEEDS_HUMAN_REVIEW or case["proposed_route"] != SUPPLIER_REQUIRED
                    or len(gates_ok) != 3 or not all(g["passed"] for g in gates_ok)):
                raise InvalidTransition("Only a case whose hard gates (1-3) all passed and that proposed "
                                        "SUPPLIER_REQUIRED can be confirmed.")
            decision = Decision(complaint_type=dec["complaint_type"], identifiers=dec["identifiers"],
                                trigger_reason=dec["trigger_reason"], dedup_key=dec["dedup_key"],
                                rule_version=dec["rule_version"])
            self._status(rid, NEEDS_HUMAN_REVIEW, SUPPLIER_REQUIRED, {"confirmed_by": by, "at": utcnow()})
            self.store.update_case(rid, route=SUPPLIER_REQUIRED)
            return self._open_task(rid, decision, created_by=f"human_confirm:{by}")

    # ------------------------------------------------------------------ TradeOS demo case -> context
    def context_for_tradeos_case(self, case: dict) -> CaseContext:
        if case.get("purchase_date_seeded"):
            odate = case["purchase_date_seeded"]
        else:
            ts = case.get("capture_time") or case.get("created_at")
            odate = ts[:10] if ts else self.today().isoformat()
        order = {"order_id": case.get("order_id") or case["id"], "customer": case["customer_name"],
                 "order_date": odate, "is_mock": False, "source": "TradeOS case record (PayPal sandbox order)",
                 "lines": [{"sku": case["product_sku"], "variant": TRADEOS_DEMO_VARIANT.get(case["product_sku"], "?"),
                            "qty": 1, "logistics": None}]}
        return CaseContext(customer=case["customer_name"], order_override=order)

    def triage_tradeos_case(self, case: dict) -> str:
        if case["product_sku"] not in CATALOG:
            raise ValueError("product not in the routing catalog")
        return self.triage(case["customer_message"], self.context_for_tradeos_case(case), source="tradeos_case",
                           tradeos_case_id=case["id"])


__all__ = ["RoutingService", "RoutingStore", "RoutingConfig", "CaseContext", "decide", "MOCK_LABEL"]
