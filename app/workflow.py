"""The one TradeOS loop (plan §3):

request -> AI intent -> deterministic policy -> autonomy -> supplier -> approval -> PayPal refund (or block).

A case is approved either by a person ("human") or, when the merchant's autonomy
settings allow it, by the merchant's own policy ("auto"). Both take the same
``approve()`` path, the same per-case lock and the same ``_guard_refund`` hard
guard; the difference is recorded on the case and on its hash chain so the audit
can say which one it was.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable

from .autonomy import decide_detailed
from .config import Settings
from .db import Database, next_seq
from .intent import AssistFields, IntentExtractor
from .notes import TemplateNoteWriter
from .paypal_client import PayPalClient, PayPalError, find_link, first_capture
from .paypal_mock import MockPayPalClient
from .intent import looks_like_injection
from .policy import PolicyInput, PolicyResult, evaluate
from .supplier import OUT_OF_STOCK, draft_supplier_message, mock_supplier_reply

HUMAN = "human"
AUTO = "auto"

DEMO_PRODUCT = {
    "sku": "TRAIL-RUNNER-42",
    "name": "Trail Runner sneakers, EU size 42",
    "category": "footwear",
    "returnable": True,
    "price": "49.99",
    "supplier": "Stride Footwear Co. (fictional demo supplier)",
}
# Case A (and R / D / P): a return for money back -> the refund path.
DEMO_MESSAGE = "These sneakers are too small and don't fit. I'd like to return them and get my money back."
# Exchange showcase: a size swap -> supplier replacement, NO refund (Refund API never called).
EXCHANGE_MESSAGE = "The shoes are too small. Can I exchange size 42 for size 43?"
# A/B are the two proof paths (plan §3). F = free text / presets. R and D are failure-mode
# demos of the SAME loop: R forces one PayPal refund error (sandbox negative testing),
# D sends the refund request twice to show idempotency.
SCENARIOS = {
    "A": {"customer_name": "Maria (demo customer)", "seeded_days_ago": None, "label": "Case A"},
    "B": {"customer_name": "Tom (demo customer)", "seeded_days_ago": "case_b", "label": "Case B"},
    "F": {"customer_name": "Free-text customer", "seeded_days_ago": None, "label": "Free text"},
    "R": {"customer_name": "Ana (failure test)", "seeded_days_ago": None, "label": "Refund API failure"},
    "D": {"customer_name": "Ken (failure test)", "seeded_days_ago": None, "label": "Double-click approve"},
    # Mock-only demo: same loop as A, but the (mock) PayPal refund starts PENDING (ECHECK) and completes
    # ~20 s later, so PENDING -> COMPLETED via reconcile or a signed webhook can be shown on screen.
    "P": {"customer_name": "Lee (MOCK pending demo)", "seeded_days_ago": None, "label": "Pending refund (MOCK)"},
}
MAX_TRACKED_CASES = 500  # cap for per-case in-memory maps (locks, reconcile throttle)
RUNNABLE = ("A", "B", "R", "D", "P")
MOCK_ONLY = ("P",)

# Case statuses
NEW = "NEW"
AWAITING_BUYER = "AWAITING_BUYER_APPROVAL"
PENDING_APPROVAL = "PENDING_APPROVAL"
REJECTED = "REJECTED"
DECLINED = "DECLINED_BY_HUMAN"
REFUND_COMPLETED = "REFUND_COMPLETED"
REFUND_PENDING = "REFUND_PENDING"
REFUND_FAILED = "REFUND_FAILED"
REFUND_ERROR = "REFUND_ERROR"            # PayPal answered with an error (4xx): it confirmed no refund was made
REFUND_UNKNOWN = "REFUND_OUTCOME_UNKNOWN"  # timeout / network / 5xx: PayPal may or may not have refunded
ERROR = "ERROR"
EXCHANGE_ARRANGED = "EXCHANGE_ARRANGED"  # human approved the exchange; supplier ships a replacement; no refund
NEEDS_HUMAN = "NEEDS_HUMAN"              # e.g. exchange but the supplier is out of stock: offer a refund?


class RefundNotAllowed(Exception):
    """Raised when code refuses to move money. This is the hard guard, independent of the UI."""


class CaseNotFound(Exception):
    pass


class Workflow:
    def __init__(self, db: Database, settings: Settings, extractor: IntentExtractor, paypal: Any = None,
                 today: Callable[[], date] | None = None, note_writer: Any = None) -> None:
        self.db = db
        self.settings = settings
        self.extractor = extractor
        self.note_writer = note_writer or TemplateNoteWriter()
        self._paypal = paypal
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._reconciled: dict[str, float] = {}
        self._refund_checks: dict[str, str] = {}
        self._inflight = 0              # money operations in progress (approve / refund / retry / recovery)
        self._resetting = False         # demo reset in progress: money operations are refused
        self._needs_check: set[str] = set()
        self._pending_recovery: set[str] = set()
        self._pending_recovery_requests: set[str] = set()
        # UTC, to match PayPal timestamps.
        self.today = today or (lambda: datetime.now(timezone.utc).date())

    # ------------------------------------------------------------------ PayPal
    @property
    def paypal_mode(self) -> str:
        if self._paypal is not None:
            return "mock" if getattr(self._paypal, "is_mock", False) else "sandbox"
        if self.settings.paypal_mock:
            return "mock"
        return "sandbox" if self.settings.paypal_configured else "unconfigured"

    def paypal(self):
        if self._paypal is None:
            if self.settings.paypal_mock:
                self._paypal = MockPayPalClient()
            else:
                # Raises a visible PayPalError if credentials are missing.
                self._paypal = PayPalClient(self.settings.paypal_client_id, self.settings.paypal_client_secret,
                                            self.settings.paypal_base_url)
        return self._paypal

    def _pp(self, case_id: str, operation: str, *args, **kwargs) -> dict:
        """Call PayPal and log every call (so 'Refund API: NOT CALLED' is provable from the log)."""
        client = self.paypal()
        request_id = kwargs.get("request_id")
        pos = _REQUEST_ID_ARG.get(operation)
        if request_id is None and pos is not None and len(args) > pos:
            request_id = args[pos]
        try:
            result = getattr(client, operation)(*args, **kwargs)
        except PayPalError as exc:
            self.db.log_paypal_call(case_id, operation, False, str(exc), debug_id=exc.debug_id or None,
                                    request_id=request_id,
                                    evidence={"http_status": exc.status_code, "name": exc.name or None,
                                              "issue": ((exc.details or [{}])[0] or {}).get("issue")
                                              if isinstance(exc.details, list) else None})
            raise
        summary = {k: result.get(k) for k in ("id", "status") if isinstance(result, dict)}
        self.db.log_paypal_call(case_id, operation, True, json.dumps(summary), debug_id=_last_debug_id(client),
                                request_id=request_id, evidence=_evidence(operation, result))
        return result

    # ------------------------------------------------------------------ seed
    def seed_demo(self) -> None:
        self.db.upsert_product(**DEMO_PRODUCT)
        for scenario in ("A", "B"):
            self.new_case(scenario)

    def new_case(self, scenario: str, message: str | None = None, label: str | None = None,
                 days_ago: int | None = None) -> str:
        if scenario not in SCENARIOS:
            raise ValueError("unknown scenario")
        spec = SCENARIOS[scenario]
        seeded = None
        if spec["seeded_days_ago"] and days_ago is None:
            days_ago = self.settings.case_b_days_since_purchase
        if days_ago:
            seeded = (self.today() - timedelta(days=days_ago)).isoformat()
        case_id = f"{scenario}-{uuid.uuid4().hex[:6].upper()}"
        self.db.insert_case(
            id=case_id, scenario=scenario, label=label or spec["label"], status=NEW,
            customer_name=spec["customer_name"], customer_message=message or DEMO_MESSAGE,
            product_sku=DEMO_PRODUCT["sku"], amount=self.settings.order_amount, currency=self.settings.currency,
            purchase_date_seeded=seeded,
            refund_fault=self.settings.refund_failure_mock_code if scenario == "R" else None,
        )
        return case_id

    def _lock(self, case_id: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.pop(case_id, None) or threading.Lock()
            self._locks[case_id] = lock  # most recently used last
            if len(self._locks) > MAX_TRACKED_CASES:  # bounded: evict idle locks, oldest first
                for key in [k for k, v in self._locks.items() if k != case_id and not v.locked()]:
                    if len(self._locks) <= MAX_TRACKED_CASES:
                        break
                    del self._locks[key]
            return lock

    @contextmanager
    def _money_op(self):
        """Marks a money operation in flight so a demo reset can't run underneath it."""
        with self._locks_guard:
            if self._resetting:
                raise RefundNotAllowed("A demo reset is in progress — try again in a moment.")
            self._inflight += 1
        try:
            yield
        finally:
            with self._locks_guard:
                self._inflight -= 1

    def begin_reset(self) -> bool:
        """Demo reset may start only when no refund call is in flight and no case lock is held."""
        with self._locks_guard:
            if self._resetting or self._inflight or any(lock.locked() for lock in self._locks.values()):
                return False
            self._resetting = True
            return True

    def end_reset(self) -> None:
        with self._locks_guard:
            self._resetting = False

    def reset_runtime_state(self) -> None:
        """Demo reset: forget per-case in-memory state (idle locks) along with the database."""
        with self._locks_guard:
            for key in [k for k, v in self._locks.items() if not v.locked()]:
                del self._locks[key]
            self._reconciled.clear()
            self._refund_checks.clear()

    def _case(self, case_id: str) -> dict:
        case = self.db.get_case(case_id)
        if not case:
            raise CaseNotFound(case_id)
        return case

    # ------------------------------------------------------------------ run
    def run_scenario(self, scenario: str) -> str:
        if scenario not in RUNNABLE:
            raise ValueError("unknown scenario")
        latest = self.db.latest_case(scenario)
        case_id = latest["id"] if latest and latest["status"] == NEW else self.new_case(scenario)
        self.process(case_id)
        return case_id

    def run_free_text(self, message: str, late: bool = False, label: str | None = None) -> str:
        """A judge's own message through the same loop: real sandbox order + capture, AI, policy, ..."""
        message = clean_message(message, self.settings.free_text_max_chars)
        if not message:
            raise ValueError("Message is empty.")
        days = self.settings.case_b_days_since_purchase if late else None
        case_id = self.new_case("F", message=message, label=label or "Free text", days_ago=days)
        self.process(case_id)
        return case_id

    def process(self, case_id: str) -> None:
        self._case(case_id)  # raises CaseNotFound for an unknown id
        s = self.settings
        try:
            # Step 1: PayPal Sandbox order + capture (card payment source => no buyer login needed).
            try:
                order = self._pp(case_id, "create_order_with_card", s.order_amount, s.currency, case_id,
                                 f"TradeOS demo {case_id}", f"tradeos-order-{case_id}")
            except PayPalError as card_err:
                self.db.audit(case_id, "payment", "Card capture unavailable — falling back to buyer approval",
                              card_err.to_dict())
                order = self._pp(case_id, "create_order", s.order_amount, s.currency, case_id,
                                 f"TradeOS demo {case_id}", f"tradeos-order-wallet-{case_id}",
                                 f"{s.public_base_url}/cases/{case_id}/paypal-return",
                                 f"{s.public_base_url}/?case={case_id}")
            self.db.update_case(case_id, order_id=order["id"], order_status=order.get("status"))
            self.db.audit(case_id, "payment", "PayPal order created",
                          {"order_id": order["id"], "status": order.get("status"),
                           "amount": f"{s.order_amount} {s.currency}"})

            if order.get("status") == "APPROVED":
                order = self._pp(case_id, "capture_order", order["id"], f"tradeos-capture-{case_id}")
            capture = first_capture(order)
            if not capture:
                approve = find_link(order, "payer-action", "approve")
                self.db.update_case(case_id, status=AWAITING_BUYER, approve_url=approve)
                self.db.audit(case_id, "payment", "Waiting for sandbox buyer approval",
                              {"approve_url": approve, "order_status": order.get("status")})
                return
            self._record_capture(case_id, order, capture)
        except PayPalError as exc:
            self._fail(case_id, "payment", exc)
            return
        self._after_capture(case_id)

    def complete_buyer_approval(self, case_id: str) -> None:
        """Fallback path: buyer approved in the PayPal sandbox, now capture."""
        case = self._case(case_id)
        if case["status"] != AWAITING_BUYER:
            return
        try:
            order = self._pp(case_id, "capture_order", case["order_id"], f"tradeos-capture-{case_id}")
            capture = first_capture(order)
            if not capture:
                raise PayPalError(f"Capture returned no capture (order status {order.get('status')})")
            self._record_capture(case_id, order, capture)
        except PayPalError as exc:
            self._fail(case_id, "payment", exc)
            return
        self._after_capture(case_id)

    def _record_capture(self, case_id: str, order: dict, capture: dict) -> None:
        self.db.update_case(case_id, order_status=order.get("status"), capture_id=capture["id"],
                            capture_status=capture.get("status"), capture_time=capture.get("create_time"))
        self.db.audit(case_id, "payment", "PayPal payment captured",
                      {"order_id": order["id"], "capture_id": capture["id"], "status": capture.get("status")})

    def _fail(self, case_id: str, stage: str, exc: PayPalError, status: str = ERROR) -> None:
        self.db.update_case(case_id, status=status, error=str(exc))
        self.db.audit(case_id, stage, "PayPal error", exc.to_dict())

    def _after_capture(self, case_id: str) -> None:
        case = self._case(case_id)
        product = self.db.get_product(case["product_sku"])

        # Step 2: customer request.
        self.db.audit(case_id, "request", "Customer request received",
                      {"customer": case["customer_name"], "message": case["customer_message"]})

        # Step 3: AI extracts intent (language only — it does not decide money).
        extraction = self.extractor.extract(case["customer_message"])
        intent = extraction.result.model_dump()  # the ONLY AI output the policy engine reads
        assist = extraction.assist.model_dump() if extraction.assist else None  # info only
        self.db.update_case(case_id, intent_json=json.dumps(intent),
                            assist_json=json.dumps(assist, ensure_ascii=False) if assist else None,
                            extraction_json=json.dumps({"extractor": extraction.extractor, "note": extraction.note,
                                                        "assist_note": extraction.assist_note,
                                                        "injection_guard": extraction.injection_guard}))
        self.db.audit(case_id, "intent", "Intent extracted",
                      {**intent, "extractor": extraction.extractor, "note": extraction.note,
                       "assist": assist, "assist_note": extraction.assist_note})
        if extraction.injection_guard:
            self.db.audit(case_id, "intent",
                          "Keyword fallback + injection detected → intent UNKNOWN, sent to a human",
                          {"why": "The LLM was unavailable, and keyword rules can be steered by injected words, "
                                  "so this message cannot become an approvable request.", "forced": intent})

        # Step 4: policy engine, fed with live PayPal capture data.
        try:
            capture = self._pp(case_id, "get_capture", case["capture_id"])
        except PayPalError as exc:
            self._fail(case_id, "policy", exc)
            return
        self.db.update_case(case_id, capture_status=capture.get("status"))
        pre = self._evaluate(case, product, extraction.result, capture, supplier_status=None, require_supplier=False)
        self.db.audit(case_id, "policy", f"Policy pre-check: {pre.decision}", pre.to_dict())
        if not pre.eligible:
            self._reject(case_id, pre, extraction)
            return

        if pre.action == "REFUND":
            # Return for a refund: no supplier step. Policy is final; the merchant's autonomy
            # settings decide whether this still needs a person.
            self.db.audit(case_id, "policy", "Policy final: ELIGIBLE — return for a refund (supplier not involved)",
                          pre.to_dict())
            self.db.update_case(case_id, policy_json=json.dumps(pre.to_dict()), decision="ELIGIBLE",
                                status=PENDING_APPROVAL)
            if self._autonomy_verdict(case_id, case, pre, extraction).decision != "AUTO":
                self._write_note(case_id, "PENDING_NOTE", pre.to_dict(), extraction.assist)
                self.db.audit(case_id, "human", "Waiting for human approval of the refund",
                              {"amount": f"{case['amount']} {case['currency']}"})
                return
            # The same approve() path, lock and hard guard a person clicking Approve would take.
            self.approve(case_id, approver=AUTO, source=AUTO)
            return

        # Step 5 (exchange only): supplier draft + clearly labelled mock reply. No money moves on this path.
        draft = draft_supplier_message(self._case(case_id), product, intent)
        self.db.update_case(case_id, supplier_draft=draft)
        self.db.audit(case_id, "supplier", "Supplier draft generated", {"draft": draft})
        reply = mock_supplier_reply(case, out_of_stock=self.settings.mock_supplier_out_of_stock)
        self.db.update_case(case_id, supplier_reply=reply["status"])
        self.db.audit(case_id, "supplier", f"Supplier replied: {reply['status']} (MOCK)", reply)
        if reply["status"] == OUT_OF_STOCK:
            # Never an automatic refund: a person decides whether to offer one.
            result = self._evaluate(case, product, extraction.result, capture, supplier_status=reply["status"],
                                    require_supplier=True)
            self.db.update_case(case_id, policy_json=json.dumps(result.to_dict()), decision="NEEDS_HUMAN",
                                status=NEEDS_HUMAN)
            self.db.audit(case_id, "human", "Needs a human: replacement out of stock (MOCK) — offer a refund? "
                          "Refund API NOT CALLED", {"supplier": reply["status"], "refund_id": None})
            return

        final = self._evaluate(case, product, extraction.result, capture, supplier_status=reply["status"],
                               require_supplier=True)
        self.db.audit(case_id, "policy", f"Policy final: {final.decision}", final.to_dict())
        if not final.eligible:
            self._reject(case_id, final, extraction)
            return
        # EXCHANGE_ELIGIBLE (not ELIGIBLE): the refund gate refuses anything but ELIGIBLE, so an exchange
        # can never reach the Refund API — whether a person approved it or the merchant's policy did.
        self.db.update_case(case_id, policy_json=json.dumps(final.to_dict()), decision="EXCHANGE_ELIGIBLE",
                            status=PENDING_APPROVAL)
        if self._autonomy_verdict(case_id, case, final, extraction).decision != "AUTO":
            self._write_note(case_id, "PENDING_NOTE", final.to_dict(), extraction.assist)
            self.db.audit(case_id, "human", "Waiting for human approval of the exchange (no refund)",
                          {"refund": "none — exchange"})
            return
        self.approve(case_id, approver=AUTO, source=AUTO)

    def _autonomy_verdict(self, case_id: str, case: dict, policy: PolicyResult, extraction):
        """The merchant's autonomy decision for a case the policy already passed, recorded on the timeline.

        Shared by the refund and the exchange path so both answer the same question the same way: may the
        merchant's own policy approve this, or does a person have to? It reads the policy result and the
        merchant's settings only — it cannot turn a policy NO into a YES (a non-eligible policy comes back
        BLOCK), and it never calls PayPal.
        """
        s = self.settings
        verdict = decide_detailed(
            policy,
            amount=Decimal(case["amount"]),
            auto_enabled=s.auto_enabled,
            auto_refund_max_amount=s.auto_refund_max_amount,
            auto_exchange_enabled=s.auto_exchange_enabled,
            injection_suspected=looks_like_injection(case.get("customer_message") or ""),
            intent_is_unknown=extraction.result.intent == "UNKNOWN",
            action=policy.action,
        )
        limits = {"auto_enabled": s.auto_enabled, "auto_refund_max_amount": str(s.auto_refund_max_amount),
                  "auto_exchange_enabled": s.auto_exchange_enabled}
        if verdict.decision == "AUTO":
            self.db.audit(case_id, "human", "Autonomy: AUTO — within the merchant's limits, no human needed",
                          {"why": verdict.reason, **limits, "amount": f"{case['amount']} {case['currency']}"})
        else:
            # Anything that is not an explicit AUTO is a person's call: AUTO off, an unreadable request,
            # an instruction-like message, a limit, or the switch for this action being off.
            self.db.audit(case_id, "human", "Autonomy: HUMAN — this case needs a person",
                          {"why": verdict.reason, **limits})
        return verdict

    def _evaluate(self, case: dict, product: dict, intent, capture: dict, supplier_status: str | None,
                  require_supplier: bool) -> PolicyResult:
        amount = (capture.get("amount") or {})
        if case.get("purchase_date_seeded"):
            purchase = date.fromisoformat(case["purchase_date_seeded"])
        else:
            ts = capture.get("create_time") or case.get("capture_time")
            purchase = datetime.fromisoformat(ts.replace("Z", "+00:00")).date() if ts else self.today()
        return evaluate(PolicyInput(
            capture_status=capture.get("status"),
            captured_amount=Decimal(amount["value"]) if amount.get("value") else None,
            capture_currency=amount.get("currency_code"),
            expected_currency=case["currency"],
            requested_refund=Decimal(case["amount"]),
            already_refunded=self._already_refunded(case, capture),
            purchase_date=purchase,
            today=self.today(),
            return_window_days=self.settings.return_window_days,
            product_returnable=bool(product["returnable"]),
            product_name=product["name"],
            intent=intent,
            supplier_status=supplier_status,
            require_supplier=require_supplier,
            injection_suspected=looks_like_injection(case.get("customer_message") or ""),
        ))

    def _reject(self, case_id: str, result: PolicyResult, extraction=None) -> None:
        self.db.update_case(case_id, policy_json=json.dumps(result.to_dict()), decision="REJECTED", status=REJECTED)
        self.db.audit(case_id, "paypal", "Refund API NOT CALLED — policy rejected the case",
                      {"reasons": result.reasons, "refund_id": None})
        if extraction is not None:
            self._write_note(case_id, "REJECTION_NOTE", result.to_dict(), extraction.assist)

    NOTE_TITLES = {
        "PENDING_NOTE": "Customer note drafted: awaiting merchant approval (not sent)",
        "REFUND_NOTE": "note_to_payer written for the refund call (neutral wording)",
        "COMPLETED_NOTE": "Final customer note written after PayPal COMPLETED",
        "FAILURE_NOTE": "Customer note drafted: refund could not be completed yet (not sent)",
        "REJECTION_NOTE": "Customer decision note drafted (no refund issued)",
        "EXCHANGE_NOTE": "Customer note written after the human approved the exchange (no refund)",
    }

    def _write_note(self, case_id: str, outcome: str, policy: dict | None, assist) -> dict | None:
        """Customer-language note written from the case's ACTUAL state (see app/notes.py).

        REFUND_NOTE goes to the payer_note column (sent with the refund call); every other
        outcome replaces the customer note shown in the dashboard.
        """
        case = self._case(case_id)
        if isinstance(assist, dict):
            try:
                assist = AssistFields.model_validate(assist)
            except Exception:
                assist = None
        try:
            note = self.note_writer.write(outcome, amount=case["amount"], currency=case["currency"],
                                          policy=policy or case.get("policy") or {}, assist=assist)
        except Exception as exc:  # the note is a convenience; never let it break the loop
            self.db.audit(case_id, "note", "Customer note unavailable", {"error": type(exc).__name__})
            return None
        column = "payer_note_json" if outcome == "REFUND_NOTE" else "note_json"
        self.db.update_case(case_id, **{column: note.model_dump_json()})
        self.db.audit(case_id, "note", self.NOTE_TITLES[outcome], note.model_dump())
        return note.model_dump()

    def _payer_note(self, case_id: str) -> str | None:
        """The note_to_payer for the refund call: written once at Approve, reused on retries/replays
        so the idempotent request body never changes."""
        case = self._case(case_id)
        if case.get("payer_note"):
            return case["payer_note"]["text"]
        note = self._write_note(case_id, "REFUND_NOTE", None, case.get("assist"))
        return note["text"] if note else None

    # ------------------------------------------------------------------ approval + money
    @staticmethod
    def _approval_title(source: str) -> str:
        """The audit line has to say which of the two happened. An auto-approval is never
        reported as a human one (and vice versa)."""
        return ("Auto-approved by the merchant's policy — no human involved" if source == AUTO
                else "Human approved the refund")

    def approve(self, case_id: str, approver: str = "merchant", source: str = HUMAN) -> None:
        """approver/source: a person ("merchant"/"human") or the merchant's own policy ("auto"/"auto").

        Both are the same code path: the same per-case lock, the same hard guard, the same PayPal
        call. Only the recorded origin differs.
        """
        # Serialised per case: a double-click can never start two approvals.
        try:
            with self._money_op(), self._lock(case_id):
                case = self._case(case_id)
                if case["status"] == PENDING_APPROVAL and case["decision"] == "EXCHANGE_ELIGIBLE":
                    self._approve_exchange(case_id, approver, source)
                    return
                if case["status"] != PENDING_APPROVAL or case["decision"] != "ELIGIBLE":
                    raise RefundNotAllowed(f"Case {case_id} is not awaiting approval (status {case['status']}, "
                                           f"policy {case['decision']}).")
                self.db.update_case(case_id, human_decision="APPROVED", human_at=self._now(),
                                    approval_source=source)
                self.db.audit(case_id, "human", self._approval_title(source),
                              {"approver": approver, "source": source})
                self._execute_refund(case_id)
        finally:
            self._after_money(case_id)

    def _approve_exchange(self, case_id: str, approver: str, source: str = HUMAN) -> None:
        """Exchange path: the replacement is approved. No money moves: Refund API NOT CALLED."""
        title = ("Auto-approved by the merchant's policy — no human involved" if source == AUTO
                 else "Human approved the exchange")
        self.db.update_case(case_id, human_decision="APPROVED", human_at=self._now(), approval_source=source,
                            status=EXCHANGE_ARRANGED)
        self.db.audit(case_id, "human", title, {"approver": approver, "source": source})
        self.db.audit(case_id, "paypal", "Refund API NOT CALLED — exchange arranged (replacement via the MOCK "
                      "supplier), no refund", {"refund_id": None})
        case = self._case(case_id)
        self._write_note(case_id, "EXCHANGE_NOTE", None, case.get("assist"))

    def _after_money(self, case_id: str) -> None:
        """Outside the case lock: start the PayPal check for an unknown refund outcome."""
        if case_id in self._needs_check:
            self._needs_check.discard(case_id)
            self._start_refund_check(case_id)

    def approve_twice(self, case_id: str) -> None:
        """Failure-mode demo: a double-clicked Approve.

        Click 1 approves and refunds. Click 2 is refused by the app (case no longer pending).
        Then the identical refund request is replayed straight at PayPal with the SAME
        PayPal-Request-Id, to show that even a request that slipped through returns the
        same refund instead of a second one.
        """
        self.approve(case_id)
        second_click = "refused by TradeOS (case no longer awaiting approval)"
        try:
            self.approve(case_id)
            second_click = "accepted (unexpected)"
        except RefundNotAllowed:
            pass
        self.db.audit(case_id, "human", "Second Approve click refused — case is no longer pending", {})
        self.replay_refund_request(case_id, second_click)

    def replay_refund_request(self, case_id: str, second_click: str = "") -> dict:
        with self._money_op(), self._lock(case_id):
            case = self._case(case_id)
            self._guard_refund(case)
            if not case["refund_id"]:
                raise RefundNotAllowed("No refund to replay.")
            request_id = self._request_id(case)
            note = (case.get("payer_note") or {}).get("text")
            again = self._pp(case_id, "refund_capture", case["capture_id"], request_id, note_to_payer=note)
            total = ((again.get("seller_payable_breakdown") or {}).get("total_refunded_amount") or {})
            evidence = {
                "clicks": 2,
                "second_click": second_click,
                "paypal_request_id": request_id,
                "first_refund_id": case["refund_id"],
                "replayed_refund_id": again.get("id"),
                "same_refund": again.get("id") == case["refund_id"],
                "refund_api_calls": len(self.db.paypal_calls(case_id, "refund_capture")),
                "total_refunded": f"{total.get('value')} {total.get('currency_code')}" if total else None,
            }
            self.db.update_case(case_id, duplicate_json=json.dumps(evidence))
            title = ("Duplicate refund request returned the SAME Refund ID — only one refund"
                     if evidence["same_refund"] else "Duplicate refund request returned a DIFFERENT refund ID")
            self.db.audit(case_id, "paypal", title, evidence)
            return evidence

    def decline(self, case_id: str, approver: str = "merchant") -> None:
        with self._lock(case_id):
            case = self._case(case_id)
            if case["status"] != PENDING_APPROVAL:
                raise RefundNotAllowed(f"Case {case_id} is not awaiting approval.")
            self.db.update_case(case_id, human_decision="DECLINED", human_at=self._now(),
                                approval_source=HUMAN, status=DECLINED)
            self.db.audit(case_id, "human", "Human declined — Refund API not called", {"approver": approver})

    def _guard_refund(self, case: dict) -> None:
        if case["decision"] != "ELIGIBLE":
            raise RefundNotAllowed(f"Policy decision is {case['decision'] or 'missing'}; refund refused.")
        if case["human_decision"] != "APPROVED":
            raise RefundNotAllowed("An approval is required before any refund.")
        if not case["capture_id"]:
            raise RefundNotAllowed("No PayPal capture to refund.")
        # The row alone is not enough: the decision and the approval must also be on the case's hash
        # chain, and the chain must verify. A direct UPDATE of the cases table (no chain entry) is refused.
        # The approval may be a person's or, when the merchant enabled autonomy, the policy's own
        # (approval_source "human" / "auto"); either way it has to be a chained entry.
        chain = self.db.verify_chain(case["id"])
        if not chain["ok"]:
            raise RefundNotAllowed(f"Audit trail BROKEN at entry {chain['broken_at']}; refund refused.")
        chained = self.db.chained_case_state(case["id"])
        if chained.get("decision") != "ELIGIBLE" or chained.get("human_decision") != "APPROVED":
            raise RefundNotAllowed("No policy ELIGIBLE + chained APPROVED entry on the audit chain; refund refused.")
        if chained.get("capture_id") != case["capture_id"]:
            raise RefundNotAllowed("Capture on the audit chain differs from the case record; refund refused.")

    @staticmethod
    def _request_id(case: dict) -> str:
        return case.get("refund_request_id") or f"tradeos-refund-{case['id']}"

    def execute_refund(self, case_id: str) -> dict:
        """Retry entry point after REFUND_ERROR / REFUND_OUTCOME_UNKNOWN (same guard, same lock,
        same PayPal-Request-Id)."""
        try:
            with self._money_op(), self._lock(case_id):
                return self._execute_refund(case_id)
        finally:
            self._after_money(case_id)

    def retry_failed_refund(self, case_id: str) -> dict:
        """REFUND_FAILED: re-sending the same PayPal-Request-Id would only return the same FAILED refund.
        A new request id is used only when (1) PayPal confirms (GET) that refund is FAILED, (2) the policy
        engine re-checks the case against a fresh GET of the capture, and (3) the human approval is still
        on record (chain). The new id is derived from the failed refund id, so double clicks are idempotent."""
        try:
            with self._money_op(), self._lock(case_id):
                case = self._case(case_id)
                if case["status"] != REFUND_FAILED or not case.get("refund_id"):
                    raise RefundNotAllowed("Only a refund that PayPal reported FAILED can be retried with a new request.")
                self._guard_refund(case)
                refund = self._pp(case_id, "get_refund", case["refund_id"], timeout=RECONCILE_READ_TIMEOUT)
                if refund.get("status") != "FAILED":
                    raise RefundNotAllowed(f"PayPal reports refund {case['refund_id']} as {refund.get('status')}, "
                                           "not FAILED; no new refund request was sent.")
                capture = self._pp(case_id, "get_capture", case["capture_id"], timeout=RECONCILE_READ_TIMEOUT)
                from .intent import IntentResult
                product = self.db.get_product(case["product_sku"])
                result = self._evaluate(case, product, IntentResult.model_validate(case["intent"]), capture,
                                        supplier_status=case.get("supplier_reply"), require_supplier=True)
                self.db.audit(case_id, "policy", f"Policy re-check before a new refund request: {result.decision}",
                              result.to_dict())
                if not result.eligible:
                    raise RefundNotAllowed("Policy re-check failed; no new refund request was sent.")
                new_id = f"tradeos-refund-{case_id}-after-{case['refund_id']}"
                self.db.update_case(case_id, refund_request_id=new_id)
                self.db.audit(case_id, "paypal", "PayPal confirmed the refund FAILED — retrying with a NEW "
                              "PayPal-Request-Id (policy re-checked, human approval on record)",
                              {"failed_refund_id": case["refund_id"], "paypal_request_id": new_id})
                return self._execute_refund(case_id, after_failed=True)
        finally:
            self._after_money(case_id)

    def _execute_refund(self, case_id: str, after_failed: bool = False) -> dict:
        """The only code path that moves money. Refuses unless policy ELIGIBLE AND human APPROVED.

        Amount (full capture), capture ID and permission all come from the backend; nothing
        from the customer message or the model reaches this call except the grounded,
        validated note_to_payer text.
        """
        case = self._case(case_id)
        self._guard_refund(case)
        if case["refund_status"] in ("COMPLETED", "PENDING"):
            return case["refund"] or {}
        if case["refund_status"] == "FAILED" and not after_failed:
            raise RefundNotAllowed("PayPal reported this refund FAILED; the same PayPal-Request-Id would only "
                                   "return it again. Use 'Retry with a new request' (re-checks policy).")

        request_id = self._request_id(case)  # idempotent: double clicks return the same refund
        if not case.get("refund_request_id"):
            self.db.update_case(case_id, refund_request_id=request_id)
        note_text = self._payer_note(case_id)
        fault = case.get("refund_fault")
        kwargs = {"note_to_payer": note_text}
        if fault:
            kwargs["mock_response"] = fault
            self.db.audit(case_id, "paypal", "Failure test: PayPal sandbox asked to fail this refund attempt",
                          {"PayPal-Mock-Response": {"mock_application_codes": fault}})
        try:
            refund = self._pp(case_id, "refund_capture", case["capture_id"], request_id, **kwargs)
        except PayPalError as exc:
            if exc.status_code is None or exc.status_code >= 500:
                # Outcome UNKNOWN (timeout / network / 5xx): PayPal may have refunded anyway, so the UI must
                # not say "no money moved". A bounded GET check runs next (outside the lock); if PayPal shows
                # the capture refunded, the same PayPal-Request-Id is re-sent once to recover the refund.
                self.db.update_case(case_id, status=REFUND_UNKNOWN, error=str(exc), refund_fault=None)
                self.db.audit(case_id, "paypal", "Refund outcome UNKNOWN — no reply from PayPal; checking",
                              {**exc.to_dict(), "paypal_request_id": request_id})
                self._needs_check.add(case_id)
            else:
                # PayPal answered with an error: it confirmed this request made no refund.
                # The fault is injected exactly once, so "Retry" exercises a real recovery.
                self.db.update_case(case_id, status=REFUND_ERROR, error=str(exc), refund_fault=None)
                self.db.audit(case_id, "paypal", "Refund failed", {**exc.to_dict(), "paypal_request_id": request_id})
                self._write_note(case_id, "FAILURE_NOTE", None, case.get("assist"))
            raise
        self._record_refund(case_id, refund, request_id, via="refund_api")
        return refund

    def recover_unknown_refund(self, case_id: str, trigger: str) -> bool:
        """REFUND_OUTCOME_UNKNOWN and PayPal shows the capture refunded: re-send the SAME request
        (same PayPal-Request-Id, same body) once. PayPal returns the refund it already made, which is then
        recorded through _record_refund. Same guard as any refund (policy + chained human approval)."""
        with self._locks_guard:
            if case_id in self._pending_recovery:
                return False
            self._pending_recovery.add(case_id)
        try:
            with self._money_op(), self._lock(case_id):
                case = self._case(case_id)
                if case["status"] != REFUND_UNKNOWN or case.get("refund_id"):
                    return False
                self._guard_refund(case)
                request_id = self._request_id(case)
                note = (case.get("payer_note") or {}).get("text")
                try:
                    refund = self._pp(case_id, "refund_capture", case["capture_id"], request_id, note_to_payer=note)
                except PayPalError as exc:
                    self.db.audit(case_id, "paypal", "Could not recover the refund from PayPal — outcome still "
                                  "UNKNOWN, needs a human", {**exc.to_dict(), "trigger": trigger})
                    return False
                self.db.audit(case_id, "paypal", f"Recovered the refund from PayPal ({trigger}): same "
                              "PayPal-Request-Id re-sent once, PayPal returned the refund it had already made",
                              {"refund_id": refund.get("id"), "status": refund.get("status"),
                               "paypal_request_id": request_id})
                self._record_refund(case_id, refund, request_id, via="recovery")
                return True
        finally:
            with self._locks_guard:
                self._pending_recovery.discard(case_id)

    # ------------------------------------------------------------------ unknown refund outcome
    def refund_check_pending(self, case_id: str) -> bool:
        with self._locks_guard:
            return self._refund_checks.get(case_id) == "CHECKING"

    def _start_refund_check(self, case_id: str) -> None:
        with self._locks_guard:
            if self._refund_checks.get(case_id) == "CHECKING":
                return
            self._refund_checks.pop(case_id, None)
            self._refund_checks[case_id] = "CHECKING"
            while len(self._refund_checks) > MAX_TRACKED_CASES:
                self._refund_checks.pop(next(iter(self._refund_checks)))
        if self.settings.reconcile_in_background:
            threading.Thread(target=self._refund_check, args=(case_id,), daemon=True).start()
        else:
            self._refund_check(case_id)

    def _refund_check(self, case_id: str) -> None:
        """Bounded GET of the capture (short timeout). Read-only; never calls the Refund API."""
        result = "UNKNOWN"
        try:
            case = self._case(case_id)
            capture = self._pp(case_id, "get_capture", case["capture_id"], timeout=RECONCILE_READ_TIMEOUT)
            status = capture.get("status")
            if status in ("REFUNDED", "PARTIALLY_REFUNDED"):
                result = "REFUNDED_AT_PAYPAL"
                title = (f"Checked with PayPal after the unanswered refund call: capture is {status} — the "
                         "request went through. Recovering the refund with the same PayPal-Request-Id.")
            else:
                result = "NOT_REFUNDED"
                title = (f"Checked with PayPal after the unanswered refund call: capture is {status}, no refund "
                         "seen yet. Retry is safe: it reuses the same PayPal-Request-Id.")
            self.db.audit(case_id, "paypal", title, {"capture_status": status, "seq": next_seq()})
            if result == "REFUNDED_AT_PAYPAL" and case["status"] == REFUND_UNKNOWN:
                with self._locks_guard:
                    self._refund_checks[case_id] = result  # lets the recovery (and a retry) through
                self.recover_unknown_refund(case_id, "after the GET check")
        except Exception as exc:  # PayPal down / timeout: retry stays safe (same PayPal-Request-Id)
            self.db.audit(case_id, "paypal", "Could not check with PayPal after the failed refund call — retry "
                          "still uses the same PayPal-Request-Id", {"error": type(exc).__name__, "seq": next_seq()})
        finally:
            with self._locks_guard:
                self._refund_checks[case_id] = result

    def resume_unresolved_refunds(self) -> int:
        """Startup with a kept database: reconcile every refund still PENDING or with an UNKNOWN outcome
        (archived cases included, so a reset never strands an in-flight refund)."""
        n = 0
        for case in self.db.list_cases(include_archived=True):
            if case.get("refund_status") == "PENDING" or case["status"] == REFUND_UNKNOWN:
                n += self.auto_reconcile(case["id"], background=self.settings.reconcile_in_background)
        return n

    def retry_policy_check(self, case_id: str) -> None:
        """ERROR after the payment was captured (PayPal GET failed during the policy step): run the
        intent + policy step again. Nothing here can refund; approval is still required afterwards."""
        with self._lock(case_id):
            case = self._case(case_id)
            if case["status"] != ERROR or not case.get("capture_id") or case.get("decision"):
                raise RefundNotAllowed("Only a captured case that failed before the policy decision can be re-checked.")
            self.db.update_case(case_id, status=NEW, error=None)
            self.db.audit(case_id, "policy", "Retrying the policy check (PayPal could not be read last time)", {})
        self._after_capture(case_id)

    def refresh_refund(self, case_id: str) -> None:
        """Manual 'Refresh status' button: a full reconciliation against PayPal."""
        self.reconcile(case_id)

    # ------------------------------------------------------------------ reconciliation
    def _already_refunded(self, case: dict, capture: dict) -> Decimal:
        """What PayPal says was already refunded on this capture (feeds the policy engine).

        GET capture has no refunded-total field, so: REFUNDED -> the whole captured amount;
        PARTIALLY_REFUNDED -> total_refunded_amount from our refund if we have one, otherwise the
        whole capture (fail closed, and the case says why: partial refund, amount unknown,
        needs a human); anything else -> 0.
        """
        status = capture.get("status")
        captured = Decimal((capture.get("amount") or {}).get("value") or "0")
        if status == "REFUNDED":
            return captured
        if status == "PARTIALLY_REFUNDED":
            total = ((case.get("refund") or {}).get("seller_payable_breakdown") or {}).get("total_refunded_amount")
            if total and total.get("value"):
                return Decimal(total["value"])
            if case.get("id"):
                self.db.audit(case["id"], "policy", "PayPal reports the capture PARTIALLY_REFUNDED by another refund "
                              "— amount unknown here, treated as not refundable; needs a human",
                              {"capture_status": status})
            return captured
        return Decimal("0")

    def reconcile(self, case_id: str, timeout: float | None = None) -> dict | None:
        """Compare local state with PayPal (GET capture + GET refund). Read-only towards PayPal.

        - Never calls the Refund API; never holds the case lock while waiting on PayPal
          (reads first with a short timeout, then lock -> compare -> write).
        - Only state change: refund PENDING -> COMPLETED when PayPal's GET says COMPLETED, via _record_refund.
        - Never downgrades and never overwrites local fields on a mismatch; mismatches are flagged.
        - PayPal unreachable: recorded, no state change.
        """
        case = self._case(case_id)
        if not case.get("capture_id"):
            return None
        timeout = RECONCILE_READ_TIMEOUT if timeout is None else timeout
        refund_id = case.get("refund_id")
        try:
            capture = self._pp(case_id, "get_capture", case["capture_id"], timeout=timeout)
            refund = self._pp(case_id, "get_refund", refund_id, timeout=timeout) if refund_id else None
        except PayPalError as exc:
            detail = {"error": str(exc), "debug_id": exc.debug_id or None, "seq": next_seq()}
            self.db.audit(case_id, "reconcile", "Reconciliation skipped — PayPal unreachable/error (no change)", detail)
            return {"ok": False, **detail}
        if (case["status"] == REFUND_UNKNOWN and not refund_id
                and capture.get("status") in ("REFUNDED", "PARTIALLY_REFUNDED")):
            # The unanswered refund call went through at PayPal: recover it (same request id), then compare.
            self.db.audit(case_id, "reconcile", f"Reconcile: PayPal shows the capture {capture.get('status')} "
                          "while the refund outcome is UNKNOWN — recovering it", {"seq": next_seq()})
            if self.recover_unknown_refund(case_id, "reconcile"):
                return self.reconcile(case_id, timeout)
        with self._lock(case_id):
            case = self._case(case_id)  # state may have moved (webhook) while we waited on PayPal
            checks, advanced, needs_human = [], False, None
            cap_status = capture.get("status")
            local_refund = case.get("refund_status")
            if not case.get("refund_id"):
                expected = {"COMPLETED"}
            elif local_refund == "COMPLETED":
                expected = {"REFUNDED", "PARTIALLY_REFUNDED"}
            else:
                expected = {"COMPLETED", "REFUNDED", "PARTIALLY_REFUNDED"}
            checks.append({"field": "capture.status", "local": "/".join(sorted(expected)), "paypal": cap_status,
                           "match": cap_status in expected})
            if capture.get("id") not in (None, case["capture_id"]):
                checks.append({"field": "capture.id", "local": case["capture_id"], "paypal": capture.get("id"),
                               "match": False})
            if refund is not None and refund.get("id") not in (None, refund_id):
                checks.append({"field": "refund.id", "local": refund_id, "paypal": refund.get("id"), "match": False})
                refund = None  # never apply a status that belongs to another refund
            up = [l.get("href", "") for l in (refund or {}).get("links") or [] if l.get("rel") == "up"]
            if up and not any(h.rstrip("/").endswith("/captures/" + case["capture_id"]) for h in up):
                checks.append({"field": "refund.capture", "local": case["capture_id"], "paypal": up[0], "match": False})
                refund = None
            if refund is not None and case.get("refund_id") == refund_id:
                pp_status = refund.get("status")
                local_after = local_refund
                if local_refund == "PENDING" and pp_status == "COMPLETED":
                    self._record_refund(case_id, {**(case.get("refund") or {}), **refund}, None, via="reconcile")
                    advanced, local_after = True, "COMPLETED"
                if pp_status in ("CANCELLED", "FAILED") and local_refund != pp_status:
                    needs_human = f"PayPal reports the refund {pp_status}"
                checks.append({"field": "refund.status", "local": local_refund, "paypal": pp_status,
                               "match": local_after == pp_status, "advanced": advanced})
                pp_amt = refund.get("amount") or {}
                checks.append({"field": "refund.amount", "local": f"{case['amount']} {case['currency']}",
                               "paypal": " ".join(str(pp_amt.get(k, "?")) for k in ("value", "currency_code")),
                               "match": _same_money(pp_amt, case["amount"], case["currency"])})
            ok = all(c["match"] for c in checks)
            if ok:
                title = ("Reconciled with PayPal — refund PENDING → COMPLETED (from PayPal GET)" if advanced
                         else "Reconciled with PayPal — all match")
                self.db.update_case(case_id, capture_status=cap_status)  # only written when it agrees
            elif needs_human:
                title = f"Reconciliation MISMATCH — needs a human: {needs_human} (no automatic change)"
            else:
                title = "Reconciliation MISMATCH — local state differs from PayPal (no automatic change)"
            self.db.audit(case_id, "reconcile", title, {"checks": checks, "ok": ok, "needs_human": needs_human,
                                                         "seq": next_seq()})
            return {"ok": ok, "checks": checks, "advanced": advanced, "needs_human": needs_human}

    def auto_reconcile(self, case_id: str, background: bool = True) -> bool:
        """Case-view trigger, deliberately narrow: only refunds still PENDING locally, at most once
        per case per RECONCILE_MIN_INTERVAL seconds, in a background thread with short read timeouts
        so neither the page nor a webhook ever waits on PayPal. Everything else is button-only."""
        case = self.db.get_case(case_id)
        if (not case or self.paypal_mode == "unconfigured"
                or not (case.get("refund_status") == "PENDING" or case["status"] == REFUND_UNKNOWN)):
            return False
        now = time.monotonic()
        with self._locks_guard:
            if now - self._reconciled.get(case_id, -1e9) < RECONCILE_MIN_INTERVAL:
                return False
            self._reconciled.pop(case_id, None)
            self._reconciled[case_id] = now
            while len(self._reconciled) > MAX_TRACKED_CASES:  # bounded: drop the oldest entry
                self._reconciled.pop(next(iter(self._reconciled)))
        run = lambda: self._safe_reconcile(case_id)  # noqa: E731
        if background:
            threading.Thread(target=run, daemon=True).start()
        else:
            run()
        return True

    def _safe_reconcile(self, case_id: str) -> None:
        try:
            self.reconcile(case_id)
        except Exception as exc:  # never let a background check break anything
            self.db.audit(case_id, "reconcile", "Reconciliation skipped — unexpected error (no change)",
                          {"error": type(exc).__name__, "seq": next_seq()})

    # ------------------------------------------------------------------ webhook
    def transmission_age(self, transmission_time: str | None) -> str:
        """'fresh', 'stale' (older than the window), 'future' (beyond allowed clock skew) or 'unknown'."""
        if not transmission_time:
            return "unknown"
        try:
            sent = datetime.fromisoformat(transmission_time.replace("Z", "+00:00"))
            if sent.tzinfo is None:
                sent = sent.replace(tzinfo=timezone.utc)
        except ValueError:
            return "stale"  # unparseable: treat as untrusted-old
        age = (datetime.now(timezone.utc) - sent).total_seconds()
        if age < -self.settings.webhook_max_future_skew_s:
            return "future"
        return "stale" if age > self.settings.webhook_max_age_s else "fresh"

    def record_webhook(self, event: dict, verification: str, method: str = "postback",
                       transmission_time: str | None = None) -> str | None:
        """Signed PayPal webhook. Returns the matched case id.

        Refund events (resource = refund): PAYMENT.CAPTURE.REFUNDED, PAYMENT.REFUND.PENDING,
        PAYMENT.REFUND.FAILED. Capture events (resource = capture): PAYMENT.CAPTURE.REVERSED,
        PAYMENT.CAPTURE.DECLINED -> logged as a warning for a human, never a state change.

        Trust rules:
        - Only a VERIFIED event can change anything. Unverified deliveries are logged only.
        - A verified event id is processed once (persisted in webhook_events); retries are no-ops.
        - Refund events must carry this case's own refund id; otherwise logged, no state change.
        - Replay window on paypal-transmission-time (signed, so it cannot be altered). PayPal's docs do
          not say whether its retries (up to 25 over 3 days) carry a new transmission time, so an old
          time alone is not proof of a replay and must not lose a legitimate late delivery:
            * future-dated beyond the skew, or old AND event id already processed -> "stale/replay
              rejected": logged, no state change, 200 (a non-2xx would only make PayPal resend it);
            * old but never seen -> accepted as a late delivery, but its payload is NOT trusted for a
              state change: TradeOS re-reads the refund from PayPal (GET) and only that result counts.
        - Allowed state changes, all through _record_refund: PENDING -> COMPLETED; PENDING -> PENDING
          (new reason, e.g. ECHECK); PENDING -> FAILED (needs a human). COMPLETED is never
          downgraded, and nothing here ever calls the Refund API.
        """
        resource = event.get("resource") or {}
        etype = event.get("event_type")
        res_id = resource.get("id")
        res_status = resource.get("status")
        event_id = event.get("id")
        verified = verification == "SUCCESS"
        capture_event = etype in CAPTURE_WARNING_EVENTS
        case = None
        if res_id:
            case = self.db.find_case_by("capture_id" if capture_event else "refund_id", res_id)
        if case is None:  # refund-shaped resources (incl. PAYMENT.CAPTURE.REVERSED) link "up" to the capture
            for link in resource.get("links") or []:
                if link.get("rel") == "up" and "/captures/" in (link.get("href") or ""):
                    case = self.db.find_case_by("capture_id", link["href"].rstrip("/").split("/")[-1])
                    break
        log = dict(event_id=event_id, event_type=etype, verification=verification, verified=verified,
                   resource_id=res_id, resource_status=res_status, verify_method=method)
        info = {"event_id": event_id, "event_type": etype, "resource_id": res_id, "resource_status": res_status,
                "status_details": resource.get("status_details"), "verification": verification,
                "verify_method": method, "received_at": self._now(), "create_time": event.get("create_time")}
        if case is None:
            self.db.log_webhook_event(case_id=None, outcome="UNMATCHED", **log)
            return None
        case_id = case["id"]
        age = self.transmission_age(transmission_time)
        if age == "unknown" and self.paypal_mode != "mock":
            age = "stale"  # fail closed: no signed transmission time -> payload never trusted directly
        info["transmission_time"], info["transmission_age"] = transmission_time, age
        if (verified and age == "stale" and event_id and not self.db.webhook_event_seen(event_id)
                and self._webhook_would_change_state(self._case(case_id), etype, resource)):
            return self._late_event_recheck(case_id, etype, transmission_time, log, info)
        result = self._record_webhook_locked(case_id, etype, resource, event_id, verified, age,
                                             transmission_time, log, info)
        if case_id in self._pending_recovery_requests:
            self._pending_recovery_requests.discard(case_id)
            self.recover_unknown_refund(case_id, "verified PayPal webhook")
        return result

    def _record_webhook_locked(self, case_id, etype, resource, event_id, verified, age, transmission_time,
                               log, info) -> str:
        with self._lock(case_id):
            case = self._case(case_id)
            if verified and (age == "future" or (age == "stale" and event_id and self.db.webhook_event_seen(event_id))):
                self.db.log_webhook_event(case_id=case_id, outcome="STALE_REPLAY_REJECTED", **{**log, "verified": False})
                self.db.audit(case_id, "webhook", f"PayPal webhook {etype} rejected as stale/replay "
                              f"(transmission time {transmission_time}) — no state change", info)
                return case_id
            if not verified:
                # Log only: an unverified POST (anyone can hit the public URL) never changes what the case shows.
                self.db.log_webhook_event(case_id=case_id, outcome="UNVERIFIED_IGNORED", **log)
                self.db.audit(case_id, "webhook", f"PayPal webhook {etype} received but NOT verified — ignored "
                              "(no state change)", info)
                return case_id
            if not event_id or not self.db.log_webhook_event(case_id=case_id, outcome="PROCESSING", **log):
                self.db.log_webhook_event(case_id=case_id, outcome="DUPLICATE_IGNORED", **{**log, "verified": False})
                self.db.audit(case_id, "webhook", "Duplicate PayPal webhook delivery ignored (event already processed)",
                              info)
                return case_id
            try:
                outcome, title = self._apply_webhook(case, etype, resource, info)
                self.db.set_webhook_outcome(event_id, outcome)
                self.db.audit(case_id, "webhook", title, info)
                return case_id
            except Exception:
                # Failed midway: release the claim so PayPal's retry of this event is processed, not
                # discarded as a duplicate. Logged as FAILED for the record.
                self.db.release_webhook_event(event_id)
                self.db.log_webhook_event(case_id=case_id, outcome="FAILED_WILL_RETRY", **{**log, "verified": False})
                raise

    def _late_event_recheck(self, case_id: str, etype: str, transmission_time: str | None, log: dict,
                            info: dict) -> str:
        """Old (outside the window), never-seen, would-change-state event. The body is NOT trusted:
        PayPal's GET decides via reconcile() (own capture/refund ids, re-check under the lock, only
        PENDING -> COMPLETED). The event id is claimed only after a successful GET; if PayPal can't
        be reached, nothing changes, the id stays unclaimed and we raise so the endpoint answers 500
        and PayPal's retry can be processed later."""
        result = self.reconcile(case_id, timeout=RECONCILE_READ_TIMEOUT)
        if not result or not result.get("checks"):
            self.db.log_webhook_event(case_id=case_id, outcome="STALE_GET_FAILED_WILL_RETRY", **{**log, "verified": False})
            self.db.audit(case_id, "webhook", f"Late PayPal webhook {etype}: could not re-check with PayPal — "
                          "no change, not acknowledged (PayPal will retry)", info)
            raise PayPalError("late webhook re-check failed")
        if not self.db.log_webhook_event(case_id=case_id, outcome="STALE_GET_CHECK", **log):
            self.db.log_webhook_event(case_id=case_id, outcome="DUPLICATE_IGNORED", **{**log, "verified": False})
            return case_id
        self.db.audit(case_id, "webhook", f"Late PayPal webhook {etype} (sent {transmission_time}) — payload not "
                      "trusted for a state change; refund re-read from PayPal instead", info)
        return case_id

    @staticmethod
    def _webhook_would_change_state(case: dict, etype: str, resource: dict) -> bool:
        return (etype not in CAPTURE_WARNING_EVENTS and case.get("refund_status") == "PENDING"
                and case.get("refund_id") == resource.get("id")
                and resource.get("status") in ("COMPLETED", "PENDING", "FAILED"))

    def _apply_webhook(self, case: dict, etype: str, resource: dict, info: dict) -> tuple[str, str]:
        """Verified, first delivery, case lock held. Returns (outcome, audit title)."""
        case_id = case["id"]
        res_status = resource.get("status")
        if etype in CAPTURE_WARNING_EVENTS:
            # DECLINED carries the capture; REVERSED carries a refund-shaped resource (PayPal's own reversal).
            return ("WARNING_NEEDS_HUMAN",
                    f"Verified PayPal webhook {etype}: {resource.get('id')} is {res_status} — "
                    "needs a human (no automatic change)")
        if (case["status"] == REFUND_UNKNOWN and not case.get("refund_id")
                and etype in ("PAYMENT.CAPTURE.REFUNDED", "PAYMENT.REFUND.PENDING")):
            # Matched via the refund's "up" link to this case's own capture. The payload is not applied;
            # TradeOS re-sends its own request id once and records what PayPal returns.
            self._pending_recovery_requests.add(case_id)
            return ("UNKNOWN_RECOVERY", f"Verified PayPal webhook {etype} for this case's capture while the refund "
                    "outcome is UNKNOWN — recovering the refund from PayPal (same PayPal-Request-Id)")
        if not case.get("refund_id") or case["refund_id"] != resource.get("id"):
            return ("MISMATCH_IGNORED", "Verified PayPal webhook does not match this case's refund id "
                    "— logged, no state change")
        local = case.get("refund_status")
        merged = {**(case.get("refund") or {}), **resource}
        if res_status == "COMPLETED":
            if local == "PENDING":
                self._record_refund(case_id, merged, None, via="webhook")
                self._confirm_webhook(case_id, info)
                return "PENDING_TO_COMPLETED", "Verified PayPal webhook moved refund PENDING → COMPLETED"
            if local == "COMPLETED":
                self._confirm_webhook(case_id, info)
                return ("CONFIRMED", f"PayPal webhook {etype} received — signature verified (second confirmation)")
            return ("NEEDS_HUMAN", f"Verified PayPal webhook says COMPLETED but TradeOS has {local} — needs a human "
                    "(no automatic change)")
        if local == "COMPLETED":
            return ("NO_CHANGE", f"Verified PayPal webhook reports refund {res_status} after COMPLETED — "
                    "not downgraded; needs a human if it persists")
        if res_status == "PENDING" and local == "PENDING":
            self._record_refund(case_id, merged, None)  # stays PENDING; records the reason (e.g. ECHECK)
            reason = (resource.get("status_details") or {}).get("reason")
            return "PENDING_CONFIRMED", f"Verified PayPal webhook: refund still PENDING{f' ({reason})' if reason else ''}"
        if res_status == "FAILED" and local == "PENDING":
            self._record_refund(case_id, merged, None)
            return "PENDING_TO_FAILED", "Verified PayPal webhook: refund FAILED at PayPal — needs a human"
        return "NO_CHANGE", f"Verified PayPal webhook reports refund {res_status} — no state change"

    def _confirm_webhook(self, case_id: str, info: dict) -> None:
        self.db.update_case(case_id, webhook_status="VERIFIED", webhook_json=json.dumps(info))

    def _record_refund(self, case_id: str, refund: dict, request_id: str | None, via: str | None = None) -> None:
        status = refund.get("status")
        case_status = {"COMPLETED": REFUND_COMPLETED, "PENDING": REFUND_PENDING}.get(status, REFUND_FAILED)
        extra = {"completed_via": via} if status == "COMPLETED" and via else {}
        self.db.update_case(case_id, refund_id=refund.get("id"), refund_status=status,
                            refund_json=json.dumps(refund), status=case_status, error=None, **extra)
        self.db.audit(case_id, "paypal", f"PayPal refund {status}",
                      {"refund_id": refund.get("id"), "status": status, "amount": refund.get("amount"),
                       "create_time": refund.get("create_time"), "paypal_request_id": request_id,
                       "note_to_payer": refund.get("note_to_payer"),
                       "status_details": refund.get("status_details")})
        case = self._case(case_id)
        if (status == "COMPLETED" and case.get("human_decision") == "APPROVED"
                and (case.get("note") or {}).get("outcome") != "COMPLETED_NOTE"):
            # Only now may the customer note say "approved" / "refunded".
            self._write_note(case_id, "COMPLETED_NOTE", None, case.get("assist"))

    @staticmethod
    def _now() -> str:
        from .db import utcnow
        return utcnow()


