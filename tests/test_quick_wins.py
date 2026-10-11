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
