"""Per-case hash-chained audit log (tamper-evident, not tamper-proof).

Every audit/decision record (timeline entries: policy result, human decision, refund results; every
PayPal call result; every webhook outcome; reconcile results) gets one entry in `audit_chain`:

    entry_hash = SHA-256( canonical JSON of {case_id, seq, type, ts, payload, prev_hash} )

canonical JSON = sorted keys, no whitespace, UTF-8 (ensure_ascii=False). seq starts at 1 per case,
prev_hash of entry 1 is GENESIS. Entries are append-only in code (no update/delete paths) and SQLite
triggers reject UPDATE/DELETE on the table.

Limit: this detects modification of stored entries by anyone who does not also recompute the chain.
Someone with write access to the database can rewrite the whole chain consistently; that is only
detectable if the head hash was noted somewhere outside the database beforehand.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

GENESIS = "0" * 64
SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_chain (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,
    ts TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL,
    source_table TEXT,
    source_id INTEGER,
    backfilled INTEGER NOT NULL DEFAULT 0,
    UNIQUE (case_id, seq)
);
CREATE TRIGGER IF NOT EXISTS audit_chain_no_update BEFORE UPDATE ON audit_chain
BEGIN SELECT RAISE(ABORT, 'audit_chain is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_chain_no_delete BEFORE DELETE ON audit_chain
BEGIN SELECT RAISE(ABORT, 'audit_chain is append-only'); END;
"""


def normalize(payload: Any) -> Any:
    """JSON round-trip so what we hash is exactly what we can re-read later."""
    return json.loads(json.dumps(payload, default=str))


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def entry_hash(case_id: str, seq: int, type_: str, ts: str, payload: Any, prev_hash: str) -> str:
    return hashlib.sha256(canonical({"case_id": case_id, "seq": seq, "type": type_, "ts": ts,
                                     "payload": payload, "prev_hash": prev_hash})).hexdigest()


def audit_row_payload(row: dict) -> dict:
    return {"stage": row["stage"], "title": row["title"],
            "detail": json.loads(row["detail_json"]) if row.get("detail_json") else None}


def paypal_row_payload(row: dict) -> dict:
    return {"operation": row["operation"], "ok": bool(row["ok"]), "result": row["result"],
            "debug_id": row.get("debug_id"), "request_id": row.get("request_id"),
            "evidence": json.loads(row["evidence_json"]) if row.get("evidence_json") else None}


def webhook_row_payload(row: dict) -> dict:
    return {k: row.get(k) for k in ("event_id", "event_type", "verification", "resource_id", "resource_status",
                                     "outcome", "verify_method")} | {"verified": bool(row.get("verified"))}


SOURCE_PAYLOAD = {"audit_events": audit_row_payload, "paypal_calls": paypal_row_payload}  # immutable sources
