"""A retained head can verify the database after backup, restore and later appends."""

import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from app.config import Settings
from app.db import utcnow
from app.main import create_app
from app.notes import TemplateNoteWriter
from app.paypal_mock import MockPayPalClient
from scripts.backup_db import backup
from scripts.check_audit_anchor import check_anchor
from tests.helpers import FakeExtractor

ROOT = Path(__file__).resolve().parents[1]


def app_at(path, paypal):
    return create_app(settings=Settings(db_path=str(path), reset_on_start=False), paypal=paypal,
                      extractor=FakeExtractor(), note_writer=TemplateNoteWriter())


def test_anchor_survives_backup_restore_and_later_appends(tmp_path):
    source = tmp_path / "source.db"
    paypal = MockPayPalClient()
    first = app_at(source, paypal)
    case_id = first.state.workflow.run_scenario("B")
    snapshot = tmp_path / "heads.json"
    heads = first.state.workflow.db.chain_heads()
    snapshot.write_text(json.dumps({"generated_at": utcnow(), "heads": heads}))

    restored_path = tmp_path / "restored.db"
    backup(source, restored_path)
    restored = app_at(restored_path, paypal)
    assert restored.state.workflow.db.get_case(case_id) is not None
    assert check_anchor(restored_path, snapshot) == len(heads)
    restored.state.workflow.db.audit(case_id, "note", "after restore")
    assert check_anchor(restored_path, snapshot) == len(heads)


def test_anchor_rejects_rewritten_chain(tmp_path):
    source = tmp_path / "source.db"
    app = app_at(source, MockPayPalClient())
    case_id = app.state.workflow.run_scenario("B")
    snapshot = tmp_path / "heads.json"
    snapshot.write_text(json.dumps({"generated_at": utcnow(), "heads": app.state.workflow.db.chain_heads()}))
    with closing(sqlite3.connect(source)) as conn:
        conn.execute("DROP TRIGGER audit_chain_no_update")
        conn.execute("UPDATE audit_chain SET entry_hash=? WHERE case_id=? AND seq=1", ("0" * 64, case_id))
        conn.commit()
    with pytest.raises(ValueError, match="does not extend anchored head"):
        check_anchor(source, snapshot)


def test_anchor_cli_can_run_directly_and_rejects_bad_snapshot(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "scripts/check_audit_anchor.py"), "--help"],
                            cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0 and "snapshot" in result.stdout
    source = tmp_path / "source.db"
    app_at(source, MockPayPalClient())
    snapshot = tmp_path / "bad.json"
    snapshot.write_text('{"heads": []}')
    with pytest.raises(ValueError, match="generated_at"):
        check_anchor(source, snapshot)
