"""SQLite storage: products, cases, audit timeline, PayPal call log."""

from __future__ import annotations

import json
import threading
import time
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    sku TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    returnable INTEGER NOT NULL,
    price TEXT NOT NULL,
    supplier TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    scenario TEXT NOT NULL,
    label TEXT,                         -- e.g. "Case A", "Spanish preset", "Free text"
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    customer_message TEXT NOT NULL,
    product_sku TEXT NOT NULL REFERENCES products(sku),
    amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    purchase_date_seeded TEXT,          -- demo-only override (Case B); NULL => use PayPal capture time
    order_id TEXT,
    order_status TEXT,
    capture_id TEXT,
    capture_status TEXT,
    capture_time TEXT,
    approve_url TEXT,
    intent_json TEXT,
    assist_json TEXT,                   -- non-decisional AI assist fields (policy never reads them)
    extraction_json TEXT,               -- extractor provenance / notes
    note_json TEXT,                     -- customer-language note grounded in the actual case state
    payer_note_json TEXT,               -- neutral note sent to PayPal as note_to_payer WITH the refund call
    policy_json TEXT,
    decision TEXT,
    supplier_draft TEXT,
    supplier_reply TEXT,
    human_decision TEXT,
    human_at TEXT,
    refund_id TEXT,
    refund_status TEXT,
    refund_json TEXT,
    refund_fault TEXT,                  -- failure-mode demo: sandbox negative-testing code for ONE attempt
    duplicate_json TEXT,                -- failure-mode demo: duplicate refund request evidence
    webhook_status TEXT,                -- PayPal webhook second confirmation
    webhook_json TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    ts TEXT NOT NULL,
    stage TEXT NOT NULL,
    title TEXT NOT NULL,
    detail_json TEXT
);

CREATE TABLE IF NOT EXISTS paypal_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    operation TEXT NOT NULL,
    ok INTEGER NOT NULL,
    result TEXT,
    debug_id TEXT,                      -- PayPal-Debug-Id (success or failure)
    request_id TEXT,                    -- PayPal-Request-Id we sent (idempotency key), if any
    evidence_json TEXT,                 -- ids / status / status_details / error name (never tokens)
    seq INTEGER                         -- monotonic ordering key shared with webhook_events
);

-- Every PayPal webhook delivery we receive (verified or not, matched or not). A VERIFIED
-- event id is claimed exactly once (partial unique index) so PayPal retries are no-ops.
CREATE TABLE IF NOT EXISTS webhook_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT,
    ts TEXT NOT NULL,
    event_type TEXT,
    verification TEXT NOT NULL,
    verified INTEGER NOT NULL,
    case_id TEXT,
    resource_id TEXT,
    resource_status TEXT,
    outcome TEXT NOT NULL,
    seq INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS webhook_events_verified_once
    ON webhook_events(event_id) WHERE verified = 1;