# Log-only, needs a human. Per PayPal's event-names page: DECLINED's resource is the capture;
# REVERSED's is a refund object (PayPal reversed the capture) linking "up" to the capture.
CAPTURE_WARNING_EVENTS = ("PAYMENT.CAPTURE.REVERSED", "PAYMENT.CAPTURE.DECLINED")
RECONCILE_MIN_INTERVAL = 30.0  # seconds between automatic reconciliations of one case
RECONCILE_READ_TIMEOUT = 5.0   # seconds per PayPal GET during reconciliation (demo must never hang)

# Position of the PayPal-Request-Id argument per client operation (for the evidence log).
_REQUEST_ID_ARG = {"create_order_with_card": 4, "create_order": 4, "capture_order": 1, "refund_capture": 1}


def _last_debug_id(client) -> str | None:
    inner = getattr(client, "_mock_wraps", None) or client  # tests wrap the mock in MagicMock
    value = getattr(inner, "last_debug_id", None)
    try:
        inner.last_debug_id = None  # never attribute one call's debug id to the next call
    except AttributeError:
        pass
    return value if isinstance(value, str) and value else None


def _evidence(operation: str, result: dict) -> dict:
    """Only identifiers and states PayPal returned. No tokens, no payer data."""
    if not isinstance(result, dict):
        return {}
    ev = {"id": result.get("id"), "status": result.get("status"), "status_details": result.get("status_details")}
    if operation in ("create_order_with_card", "capture_order"):
        cap = first_capture(result)
        if cap:
            ev.update(capture_id=cap.get("id"), capture_status=cap.get("status"),
                      capture_status_details=cap.get("status_details"))
    if result.get("amount"):
        ev["amount"] = result["amount"]
    return {k: v for k, v in ev.items() if v}


def _same_money(pp_amount: dict, local_value: str, local_currency: str) -> bool:
    """Decimal value + currency comparison ("49.99" == "49.990"); a missing PayPal amount is not a mismatch."""
    if not pp_amount or pp_amount.get("value") is None:
        return True
    try:
        same_value = Decimal(str(pp_amount["value"])) == Decimal(str(local_value))
    except ArithmeticError:
        return False
    return same_value and (pp_amount.get("currency_code") or local_currency) == local_currency


def clean_message(message: str | None, max_chars: int) -> str:
    """Free text is data: strip control characters, collapse whitespace, hard length cap."""
    keep = "\n\t\u200c\u200d"  # ZWNJ / ZWJ are meaningful (Persian, Indic scripts, emoji sequences)
    text = "".join(ch if (ch.isprintable() or ch in keep) else " " for ch in (message or ""))
    lines = (" ".join(line.split()) for line in text.strip().splitlines())
    text = "\n".join(line for line in lines if line)
    return text[:max_chars]
