"""The one TradeOS loop (plan §3):

request -> AI intent -> deterministic policy -> supplier -> human approval -> PayPal refund (or block).
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable

from .config import Settings
from .db import Database
from .intent import IntentExtractor
from .paypal_client import PayPalClient, PayPalError, find_link, first_capture
from .paypal_mock import MockPayPalClient
from .policy import PolicyInput, PolicyResult, evaluate
from .supplier import draft_supplier_message, mock_supplier_reply

DEMO_PRODUCT = {
    "sku": "TRAIL-RUNNER-42",
    "name": "Trail Runner sneakers, EU size 42",
    "category": "footwear",
    "returnable": True,
    "price": "49.99",
    "supplier": "Stride Footwear Co. (fictional demo supplier)",
}
DEMO_MESSAGE = "The shoes are too small. Can I exchange size 42 for size 43?"
SCENARIOS = {
    "A": {"customer_name": "Maria (demo customer)", "seeded_days_ago": None},
    "B": {"customer_name": "Tom (demo customer)", "seeded_days_ago": "case_b"},
}

# Case statuses
NEW = "NEW"
AWAITING_BUYER = "AWAITING_BUYER_APPROVAL"
PENDING_APPROVAL = "PENDING_APPROVAL"
REJECTED = "REJECTED"
DECLINED = "DECLINED_BY_HUMAN"
REFUND_COMPLETED = "REFUND_COMPLETED"
REFUND_PENDING = "REFUND_PENDING"
REFUND_FAILED = "REFUND_FAILED"
REFUND_ERROR = "REFUND_ERROR"
ERROR = "ERROR"


class RefundNotAllowed(Exception):
    """Raised when code refuses to move money. This is the hard guard, independent of the UI."""


class CaseNotFound(Exception):
    pass


class Workflow:
    def __init__(self, db: Database, settings: Settings, extractor: IntentExtractor, paypal: Any = None,
                 today: Callable[[], date] | None = None) -> None:
        self.db = db
        self.settings = settings
        self.extractor = extractor
        self._paypal = paypal
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
        try:
            result = getattr(self.paypal(), operation)(*args, **kwargs)
        except PayPalError as exc:
            self.db.log_paypal_call(case_id, operation, False, str(exc))
            raise
        summary = {k: result.get(k) for k in ("id", "status") if isinstance(result, dict)}
        self.db.log_paypal_call(case_id, operation, True, json.dumps(summary))
        return result

    # ------------------------------------------------------------------ seed
    def seed_demo(self) -> None:
        self.db.upsert_product(**DEMO_PRODUCT)
        for scenario in ("A", "B"):
            self.new_case(scenario)

    def new_case(self, scenario: str) -> str:
        if scenario not in SCENARIOS:
            raise ValueError("unknown scenario")
        spec = SCENARIOS[scenario]
        seeded = None
        if spec["seeded_days_ago"]:
            seeded = (self.today() - timedelta(days=self.settings.case_b_days_since_purchase)).isoformat()
        case_id = f"{scenario}-{uuid.uuid4().hex[:6].upper()}"
        self.db.insert_case(
            id=case_id, scenario=scenario, status=NEW, customer_name=spec["customer_name"],
            customer_message=DEMO_MESSAGE, product_sku=DEMO_PRODUCT["sku"],
            amount=self.settings.order_amount, currency=self.settings.currency, purchase_date_seeded=seeded,
        )
        return case_id

    def _case(self, case_id: str) -> dict:
        case = self.db.get_case(case_id)
        if not case:
            raise CaseNotFound(case_id)
        return case

    # ------------------------------------------------------------------ run
    def run_scenario(self, scenario: str) -> str:
        latest = self.db.latest_case(scenario)
        case_id = latest["id"] if latest and latest["status"] == NEW else self.new_case(scenario)
        self.process(case_id)
        return case_id

    def process(self, case_id: str) -> None:
        case = self._case(case_id)
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
        intent = extraction.result.model_dump()
        self.db.update_case(case_id, intent_json=json.dumps(intent))
        self.db.audit(case_id, "intent", "Intent extracted",
                      {**intent, "extractor": extraction.extractor, "note": extraction.note})

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
            self._reject(case_id, pre)
            return

        # Step 5: supplier draft + clearly labelled mock reply.
        draft = draft_supplier_message(self._case(case_id), product, intent)
        self.db.update_case(case_id, supplier_draft=draft)
        self.db.audit(case_id, "supplier", "Supplier draft generated", {"draft": draft})
        reply = mock_supplier_reply(case)
        self.db.update_case(case_id, supplier_reply=reply["status"])
        self.db.audit(case_id, "supplier", f"Supplier replied: {reply['status']} (MOCK)", reply)

        final = self._evaluate(case, product, extraction.result, capture, supplier_status=reply["status"],
                               require_supplier=True)
        self.db.audit(case_id, "policy", f"Policy final: {final.decision}", final.to_dict())
        if not final.eligible:
            self._reject(case_id, final)
            return
        self.db.update_case(case_id, policy_json=json.dumps(final.to_dict()), decision=final.decision,
                            status=PENDING_APPROVAL)
        self.db.audit(case_id, "human", "Waiting for human approval", {"amount": f"{case['amount']} {case['currency']}"})

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
            already_refunded=Decimal("0"),
            purchase_date=purchase,
            today=self.today(),
            return_window_days=self.settings.return_window_days,
            product_returnable=bool(product["returnable"]),
            product_name=product["name"],
            intent=intent,
            supplier_status=supplier_status,
            require_supplier=require_supplier,
        ))

    def _reject(self, case_id: str, result: PolicyResult) -> None:
        self.db.update_case(case_id, policy_json=json.dumps(result.to_dict()), decision="REJECTED", status=REJECTED)
        self.db.audit(case_id, "paypal", "Refund API NOT CALLED — policy rejected the case",
                      {"reasons": result.reasons, "refund_id": None})

    # ------------------------------------------------------------------ human + money
    def approve(self, case_id: str, approver: str = "merchant") -> None:
        case = self._case(case_id)
        if case["status"] != PENDING_APPROVAL or case["decision"] != "ELIGIBLE":
            raise RefundNotAllowed(f"Case {case_id} is not awaiting approval (status {case['status']}, "
                                   f"policy {case['decision']}).")
        self.db.update_case(case_id, human_decision="APPROVED", human_at=self._now())
        self.db.audit(case_id, "human", "Human approved the refund", {"approver": approver})
        self.execute_refund(case_id)

    def decline(self, case_id: str, approver: str = "merchant") -> None:
        case = self._case(case_id)
        if case["status"] != PENDING_APPROVAL:
            raise RefundNotAllowed(f"Case {case_id} is not awaiting approval.")
        self.db.update_case(case_id, human_decision="DECLINED", human_at=self._now(), status=DECLINED)
        self.db.audit(case_id, "human", "Human declined — Refund API not called", {"approver": approver})

    def execute_refund(self, case_id: str) -> dict:
        """The only code path that moves money. Refuses unless policy ELIGIBLE AND human APPROVED."""
        case = self._case(case_id)
        if case["decision"] != "ELIGIBLE":
            raise RefundNotAllowed(f"Policy decision is {case['decision'] or 'missing'}; refund refused.")
        if case["human_decision"] != "APPROVED":
            raise RefundNotAllowed("Human approval is required before any refund.")
        if not case["capture_id"]:
            raise RefundNotAllowed("No PayPal capture to refund.")
        if case["refund_status"] in ("COMPLETED", "PENDING"):
            return case["refund"] or {}

        request_id = f"tradeos-refund-{case_id}"  # idempotent: double clicks return the same refund
        try:
            refund = self._pp(case_id, "refund_capture", case["capture_id"], request_id)
        except PayPalError as exc:
            self.db.update_case(case_id, status=REFUND_ERROR, error=str(exc))
            self.db.audit(case_id, "paypal", "Refund failed", exc.to_dict())
            raise
        self._record_refund(case_id, refund, request_id)
        return refund

    def refresh_refund(self, case_id: str) -> None:
        case = self._case(case_id)
        if not case["refund_id"]:
            return
        try:
            refund = self._pp(case_id, "get_refund", case["refund_id"])
        except PayPalError as exc:
            self.db.update_case(case_id, error=str(exc))
            self.db.audit(case_id, "paypal", "Refund status refresh failed", exc.to_dict())
            return
        self._record_refund(case_id, refund, None)

    def _record_refund(self, case_id: str, refund: dict, request_id: str | None) -> None:
        status = refund.get("status")
        case_status = {"COMPLETED": REFUND_COMPLETED, "PENDING": REFUND_PENDING}.get(status, REFUND_FAILED)
        self.db.update_case(case_id, refund_id=refund.get("id"), refund_status=status,
                            refund_json=json.dumps(refund), status=case_status, error=None)
        self.db.audit(case_id, "paypal", f"PayPal refund {status}",
                      {"refund_id": refund.get("id"), "status": status, "amount": refund.get("amount"),
                       "create_time": refund.get("create_time"), "paypal_request_id": request_id,
                       "status_details": refund.get("status_details")})

    @staticmethod
    def _now() -> str:
        from .db import utcnow
        return utcnow()