"""

TABLES = ("webhook_events", "paypal_calls", "audit_events", "cases", "products")
JSON_COLUMNS = ("intent_json", "policy_json", "refund_json", "assist_json", "extraction_json", "note_json",
                "duplicate_json", "webhook_json", "payer_note_json")


_seq_lock = threading.Lock()
_last_seq = 0


def next_seq() -> int:
    """Strictly increasing ordering key (ns wall clock, bumped on ties) so evidence rows from
    different tables sort in true call order, not by 1-second timestamps."""
    global _last_seq
    with _seq_lock:
        _last_seq = max(time.time_ns(), _last_seq + 1)
        return _last_seq


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self, reset: bool = False) -> None:
        with self.connect() as conn:
            if reset:
                for t in TABLES:
                    conn.execute(f"DROP TABLE IF EXISTS {t}")
            conn.executescript(SCHEMA)
            # Lightweight forward migration for a kept database (TRADEOS_RESET_ON_START=0).
            have = {r[1] for r in conn.execute("PRAGMA table_info(cases)")}
            for col in ("label", "assist_json", "extraction_json", "note_json", "refund_fault", "duplicate_json",
                        "webhook_status", "webhook_json", "payer_note_json"):
                if col not in have:
                    conn.execute(f"ALTER TABLE cases ADD COLUMN {col} TEXT")
            have = {r[1] for r in conn.execute("PRAGMA table_info(paypal_calls)")}
            for col in ("debug_id", "request_id", "evidence_json", "seq"):
                if col not in have:
                    conn.execute(f"ALTER TABLE paypal_calls ADD COLUMN {col} TEXT")
            if "seq" not in {r[1] for r in conn.execute("PRAGMA table_info(webhook_events)")}:
                conn.execute("ALTER TABLE webhook_events ADD COLUMN seq INTEGER")

    # -- products ---------------------------------------------------------
    def upsert_product(self, sku: str, name: str, category: str, returnable: bool, price: str, supplier: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?)",
                (sku, name, category, int(returnable), price, supplier),
            )

    def get_product(self, sku: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM products WHERE sku=?", (sku,)).fetchone()
        return dict(row) if row else None

    # -- cases ------------------------------------------------------------
    def insert_case(self, **fields: Any) -> None:
        now = utcnow()
        fields.setdefault("created_at", now)
        fields.setdefault("updated_at", now)
        cols = ",".join(fields)
        marks = ",".join("?" for _ in fields)
        with self.connect() as conn:
            conn.execute(f"INSERT INTO cases ({cols}) VALUES ({marks})", tuple(fields.values()))

    def update_case(self, case_id: str, **fields: Any) -> None:
        fields["updated_at"] = utcnow()
        sets = ",".join(f"{k}=?" for k in fields)
        with self.connect() as conn:
            conn.execute(f"UPDATE cases SET {sets} WHERE id=?", (*fields.values(), case_id))

    def get_case(self, case_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        return _decode_case(row) if row else None

    def list_cases(self, status: str | None = None, scenario: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM cases WHERE 1=1", []
        if status:
            sql += " AND status=?"
            args.append(status)
        if scenario:
            sql += " AND scenario=?"
            args.append(scenario)
        sql += " ORDER BY created_at DESC, rowid DESC"
        with self.connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [_decode_case(r) for r in rows]

    def latest_case(self, scenario: str, label: str | None = None) -> dict | None:
        cases = self.list_cases(scenario=scenario)
        if label is not None:
            cases = [c for c in cases if c.get("label") == label]
        return cases[0] if cases else None

    def find_case_by(self, column: str, value: str) -> dict | None:
        if column not in ("refund_id", "capture_id", "order_id"):
            raise ValueError(column)
        with self.connect() as conn:
            row = conn.execute(f"SELECT * FROM cases WHERE {column}=?", (value,)).fetchone()
        return _decode_case(row) if row else None

    # -- audit ------------------------------------------------------------
    def audit(self, case_id: str, stage: str, title: str, detail: Any = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO audit_events (case_id, ts, stage, title, detail_json) VALUES (?,?,?,?,?)",
                (case_id, utcnow(), stage, title, json.dumps(detail, default=str) if detail is not None else None),
            )

    def timeline(self, case_id: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_events WHERE case_id=? ORDER BY id", (case_id,)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["detail"] = json.loads(d.pop("detail_json")) if d.get("detail_json") else None
            out.append(d)
        return out

    # -- PayPal call log ---------------------------------------------------
    def log_paypal_call(self, case_id: str, operation: str, ok: bool, result: str, debug_id: str | None = None,
                        request_id: str | None = None, evidence: dict | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO paypal_calls (case_id, ts, operation, ok, result, debug_id, request_id, evidence_json, "
                "seq) VALUES (?,?,?,?,?,?,?,?,?)",
                (case_id, utcnow(), operation, int(ok), result, debug_id, request_id,
                 json.dumps(evidence) if evidence is not None else None, next_seq()),
            )

    def paypal_calls(self, case_id: str, operation: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM paypal_calls WHERE case_id=?", [case_id]
        if operation:
            sql += " AND operation=?"
            args.append(operation)
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql + " ORDER BY id", args).fetchall()]

    # -- PayPal webhook log --------------------------------------------------
    def log_webhook_event(self, event_id: str | None, event_type: str | None, verification: str, verified: bool,
                          case_id: str | None, resource_id: str | None, resource_status: str | None,
                          outcome: str) -> bool:
        """Insert one delivery. For verified events returns False if that event id was already
        claimed (duplicate delivery); unverified rows are never deduplicated and never block."""
        with self.connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO webhook_events (event_id, ts, event_type, verification, verified, case_id, "
                    "resource_id, resource_status, outcome, seq) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (event_id, utcnow(), event_type, verification, int(verified), case_id, resource_id,
                     resource_status, outcome, next_seq()))
            except sqlite3.IntegrityError:
                return False
        return True

    def release_webhook_event(self, event_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM webhook_events WHERE event_id=? AND verified=1", (event_id,))

    def set_webhook_outcome(self, row_event_id: str, outcome: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE webhook_events SET outcome=? WHERE event_id=? AND verified=1", (outcome, row_event_id))

    def webhook_events(self, case_id: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM webhook_events", []
        if case_id:
            sql, args = sql + " WHERE case_id=?", [case_id]
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql + " ORDER BY id", args).fetchall()]


def _decode_case(row: sqlite3.Row) -> dict:
    d = dict(row)
    for key in JSON_COLUMNS:
        raw = d.get(key)
        d[key.removesuffix("_json")] = json.loads(raw) if raw else None
    return d
