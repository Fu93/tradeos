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


# ---- review round ----
def test_truncated_last_entry_detected_when_record_remains(settings):
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    last = wf.db.chain_entries(case_id)[-1]
    raw(wf.db, "DROP TRIGGER audit_chain_no_delete")
    raw(wf.db, "DELETE FROM audit_chain WHERE id=?", (last["id"],))
    res = wf.db.verify_chain(case_id)
    if last["source_table"] in chain.SOURCE_PAYLOAD:
        assert res["ok"] is False and "missing from the chain" in res["reason"]


def test_truncation_with_record_also_deleted_needs_external_head(settings):
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    wf.db.audit(case_id, "note", "last")
    head = wf.db.verify_chain(case_id)["head"]
    last = wf.db.chain_entries(case_id)[-1]
    raw(wf.db, "DROP TRIGGER audit_chain_no_delete")
    raw(wf.db, "DELETE FROM audit_chain WHERE id=?", (last["id"],))
    raw(wf.db, "DELETE FROM audit_events WHERE id=?", (last["source_id"],))
    res = wf.db.verify_chain(case_id)
    assert res["ok"] is True and res["head"] != head  # honest limit: only an anchored head shows it


def test_mixed_concurrent_writers_one_consistent_chain(settings):
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    go = threading.Barrier(30)

    def w(i):
        go.wait()
        if i % 3 == 0:
            wf.db.audit(case_id, "note", f"n{i}")
        elif i % 3 == 1:
            wf.db.log_paypal_call(case_id, "get_capture", True, "COMPLETED", debug_id=f"d{i}")
        else:
            wf.db.log_webhook_event(f"E{i}", "PAYMENT.CAPTURE.REFUNDED", "SUCCESS", True, case_id, "R", "COMPLETED",
                                    "PROCESSING")
            wf.db.set_webhook_outcome(f"E{i}", "CONFIRMED")
    ths = [threading.Thread(target=w, args=(i,)) for i in range(30)]
    [t.start() for t in ths]
    [t.join(timeout=30) for t in ths]
    assert not any(t.is_alive() for t in ths)  # no deadlock
    res = wf.db.verify_chain(case_id)
    seqs = [e["seq"] for e in wf.db.chain_entries(case_id)]
    assert res["ok"] and seqs == list(range(1, len(seqs) + 1))


def test_background_reconcile_vs_approve_vs_webhook(settings):
    client, pp, wf = app_with(settings, reconcile_in_background=True)
    case_id = case_from(client.post("/demo/run/A", follow_redirects=False))
    ths = [threading.Thread(target=lambda: client.post(f"/cases/{case_id}/approve", follow_redirects=False)),
           threading.Thread(target=lambda: wf.reconcile(case_id)),
           threading.Thread(target=lambda: wf.auto_reconcile(case_id))]
    [t.start() for t in ths]
    [t.join(timeout=30) for t in ths]
    rid = wf.db.get_case(case_id)["refund_id"]
    client.post("/webhooks/paypal", content=json.dumps(refund_event(rid)), headers=SIG)
    import time
    time.sleep(0.5)
    assert wf.db.verify_chain(case_id)["ok"] and pp.refund_capture.call_count == 1


@pytest.mark.parametrize("payload", [{"f": 0.1, "big": 1e21, "neg": -0.0, "i": 10**20},
                                     {"u": "退款 ÄÖÜ 日本語 🙂", "esc": "a\"b\\c\n"},
                                     {"n": None, "l": [None, True, False], "nested": {"z": 1, "a": {"y": None}}}])
def test_canonical_json_stable(settings, payload):
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    wf.db.audit(case_id, "note", "edge", payload)
    assert wf.db.verify_chain(case_id)["ok"]
    a = chain.canonical(chain.normalize(payload))
    assert a == chain.canonical(json.loads(json.dumps(chain.normalize(payload), sort_keys=True)))


def test_no_secrets_in_chain(settings):
    client, pp, wf = app_with(settings)
    run_a(client)
    blob = json.dumps([e["payload_json"] for c in wf.db.list_cases() for e in wf.db.chain_entries(c["id"])]).lower()
    for bad in ("access_token", "bearer ", "client_secret", "authorization", "api_key"):
        assert bad not in blob


def test_verify_latency_reasonable(settings):
    import time
    client, pp, wf = app_with(settings)
    case_id = run_a(client)
    for i in range(300):
        wf.db.audit(case_id, "note", f"n{i}", {"i": i})
    t0 = time.perf_counter()
    assert wf.db.verify_chain(case_id)["ok"]
    t1 = time.perf_counter()
    client.get(f"/?case={case_id}")
    t2 = time.perf_counter()
    print(f"verify {len(wf.db.chain_entries(case_id))} entries: {1000*(t1-t0):.1f} ms; page {1000*(t2-t1):.1f} ms")
    assert t1 - t0 < 1.0
