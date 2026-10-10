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

from . import audit_chain as chain  # noqa: E402

_chain_lock = threading.RLock()  # one writer at a time for chain appends (single-process app)

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
    approval_source TEXT,               -- "human" (a person clicked Approve) / "auto" (the merchant's policy allowed it)
    refund_id TEXT,
    refund_status TEXT,
    refund_json TEXT,
    refund_fault TEXT,                  -- failure-mode demo: sandbox negative-testing code for ONE attempt
    duplicate_json TEXT,                -- failure-mode demo: duplicate refund request evidence
    webhook_status TEXT,                -- PayPal webhook second confirmation
    webhook_json TEXT,
    error TEXT,
    refund_request_id TEXT,             -- PayPal-Request-Id of the current refund attempt (idempotency key)
    completed_via TEXT,                 -- refund_api / webhook / reconcile / recovery: who confirmed COMPLETED
    archived_at TEXT                    -- demo reset archives cases (never DROPs them)
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
    seq INTEGER,
    verify_method TEXT                  -- self (cert + CRC32) / postback (PayPal API) / none
);
CREATE UNIQUE INDEX IF NOT EXISTS webhook_events_verified_once
    ON webhook_events(event_id) WHERE verified = 1;
"""

TABLES = ("audit_chain", "webhook_events", "paypal_calls", "audit_events", "cases", "products")
# Case columns whose every change is appended to the case's hash chain ("case:update" entries).
# The refund gate re-derives decision / human approval from these chained entries, not from the row.
CHAINED_CASE_FIELDS = ("status", "decision", "human_decision", "approval_source", "refund_id", "refund_status",
                       "refund_request_id", "capture_id", "archived_at")
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
        """Create / migrate the schema. reset=True is the demo reset: it ARCHIVES every live case
        (archived_at + a chained 'case:update' entry) instead of dropping tables, so the append-only
        audit chain, the PayPal call log and webhook matching for in-flight refunds all survive."""
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.executescript(chain.SCHEMA)
            # Lightweight forward migration for a kept database (TRADEOS_RESET_ON_START=0).
            have = {r[1] for r in conn.execute("PRAGMA table_info(cases)")}
            for col in ("label", "assist_json", "extraction_json", "note_json", "refund_fault", "duplicate_json",
                        "webhook_status", "webhook_json", "payer_note_json", "refund_request_id", "completed_via",
                        "archived_at", "approval_source"):
                if col not in have:
                    conn.execute(f"ALTER TABLE cases ADD COLUMN {col} TEXT")
            have = {r[1] for r in conn.execute("PRAGMA table_info(paypal_calls)")}
            for col in ("debug_id", "request_id", "evidence_json", "seq"):
                if col not in have:
                    conn.execute(f"ALTER TABLE paypal_calls ADD COLUMN {col} TEXT")
            have_we = {r[1] for r in conn.execute("PRAGMA table_info(webhook_events)")}
            if "seq" not in have_we:
                conn.execute("ALTER TABLE webhook_events ADD COLUMN seq INTEGER")
            if "verify_method" not in have_we:
                conn.execute("ALTER TABLE webhook_events ADD COLUMN verify_method TEXT")
        self._backfill_chain()
        self._backfill_case_state()
        if reset:
            self.archive_all()

    def archive_all(self) -> int:
        now = utcnow()
        ids = [r["id"] for r in self._rows("SELECT id FROM cases WHERE archived_at IS NULL")]
        for case_id in ids:
            self.update_case(case_id, archived_at=now)
        return len(ids)

    def _rows(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql, args).fetchall()]

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
        with _chain_lock, self.connect() as conn:
            conn.execute(f"INSERT INTO cases ({cols}) VALUES ({marks})", tuple(fields.values()))
            self._chain_case(conn, fields["id"], fields, fields["updated_at"])

    def update_case(self, case_id: str, **fields: Any) -> None:
        """Every write of a CHAINED_CASE_FIELDS column is appended to the case's hash chain in the
        same transaction, so a decision / approval / refund state can't change without a chain entry."""
        fields["updated_at"] = utcnow()
        sets = ",".join(f"{k}=?" for k in fields)
        with _chain_lock, self.connect() as conn:
            cur = conn.execute(f"UPDATE cases SET {sets} WHERE id=?", (*fields.values(), case_id))
            if cur.rowcount:
                self._chain_case(conn, case_id, fields, fields["updated_at"])

    def _chain_case(self, conn, case_id: str, fields: dict, ts: str, backfilled: bool = False) -> None:
        changed = {k: fields[k] for k in CHAINED_CASE_FIELDS if k in fields}
        if changed:
            self._chain_append(conn, case_id, "case:update", ts, changed, None, None, backfilled)

    def chained_case_state(self, case_id: str) -> dict:
        """Case state re-derived from the chain alone (fold of its 'case:update' entries)."""
        state: dict = {}
        for e in self.chain_entries(case_id):
            if e["type"] == "case:update":
                state.update(json.loads(e["payload_json"]))
        return state

    def _backfill_case_state(self) -> None:
        """Kept databases from before case state was chained: one backfilled snapshot per case."""
        with _chain_lock, self.connect() as conn:
            have = {r[0] for r in conn.execute("SELECT DISTINCT case_id FROM audit_chain WHERE type='case:update'")}
            for r in conn.execute("SELECT * FROM cases").fetchall():
                if r["id"] not in have:
                    self._chain_case(conn, r["id"], dict(r), r["updated_at"], backfilled=True)

    def get_case(self, case_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        return _decode_case(row) if row else None

    def list_cases(self, status: str | None = None, scenario: str | None = None,
                   include_archived: bool = False) -> list[dict]:
        sql, args = "SELECT * FROM cases WHERE 1=1", []
        if not include_archived:
            sql += " AND archived_at IS NULL"
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
        with _chain_lock, self.connect() as conn:
            ts = utcnow()
            cur = conn.execute(
                "INSERT INTO audit_events (case_id, ts, stage, title, detail_json) VALUES (?,?,?,?,?)",
                (case_id, ts, stage, title, json.dumps(detail, default=str) if detail is not None else None),
            )
            row = dict(conn.execute("SELECT * FROM audit_events WHERE id=?", (cur.lastrowid,)).fetchone())
            self._chain_append(conn, case_id, f"audit:{stage}", ts, chain.audit_row_payload(row),
                               "audit_events", cur.lastrowid)

    # -- hash chain (append-only) ---------------------------------------------
    @staticmethod
    def _chain_append(conn, case_id: str, type_: str, ts: str, payload: Any, source_table: str | None,
                      source_id: int | None, backfilled: bool = False) -> None:
        """Only write path for audit_chain. Caller holds _chain_lock and is inside one transaction
        together with the source row, so the entry and its source commit or roll back together."""
        last = conn.execute("SELECT seq, entry_hash FROM audit_chain WHERE case_id=? ORDER BY seq DESC LIMIT 1",
                            (case_id,)).fetchone()
        seq, prev = (last["seq"] + 1, last["entry_hash"]) if last else (1, chain.GENESIS)
        payload = chain.normalize(payload)
        h = chain.entry_hash(case_id, seq, type_, ts, payload, prev)
        conn.execute("INSERT INTO audit_chain (case_id, seq, type, ts, payload_json, prev_hash, entry_hash, "
                     "source_table, source_id, backfilled) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (case_id, seq, type_, ts, json.dumps(payload, sort_keys=True), prev, h, source_table,
                      source_id, int(backfilled)))

    def _chain_webhook(self, conn, row_id: int, type_: str) -> None:
        row = conn.execute("SELECT * FROM webhook_events WHERE id=?", (row_id,)).fetchone()
        if row is not None and row["case_id"]:
            row = dict(row)
            self._chain_append(conn, row["case_id"], type_, utcnow(), chain.webhook_row_payload(row),
                               "webhook_events", row_id)

    def _backfill_chain(self) -> None:
        """Existing databases: build the chain for cases that have records but no chain yet, in their
        original order, marked backfilled=1 (hashed now, so they prove nothing about earlier edits)."""
        with _chain_lock, self.connect() as conn:
            chained = {r[0] for r in conn.execute("SELECT DISTINCT case_id FROM audit_chain")}
            rows = []
            for r in conn.execute("SELECT * FROM audit_events"):
                rows.append((r["ts"], 0, r["id"], "audit_events", dict(r)))
            for r in conn.execute("SELECT * FROM paypal_calls"):
                rows.append((r["ts"], 1, r["id"], "paypal_calls", dict(r)))
            for r in conn.execute("SELECT * FROM webhook_events WHERE case_id IS NOT NULL"):
                rows.append((r["ts"], 2, r["id"], "webhook_events", dict(r)))
            rows.sort(key=lambda x: (x[0], x[1], x[2]))
            for ts, _, rid, table, row in rows:
                if row["case_id"] in chained:
                    continue
                if table == "audit_events":
                    t_, p_ = f"audit:{row['stage']}", chain.audit_row_payload(row)
                elif table == "paypal_calls":
                    t_, p_ = f"paypal:{row['operation']}", chain.paypal_row_payload(row)
                else:
                    t_, p_ = "webhook:received", chain.webhook_row_payload(row)
                self._chain_append(conn, row["case_id"], t_, ts, p_, table, rid, backfilled=True)

    def chain_entries(self, case_id: str) -> list[dict]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM audit_chain WHERE case_id=? ORDER BY seq",
                                                  (case_id,)).fetchall()]

    def verify_chain(self, case_id: str) -> dict:
        """Recompute every hash; report the first broken link (1-based seq)."""
        entries = self.chain_entries(case_id)
        prev, n_back = chain.GENESIS, 0

        def broken(e, k, reason):
            return {"ok": False, "case_id": case_id, "entries": len(entries), "broken_at": k, "reason": reason,
                    "head": entries[-1]["entry_hash"] if entries else chain.GENESIS, "backfilled": n_back}
        with self.connect() as conn:
            for k, e in enumerate(entries, start=1):
                n_back += e["backfilled"]
                if e["seq"] != k:
                    return broken(e, k, f"sequence gap: expected {k}, found {e['seq']}")
                if e["prev_hash"] != prev:
                    return broken(e, k, "prev_hash does not match the previous entry")
                payload = json.loads(e["payload_json"])
                if chain.entry_hash(case_id, e["seq"], e["type"], e["ts"], payload, e["prev_hash"]) != e["entry_hash"]:
                    return broken(e, k, "entry content does not match its hash")
                src = chain.SOURCE_PAYLOAD.get(e["source_table"] or "")
                if src is not None:
                    row = conn.execute(f"SELECT * FROM {e['source_table']} WHERE id=?", (e["source_id"],)).fetchone()
                    if row is None:
                        return broken(e, k, f"source record {e['source_table']}#{e['source_id']} was deleted")
                    if chain.normalize(src(dict(row))) != payload:
                        return broken(e, k, f"source record {e['source_table']}#{e['source_id']} was modified")
                prev = e["entry_hash"]
            # Coverage: every immutable record of this case must be in the chain. Catches a deleted
            # (truncated) chain entry whose record still exists. If the record was deleted too, only a
            # head hash recorded outside the database reveals it.
            chained = {(e["source_table"], e["source_id"]) for e in entries}
            for table in chain.SOURCE_PAYLOAD:
                for r in conn.execute(f"SELECT id FROM {table} WHERE case_id=? ORDER BY id", (case_id,)):
                    if (table, r["id"]) not in chained:
                        return broken(None, len(entries) + 1, f"record {table}#{r['id']} is missing from the chain")
        return {"ok": True, "case_id": case_id, "entries": len(entries), "broken_at": None, "reason": None,
                "head": prev, "backfilled": n_back}

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
        with _chain_lock, self.connect() as conn:
            ts = utcnow()
            cur = conn.execute(
                "INSERT INTO paypal_calls (case_id, ts, operation, ok, result, debug_id, request_id, evidence_json, "
                "seq) VALUES (?,?,?,?,?,?,?,?,?)",
                (case_id, ts, operation, int(ok), result, debug_id, request_id,
                 json.dumps(evidence) if evidence is not None else None, next_seq()),
            )
            row = dict(conn.execute("SELECT * FROM paypal_calls WHERE id=?", (cur.lastrowid,)).fetchone())
            self._chain_append(conn, case_id, f"paypal:{operation}", ts, chain.paypal_row_payload(row),
                               "paypal_calls", cur.lastrowid)

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
                          outcome: str, verify_method: str | None = None) -> bool:
        """Insert one delivery. For verified events returns False if that event id was already
        claimed (duplicate delivery); unverified rows are never deduplicated and never block."""
        with _chain_lock, self.connect() as conn:
            try:
                cur = conn.execute(
                    "INSERT INTO webhook_events (event_id, ts, event_type, verification, verified, case_id, "
                    "resource_id, resource_status, outcome, seq, verify_method) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (event_id, utcnow(), event_type, verification, int(verified), case_id, resource_id,
                     resource_status, outcome, next_seq(), verify_method))
            except sqlite3.IntegrityError:
                return False
            self._chain_webhook(conn, cur.lastrowid, "webhook:received")
        return True

    def webhook_event_seen(self, event_id: str) -> bool:
        with self.connect() as conn:
            return conn.execute("SELECT 1 FROM webhook_events WHERE event_id=? AND verified=1",
                                (event_id,)).fetchone() is not None

    def release_webhook_event(self, event_id: str) -> None:
        with _chain_lock, self.connect() as conn:
            for r in conn.execute("SELECT id FROM webhook_events WHERE event_id=? AND verified=1", (event_id,)).fetchall():
                self._chain_webhook(conn, r["id"], "webhook:released_for_retry")
            conn.execute("DELETE FROM webhook_events WHERE event_id=? AND verified=1", (event_id,))

    def set_webhook_outcome(self, row_event_id: str, outcome: str) -> None:
        with _chain_lock, self.connect() as conn:
            conn.execute("UPDATE webhook_events SET outcome=? WHERE event_id=? AND verified=1", (outcome, row_event_id))
            for r in conn.execute("SELECT id FROM webhook_events WHERE event_id=? AND verified=1",
                                  (row_event_id,)).fetchall():
                self._chain_webhook(conn, r["id"], "webhook:outcome")

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
