"""Hash-chained audit trail: append-only, verifiable, tamper-evident (not tamper-proof)."""
import hashlib
import json
import sqlite3
import threading

import pytest

from app import audit_chain as chain
from app.db import Database
from tests.test_hardening import SIG, app_with, case_from, pending_case, refund_event, run_a


def raw(db, sql, args=()):
    conn = sqlite3.connect(db.path)
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def test_case_a_chain_covers_decisions_paypal_and_webhooks(settings):
    client, pp, wf, case_id, rid = pending_case(settings)
    client.post("/webhooks/paypal", content=json.dumps(refund_event(rid)), headers=SIG)
    wf.reconcile(case_id)
    types = [e["type"] for e in wf.db.chain_entries(case_id)]
    assert any(t.startswith("audit:policy") for t in types)
    assert any(t.startswith("audit:human") for t in types)
    assert "paypal:refund_capture" in types and "paypal:get_capture" in types
    assert "webhook:received" in types and "webhook:outcome" in types
    assert "audit:reconcile" in types
    res = client.get(f"/cases/{case_id}/audit/verify").json()
    assert res["ok"] and res["entries"] == len(types) and res["broken_at"] is None and res["backfilled"] == 0


def test_hash_definition_is_sha256_of_canonical_json(settings):
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    entries = wf.db.chain_entries(case_id)
    assert entries[0]["prev_hash"] == chain.GENESIS == "0" * 64
    for prev, e in zip([None] + entries, entries):
        body = {"case_id": case_id, "seq": e["seq"], "type": e["type"], "ts": e["ts"],
                "payload": json.loads(e["payload_json"]), "prev_hash": e["prev_hash"]}
        blob = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        assert hashlib.sha256(blob).hexdigest() == e["entry_hash"]
        if prev:
            assert e["prev_hash"] == prev["entry_hash"]


def test_append_only_triggers(settings):
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    with pytest.raises(sqlite3.IntegrityError):
        raw(wf.db, "UPDATE audit_chain SET ts='x' WHERE case_id=?", (case_id,))
    with pytest.raises(sqlite3.IntegrityError):
        raw(wf.db, "DELETE FROM audit_chain WHERE case_id=?", (case_id,))
    assert not hasattr(wf.db, "update_chain") and not hasattr(wf.db, "delete_chain")


# ---- tamper demonstrations (test-only; there is no tamper button in the app) ----
def test_tamper_source_audit_row_detected(settings):
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    entries = wf.db.chain_entries(case_id)
    target = next(e for e in entries if e["source_table"] == "audit_events" and "human" in e["type"])
    raw(wf.db, "UPDATE audit_events SET title='Human DECLINED' WHERE id=?", (target["source_id"],))
    res = wf.db.verify_chain(case_id)
    assert res["ok"] is False and res["broken_at"] == target["seq"] and "modified" in res["reason"]
    page = client.get(f"/?case={case_id}").text
    assert f"Audit trail BROKEN at entry {target['seq']}" in page


def test_tamper_paypal_call_and_deleted_row_detected(settings):
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    e = next(e for e in wf.db.chain_entries(case_id) if e["type"] == "paypal:refund_capture")
    raw(wf.db, "UPDATE paypal_calls SET result='FAILED' WHERE id=?", (e["source_id"],))
    assert wf.db.verify_chain(case_id)["broken_at"] == e["seq"]
    raw(wf.db, "DELETE FROM paypal_calls WHERE id=?", (e["source_id"],))
    assert "deleted" in wf.db.verify_chain(case_id)["reason"]


def test_tamper_chain_entry_detected_after_dropping_trigger(settings):
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    raw(wf.db, "DROP TRIGGER audit_chain_no_update")
    e = wf.db.chain_entries(case_id)[2]
    raw(wf.db, "UPDATE audit_chain SET payload_json=? WHERE id=?", (json.dumps({"forged": True}), e["id"]))
    res = wf.db.verify_chain(case_id)
    assert res == {**res, "ok": False, "broken_at": 3, "reason": "entry content does not match its hash"}


def test_full_rewrite_is_not_detected_without_external_anchor(settings):
    """The documented limit: someone who rewrites AND recomputes the chain passes verify. Only a head
    hash noted outside the database (e.g. earlier) reveals it."""
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    head_before = wf.db.verify_chain(case_id)["head"]
    raw(wf.db, "DROP TRIGGER audit_chain_no_update")
    raw(wf.db, "DROP TRIGGER audit_chain_no_delete")
    e = next(e for e in wf.db.chain_entries(case_id) if "human" in e["type"])
    raw(wf.db, "UPDATE audit_events SET title='Rewritten' WHERE id=?", (e["source_id"],))
    rows = wf.db.chain_entries(case_id)
    # recompute consistently (attacker with write access)
    raw(wf.db, "DELETE FROM audit_chain WHERE case_id=?", (case_id,))
    from app.db import _chain_lock
    with _chain_lock, wf.db.connect() as conn:
        for r in rows:
            payload = json.loads(r["payload_json"])
            if r["id"] == e["id"]:
                payload["title"] = "Rewritten"
            wf.db._chain_append(conn, case_id, r["type"], r["ts"], payload, r["source_table"], r["source_id"])
    res = wf.db.verify_chain(case_id)
    assert res["ok"] is True                    # not detectable from inside the database...
    assert res["head"] != head_before           # ...but the head hash changed, so an external note catches it


def test_backfill_existing_db_marks_rows(tmp_path):
    path = str(tmp_path / "old.db")
    db = Database(path)
    db.init(reset=True)
    # simulate a pre-chain database: drop the chain and add legacy rows
    raw(db, "DROP TABLE audit_chain")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("INSERT INTO audit_events (case_id, ts, stage, title, detail_json) VALUES ('OLD-1','2026-10-01T00:00:01Z','policy','Policy','{}')")
    conn.execute("INSERT INTO paypal_calls (case_id, ts, operation, ok, result) VALUES ('OLD-1','2026-10-01T00:00:02Z','refund_capture',1,'COMPLETED')")
    conn.commit()
    conn.close()
    db.init(reset=False)
    res = db.verify_chain("OLD-1")
    assert res["ok"] and res["entries"] == 2 and res["backfilled"] == 2
    assert [e["type"] for e in db.chain_entries("OLD-1")] == ["audit:policy", "paypal:refund_capture"]
    db.init(reset=False)  # idempotent
    assert db.verify_chain("OLD-1")["entries"] == 2


def test_reset_rebuilds_cleanly(settings):
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    client.post("/demo/reset", follow_redirects=False)
    assert wf.db.chain_entries(case_id) == []
    for c in wf.db.list_cases():
        assert wf.db.verify_chain(c["id"])["ok"]


def test_concurrent_appends_keep_one_chain(settings):
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    ths = [threading.Thread(target=lambda i=i: wf.db.audit(case_id, "note", f"n{i}")) for i in range(20)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    res = wf.db.verify_chain(case_id)
    assert res["ok"] and [e["seq"] for e in wf.db.chain_entries(case_id)] == list(range(1, res["entries"] + 1))


def test_case_a_once_case_b_409_unchanged_and_badge(settings):
    client, pp, wf = app_with(settings)
    a = run_a(client)
    assert pp.refund_capture.call_count == 1
    b = case_from(client.post("/demo/run/B", follow_redirects=False))
    assert client.post(f"/cases/{b}/approve", follow_redirects=False).status_code == 409
    assert pp.refund_capture.call_count == 1
    page = client.get(f"/?case={a}").text
    assert "Audit trail intact:" in page and "Verify audit trail" in page
    assert client.get("/cases/NOPE/audit/verify").status_code == 404
