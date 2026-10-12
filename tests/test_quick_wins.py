"""Small hardening follow-ups from the 2026-10-11 audit: WAL journal mode and full-entropy case ids."""
import re

from app.db import Database


def test_sqlite_uses_wal_journal(settings):
    """Readers (dashboard chain verification) must stop blocking the writer (background reconcile)."""
    db = Database(settings.db_path)
    db.init()
    with db.connect() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_case_ids_have_64_bit_entropy(workflow):
    # Long enough that enumerating action endpoints by id is infeasible, short enough that the
    # PayPal-Request-Ids derived from it stay within PayPal's 38-char guidance (see the comment
    # in new_case and test_paypal_request_ids_fit_paypal_limit).
    for _ in range(4):
        case_id = workflow.new_case("A")
        assert re.fullmatch(r"A-[0-9A-F]{16}", case_id)


def test_secondary_indexes_exist(settings):
    """find_case_by (every webhook delivery), timeline, paypal_calls, webhook_events and verify_chain's
    coverage check must not scan the whole table."""
    db = Database(settings.db_path)
    db.init()
    with db.connect() as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    for expected in ("idx_cases_capture_id", "idx_cases_refund_id", "idx_cases_order_id",
                     "idx_audit_events_case", "idx_paypal_calls_case", "idx_webhook_events_case"):
        assert expected in names


def test_latest_case_is_a_single_query_with_label_filter(workflow):
    db = workflow.db
    a = workflow.run_scenario("A")
    b = workflow.run_scenario("A")  # two scenario-A cases: the newest must win
    assert db.latest_case("A")["id"] == b
    assert db.latest_case("A", label="Case A")["id"] == b
    assert db.latest_case("A", label="no-such-label") is None
    assert a and db.latest_case("B")["scenario"] == "B"
