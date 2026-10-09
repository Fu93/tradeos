"""Service + storage for the taxonomy-v3 routing EXPERIMENT. Own tables (routing_v3_*); refund tables untouched.

Statuses: DIRECT_WORKFLOW · SUGGESTED_TASK (awaits a human) · TASK_DRAFT_READY (internal draft, NOT sent) ·
          AWAITING_CUSTOMER (clarifying question shown; reply is SIMULATED in the panel) · HUMAN_REVIEW.
Nothing is ever sent to a customer or a supplier from here.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Iterator

from .intent import looks_like_injection
from .routing_data import MOCK_LABEL
from .routing_v3 import (MAX_CLARIFY_ROUNDS, RULE_VERSION_V3, ContextV3, DecisionV3, ExtractionUnavailable, Translator,
                         _HUMAN_ASK, agreement_gate, clarify_next, decide_v3, detect_lang, render_template)

STATUS_OF = {"DIRECT_WORKFLOW": "DIRECT_WORKFLOW", "CREATE_SUPPLIER_TASK": "SUGGESTED_TASK",
             "CLARIFY_WITH_CUSTOMER": "AWAITING_CUSTOMER", "HUMAN_REVIEW": "HUMAN_REVIEW"}
STATUS_TEXT = {"DIRECT_WORKFLOW": "Existing workflow handles it (refund / return / own stock)",
               "SUGGESTED_TASK": "Suggested supplier task: waiting for a human to confirm",
               "TASK_DRAFT_READY": "Internal supplier draft ready (NOT sent)",
               "AWAITING_CUSTOMER": "Clarifying question ready (simulated, not sent)",
               "HUMAN_REVIEW": "A human reviews it"}

SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS routing_v3_cases (
  id TEXT PRIMARY KEY, created_at TEXT, customer TEXT, linked_order TEXT, message TEXT, lang TEXT,
  status TEXT, action TEXT, rule TEXT, decided_by TEXT, refund_intent INTEGER, decision_json TEXT,
  extraction_json TEXT, rounds_json TEXT, task_json TEXT, is_mock INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS routing_v3_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, at TEXT, event TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS routing_v3_clarify_cache (key TEXT PRIMARY KEY, value_json TEXT, at TEXT);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RoutingV3Store:
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
        with self.connect() as c:
            if reset:
                c.executescript("DROP TABLE IF EXISTS routing_v3_cases; DROP TABLE IF EXISTS routing_v3_log; "
                                "DROP TABLE IF EXISTS routing_v3_clarify_cache;")
            c.executescript(SCHEMA_V3)

    def log(self, cid: str, event: str, detail: str = "") -> None:
        with self.connect() as c:
            c.execute("INSERT INTO routing_v3_log(case_id, at, event, detail) VALUES (?,?,?,?)", (cid, _now(), event, detail))

    def events(self, cid: str) -> list[dict]:
        with self.connect() as c:
            return [dict(r) for r in c.execute("SELECT at, event, detail FROM routing_v3_log WHERE case_id=? ORDER BY id", (cid,))]

    def save(self, row: dict) -> None:
        cols = ["id", "created_at", "customer", "linked_order", "message", "lang", "status", "action", "rule", "decided_by",
                "refund_intent", "decision_json", "extraction_json", "rounds_json", "task_json"]
        with self.connect() as c:
            c.execute(f"INSERT OR REPLACE INTO routing_v3_cases({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                      [row.get(k) for k in cols])

    def get(self, cid: str) -> dict | None:
        with self.connect() as c:
            r = c.execute("SELECT * FROM routing_v3_cases WHERE id=?", (cid,)).fetchone()
        return self._hydrate(r) if r else None

    def recent(self, limit: int = 8) -> list[dict]:
        with self.connect() as c:
            rows = c.execute("SELECT * FROM routing_v3_cases ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
        return [self._hydrate(r) for r in rows]

    def open_task(self, key: str) -> dict | None:
        for case in self.recent(500):
            t = case.get("task")
            if t and t.get("dedup_key") == key and case["status"] in ("SUGGESTED_TASK", "TASK_DRAFT_READY"):
                return {"id": case["id"], **t}
        return None

    def cache(self) -> dict:
        with self.connect() as c:
            return {r["key"]: json.loads(r["value_json"]) for r in c.execute("SELECT * FROM routing_v3_clarify_cache")}

    def put_cache(self, key: str, value: dict) -> None:
        with self.connect() as c:
            c.execute("INSERT OR REPLACE INTO routing_v3_clarify_cache VALUES (?,?,?)", (key, json.dumps(value), _now()))

    @staticmethod
    def _hydrate(r) -> dict:
        d = dict(r)
        for k in ("decision", "extraction", "rounds", "task"):
            raw = d.pop(f"{k}_json", None)
            d[k] = json.loads(raw) if raw else ([] if k == "rounds" else None)
        return d


def draft_task_text(cid: str, task: dict) -> str:
    lines = ["INTERNAL DRAFT — NOT SENT. The supplier has NOT been contacted. (MOCK supplier, experiment)",
             f"To: {task['supplier']}", f"Subject: [{task['family']} / {task['issue_type']}] Order {task['order_id']} — "
                                        f"{task['product']}", "", f"order id: {task['order_id']}", f"product: {task['product']} ({task['sku']})"]
    if task.get("requested_variant"):
        lines.append(f"requested variant: {task['requested_variant']}")
    if task.get("part"):
        lines.append(f"part number: {task['part']}")
    lines += [f"days since purchase: {task['days_since_purchase']}", "",
              f"Why the supplier: {task['why_supplier']}", f"Reference: routing v3 case {cid} · {RULE_VERSION_V3}"]
    return "\n".join(lines)


class RoutingV3Service:
    def __init__(self, store: RoutingV3Store, extractor, today: date | None = None, agreement_k: int = 1,
                 translator_llm=None) -> None:
        self.store, self.extractor, self._today, self.k = store, extractor, today, max(1, agreement_k)
        self.translator_llm = translator_llm if translator_llm is not None else (extractor if hasattr(extractor, "base_url") else None)

    @property
    def today(self) -> date:
        t = self._today
        return (t() if callable(t) else t) or date.today()

    # -- core
    def _extract(self, message: str):
        """Counted retry (1 extra attempt), never a keyword fallback: failure -> HUMAN_REVIEW."""
        if self.extractor is None:
            raise ExtractionUnavailable("no LLM configured")
        err = None
        for attempt in range(2):
            try:
                return self.extractor.extract(message), attempt
            except ExtractionUnavailable as exc:
                err = exc
        raise err

    def _decide(self, message: str, ctx: ContextV3) -> tuple[DecisionV3, dict | None, str]:
        try:
            ex, retries = self._extract(message)
        except ExtractionUnavailable as exc:
            d = DecisionV3().stop("V-", "HUMAN_REVIEW", f"Extraction unavailable after a counted retry ({exc}); v3 never "
                                                         "falls back to keyword routing.")
            return d, None, f"extraction failed: {exc}"
        d = decide_v3(ex, message, ctx, self.today, self.store.open_task)
        note = f"extracted by {ex.extractor} in {ex.latency_ms} ms (retries {retries})"
        if d.action == "CREATE_SUPPLIER_TASK" and self.k > 1:
            try:
                extras = self.extractor.sample(message, self.k - 1, 1.0)
                d = agreement_gate(d, extras, message, ctx, self.today)
            except ExtractionUnavailable as exc:
                d.suggested_task = None
                d.stop("V13", "HUMAN_REVIEW", f"Agreement samples unavailable ({exc}): demoted to a human.")
        exd = ex.raw | {"extractor": ex.extractor, "latency_ms": ex.latency_ms}
        return d, exd, note

    def _clarify(self, cid: str, d: DecisionV3, rounds: list[dict], lang: str) -> tuple[str, dict | None]:
        gate = clarify_next(rounds, d)
        if not gate["ask"]:
            return "HUMAN_REVIEW", {"handoff": gate["reason"]}
        text, keep = render_template(d)
        tr = Translator(self.translator_llm, self.store.cache())
        out = tr.translate(text, keep, lang)
        if out["source"].startswith("llm-translation"):
            self.store.put_cache(f"{lang}|{text}", {k: out[k] for k in ("text", "lang", "source", "checks")})
        q = {"round": len(rounds) + 1, "template": d.template, "slots": d.slots, "canonical": text, "question": out["text"],
             "lang": out["lang"], "translation": out["source"], "checks": out.get("checks", []), "reply": None}
        return "AWAITING_CUSTOMER", q

    def triage(self, message: str, ctx: ContextV3) -> str:
        cid = "RV3-" + secrets.token_hex(4).upper()
        lang = detect_lang(message)
        d, exd, note = self._decide(message, ctx)
        status, rounds, task = STATUS_OF[d.action], [], None
        self.store.save({"id": cid, "created_at": _now(), "customer": ctx.customer, "linked_order": ctx.linked_order_id,
                         "message": message, "lang": lang, "status": "HUMAN_REVIEW", "rounds_json": "[]"})
        self.store.log(cid, "received", f"{len(message)} chars · lang {lang} · {MOCK_LABEL}")
        self.store.log(cid, "extracted", note)
        if d.action == "CLARIFY_WITH_CUSTOMER":
            status, q = self._clarify(cid, d, rounds, lang)
            if status == "AWAITING_CUSTOMER":
                rounds.append(q)
                self.store.log(cid, "clarify", f"{q['template']} ({q['translation']})")
            else:
                d.reason += f" | {q['handoff']}"
        if d.suggested_task:
            task = d.suggested_task
            self.store.log(cid, "suggested_task", f"{task['supplier']} · {task['dedup_key']}"
                           + (f" · duplicate of {task['duplicate_of']}" if task.get("duplicate_of") else ""))
        self.store.log(cid, "decided", f"{d.action} by {d.decided_by}")
        self._save(cid, ctx, message, lang, status, d, exd, rounds, task)
        return cid

    def _save(self, cid, ctx, message, lang, status, d, exd, rounds, task, created=None):
        old = self.store.get(cid) or {}
        self.store.save({"id": cid, "created_at": created or old.get("created_at") or _now(), "customer": ctx.customer,
                         "linked_order": ctx.linked_order_id, "message": message, "lang": lang, "status": status,
                         "action": d.action, "rule": d.rule, "decided_by": d.decided_by, "refund_intent": int(d.refund_intent),
                         "decision_json": json.dumps(d.to_dict(), default=str), "extraction_json": json.dumps(exd) if exd else None,
                         "rounds_json": json.dumps(rounds), "task_json": json.dumps(task) if task else None})

    def simulate_reply(self, cid: str, reply: str) -> str:
        """Simulated customer reply (panel only; nothing was sent). Re-gates on original message + reply."""
        case = self.store.get(cid)
        if case is None:
            raise KeyError(cid)
        if case["status"] != "AWAITING_CUSTOMER":
            raise ValueError(f"Case is {case['status']}, not awaiting a customer reply.")
        rounds = case["rounds"]
        rounds[-1]["reply"] = reply
        ctx = ContextV3(case["customer"], case["linked_order"])
        self.store.log(cid, "reply_simulated", f"{len(reply)} chars (simulated in the panel; nothing was sent)")
        if looks_like_injection(reply) or _HUMAN_ASK.search(reply):
            d = DecisionV3().stop("R0", "HUMAN_REVIEW", "Reply asks for a person or contains instruction-like text: a human "
                                                         "takes over.")
            self._save(cid, ctx, case["message"], case["lang"], "HUMAN_REVIEW", d, case["extraction"], rounds, None)
            return cid
        combined = f"{case['message']}\n\n[Customer reply to clarifying question {rounds[-1]['template']}]\n{reply}"
        d, exd, note = self._decide(combined, ctx)
        self.store.log(cid, "re-gated", note)
        status, task = STATUS_OF[d.action], None
        if d.rule in ("V0", "V1", "V2", "V3") and d.action == "HUMAN_REVIEW":
            d.reason += " (raised by the reply)"
        if d.action == "CLARIFY_WITH_CUSTOMER":
            status, q = self._clarify(cid, d, rounds, case["lang"])
            if status == "AWAITING_CUSTOMER":
                rounds.append(q)
            else:
                d.reason += f" | {q['handoff']}"
                d.action = "HUMAN_REVIEW"
        if d.suggested_task:
            task = d.suggested_task
        self.store.log(cid, "decided", f"{d.action} by {d.decided_by} (after reply {len(rounds)}/{MAX_CLARIFY_ROUNDS})")
        self._save(cid, ctx, combined, case["lang"], status, d, exd, rounds, task)
        return cid

    def confirm_task(self, cid: str, by: str = "merchant") -> dict:
        case = self.store.get(cid)
        if case is None:
            raise KeyError(cid)
        if case["status"] != "SUGGESTED_TASK" or not case.get("task"):
            raise ValueError(f"Case is {case['status']}: there is no suggested task to confirm.")
        task = case["task"] | {"status": "DRAFT_READY", "confirmed_by": by, "confirmed_at": _now()}
        task["draft"] = draft_task_text(cid, task)
        with self.store.connect() as c:
            c.execute("UPDATE routing_v3_cases SET status='TASK_DRAFT_READY', task_json=? WHERE id=?", (json.dumps(task), cid))
        self.store.log(cid, "task_confirmed", f"by {by}: internal draft created (NOT sent)")
        return task

    def dismiss_task(self, cid: str, by: str = "merchant") -> None:
        case = self.store.get(cid)
        if case is None:
            raise KeyError(cid)
        if case["status"] != "SUGGESTED_TASK":
            raise ValueError("No suggested task to dismiss.")
        with self.store.connect() as c:
            c.execute("UPDATE routing_v3_cases SET status='HUMAN_REVIEW' WHERE id=?", (cid,))
        self.store.log(cid, "task_dismissed", f"by {by}: handled by a human instead")
