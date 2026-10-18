"""PayPal Disputes, READ-ONLY.

What this module does: mirror a dispute (from a verified CUSTOMER.DISPUTE.* webhook, or from a GET) into the
`disputes` table, link it to a case by capture id, write matched disputes to that case's hash chain, and
compute a recommendation for a human (policy.recommend_dispute).

What it never does: call any Disputes write endpoint (evidence, accept, appeal, offer, message, settle ...),
touch a refund, or change a case's status. The only PayPal calls are
GET /v1/customer/disputes and GET /v1/customer/disputes/{id}. "Humans approve": a person acts in PayPal.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .paypal_client import DISPUTES_READ_SCOPE, PayPalError, is_scope_error
from .policy import DisputeFacts, recommend_dispute

DISPUTE_EVENTS = ("CUSTOMER.DISPUTE.CREATED", "CUSTOMER.DISPUTE.UPDATED", "CUSTOMER.DISPUTE.RESOLVED")
MAX_SYNC = 10
SCOPE_MISSING_MESSAGE = (
    f"This PayPal app cannot read disputes (scope {DISPUTES_READ_SCOPE} is not granted). "
    "Disputes that PayPal pushes by signed webhook are still recorded; fetching from PayPal is unavailable "
    "until the scope is enabled on the app. Nothing else is affected.")


def _s(value: Any, limit: int = 200) -> str | None:
    return str(value)[:limit] if isinstance(value, (str, int)) and str(value) else None


def _money(obj: Any) -> tuple[str | None, str | None]:
    if isinstance(obj, dict) and obj.get("value") is not None:
        return _s(obj.get("value"), 32), _s(obj.get("currency_code"), 8)
    return None, None


def seller_transaction_ids(resource: dict) -> list[str]:
    out = []
    for t in resource.get("disputed_transactions") or []:
        if isinstance(t, dict) and (tid := _s(t.get("seller_transaction_id"), 64)):
            out.append(tid)
    return out


def parse_dispute(resource: Any) -> dict | None:
    """Only the fields we show, each length-capped. None if this is not a dispute object."""
    if not isinstance(resource, dict) or not _s(resource.get("dispute_id"), 64):
        return None
    txs = [t for t in resource.get("disputed_transactions") or [] if isinstance(t, dict)]
    amount, currency = _money(resource.get("dispute_amount"))
    if amount is None and txs:
        amount, currency = _money(txs[0].get("gross_amount"))
    return {"dispute_id": _s(resource.get("dispute_id"), 64), "status": _s(resource.get("status"), 64),
            "dispute_state": _s(resource.get("dispute_state"), 64),
            "life_cycle_stage": _s(resource.get("dispute_life_cycle_stage"), 64),
            "reason": _s(resource.get("reason"), 64), "amount": amount, "currency": currency,
            "due_date": _s(resource.get("seller_response_due_date"), 40),
            "create_time": _s(resource.get("create_time"), 40), "update_time": _s(resource.get("update_time"), 40)}


def _debug_id(client: Any) -> str | None:
    inner = getattr(client, "_mock_wraps", None) or client  # tests wrap the mock in MagicMock
    value = getattr(inner, "last_debug_id", None)
    return value if isinstance(value, str) and value else None


def _to_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _dec(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except InvalidOperation:
        return None


class DisputeService:
    def __init__(self, wf: Any) -> None:
        self.wf, self.db = wf, wf.db

    # -- matching / storing ----------------------------------------------------------------
    def _match(self, resource: dict) -> dict | None:
        for tid in seller_transaction_ids(resource):
            case = self.db.find_case_by("capture_id", tid)
            if case:
                return case
        return None

    def ingest(self, resource: dict, source: str, event_id: str | None = None) -> tuple[str, str | None] | None:
        """Store one dispute. Returns (result, case_id) with result created / updated / stale, or None if
        the resource is not a dispute. A matched, changed dispute is appended to the case's hash chain."""
        rec = parse_dispute(resource)
        if rec is None:
            return None
        case = self._match(resource)
        case_id = case["id"] if case else None
        tids = seller_transaction_ids(resource)
        rec.update(case_id=case_id, capture_id=(case["capture_id"] if case else (tids[0] if tids else None)),
                   source=source, last_event_id=event_id)
        result = self.db.upsert_dispute(rec)
        if case_id and result != "stale":
            self.db.audit(case_id, "dispute", f"PayPal dispute {rec['dispute_id']} {result} ({rec['status']}) — "
                          "read-only record; no action taken",
                          {k: rec[k] for k in ("dispute_id", "status", "dispute_state", "life_cycle_stage", "reason",
                                               "amount", "currency", "due_date", "update_time", "source",
                                               "last_event_id")})
        return result, case_id

    # -- webhook ---------------------------------------------------------------------------
    def record_webhook(self, event: dict, verification: str, method: str = "postback",
                       transmission_time: str | None = None) -> str | None:
        """CUSTOMER.DISPUTE.* delivery. Same trust rules as the refund events: only a VERIFIED event is applied;
        a verified event id is applied once; future-dated or old-and-already-seen deliveries are rejected.
        Nothing here moves money or changes a case."""
        resource = event.get("resource")
        resource = resource if isinstance(resource, dict) else {}
        etype, event_id = str(event.get("event_type") or ""), event.get("id")
        verified = verification == "SUCCESS"
        rec = parse_dispute(resource)
        case = self._match(resource) if rec else None
        case_id = case["id"] if case else None
        log: dict[str, Any] = dict(event_id=event_id, event_type=etype, verification=verification, verified=verified,
                                   resource_id=rec["dispute_id"] if rec else _s(resource.get("id")),
                                   resource_status=rec["status"] if rec else None, verify_method=method)
        info = {"event_id": event_id, "event_type": etype, "dispute_id": log["resource_id"],
                "verification": verification, "verify_method": method, "transmission_time": transmission_time}

        def note(outcome: str, title: str, **over: Any) -> str | None:
            self.db.log_webhook_event(case_id=case_id, outcome=outcome, **{**log, **over})
            if case_id:
                self.db.audit(case_id, "webhook", title, info)
            return case_id

        if not verified:
            return note("UNVERIFIED_IGNORED", f"PayPal webhook {etype} received but NOT verified — ignored "
                        "(no dispute recorded)")
        age = self.wf.transmission_age(transmission_time)
        if age == "unknown" and self.wf.paypal_mode != "mock":
            age = "stale"
        if age == "future" or (age == "stale" and event_id and self.db.webhook_event_seen(event_id)):
            return note("STALE_REPLAY_REJECTED", f"PayPal webhook {etype} rejected as stale/replay "
                        f"(transmission time {transmission_time}) — no dispute change", verified=False)
        if rec is None:
            return note("UNSUPPORTED_PAYLOAD", f"PayPal webhook {etype} had no dispute object — ignored",
                        verified=False)
        if not event_id or not self.db.log_webhook_event(case_id=case_id, outcome="PROCESSING", **log):
            return note("DUPLICATE_IGNORED", "Duplicate PayPal dispute webhook delivery ignored", verified=False)
        try:
            outcome = self.ingest(resource, "webhook", event_id)
            self.db.set_webhook_outcome(event_id, "DISPUTE_" + (outcome[0] if outcome else "IGNORED").upper())
            return case_id
        except Exception:
            self.db.release_webhook_event(event_id)
            self.db.log_webhook_event(case_id=case_id, outcome="FAILED_WILL_RETRY", **{**log, "verified": False})
            raise

    # -- GET (read-only) -------------------------------------------------------------------
    def access(self) -> dict:
        """Does the app hold the read scope? granted / missing / unknown (PayPal reported no scopes) /
        unavailable (no usable PayPal client). One OAuth token request, no dispute call."""
        try:
            client = self.wf.paypal()
            has = client.has_scope(DISPUTES_READ_SCOPE) if hasattr(client, "has_scope") else None
        except PayPalError as exc:
            return {"state": "unavailable", "message": f"PayPal is not reachable or configured: {exc.message}"}
        if has is False:
            return {"state": "missing", "message": SCOPE_MISSING_MESSAGE}
        return {"state": "granted" if has else "unknown",
                "message": "" if has else "PayPal did not report the app's scopes; a fetch will show the real answer."}

    def fetch(self, dispute_id: str) -> dict:
        """GET one dispute and store it. Never raises for PayPal problems; returns {ok, code, message, ...}."""
        client = self.wf.paypal()
        try:
            resource = client.get_dispute(dispute_id)
        except PayPalError as exc:
            self._log_failure(dispute_id, exc)
            if is_scope_error(exc):
                return {"ok": False, "code": "SCOPE_MISSING", "message": SCOPE_MISSING_MESSAGE,
                        "debug_id": exc.debug_id}
            return {"ok": False, "code": "PAYPAL_ERROR", "message": f"PayPal could not return the dispute: "
                    f"{exc.message}", "debug_id": exc.debug_id}
        outcome = self.ingest(resource, "paypal_get")
        if outcome is None:
            return {"ok": False, "code": "NOT_A_DISPUTE", "message": "PayPal's reply was not a dispute object."}
        result, case_id = outcome
        if case_id:
            self.db.log_paypal_call(case_id, "get_dispute", True, json.dumps({"id": dispute_id}),
                                    debug_id=_debug_id(client),
                                    evidence={"id": dispute_id, "status": resource.get("status")})
        return {"ok": True, "code": result.upper(), "dispute_id": dispute_id, "case_id": case_id,
                "message": f"Dispute {dispute_id} {result} (read-only GET)."}

    def _log_failure(self, dispute_id: str, exc: PayPalError) -> None:
        row = self.db.get_dispute(dispute_id)
        if row and row.get("case_id"):
            self.db.log_paypal_call(row["case_id"], "get_dispute", False, str(exc), debug_id=exc.debug_id or None,
                                    evidence={"id": dispute_id, "http_status": exc.status_code,
                                              "name": exc.name or None})

    def sync(self, limit: int = MAX_SYNC) -> dict:
        """GET the dispute list, then GET each of the first `limit` (bounded) and store them."""
        client = self.wf.paypal()
        try:
            listing = client.list_disputes(page_size=limit)
        except PayPalError as exc:
            if is_scope_error(exc):
                return {"ok": False, "code": "SCOPE_MISSING", "message": SCOPE_MISSING_MESSAGE, "fetched": 0}
            return {"ok": False, "code": "PAYPAL_ERROR", "fetched": 0,
                    "message": f"PayPal could not list disputes: {exc.message}"}
        ids = [i.get("dispute_id") for i in (listing.get("items") or []) if isinstance(i, dict) and i.get("dispute_id")]
        done, failed = 0, 0
        for did in ids[:limit]:
            res = self.fetch(str(did))
            done += bool(res["ok"])
            failed += not res["ok"]
        msg = (f"PayPal lists {len(ids)} dispute(s); stored {done}" + (f", {failed} failed" if failed else "")
               + " (read-only GET).") if ids else "PayPal reports no disputes for this app (read-only GET)."
        return {"ok": not failed, "code": "OK" if not failed else "PARTIAL", "message": msg, "fetched": done}

    # -- view model ------------------------------------------------------------------------
    def view(self) -> list[dict]:
        today = self.wf.today()
        rows = []
        for d in self.db.list_disputes():
            case = self.db.get_case(d["case_id"]) if d.get("case_id") else None
            rec = recommend_dispute(DisputeFacts(
                status=d["status"], reason=d["reason"], amount=_dec(d["amount"]), currency=d["currency"],
                due=_to_date(d["due_date"]), today=today, case_matched=case is not None,
                case_refund_status=(case or {}).get("refund_status"),
                case_decision=(case or {}).get("decision"), case_amount=_dec((case or {}).get("amount"))))
            rows.append({**d, "case": case, "recommendation": rec.to_dict()})
        return rows
