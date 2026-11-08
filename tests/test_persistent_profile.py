"""The private disk profile keeps cases and their audit chains across app restarts."""

from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
import yaml
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.notes import TemplateNoteWriter
from app.paypal_mock import MockPayPalClient
from app.db import Database
from scripts.backup_db import backup
from tests.helpers import FakeExtractor

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "private-sandbox-operator-token-123456"


def private_settings(tmp_path, **overrides):
    disk = tmp_path / "data"
    fields = {"db_path": str(disk / "tradeos.db"), "persistent_data_dir": str(disk),
              "reset_on_start": False, "operator_token": TOKEN, "mcp_enabled": False,
              "public_base_url": "https://private.example"}
    return Settings(**(fields | overrides))


def test_persistent_profile_survives_restart_with_audit_chain(tmp_path):
    settings = private_settings(tmp_path)
    paypal = MockPayPalClient()
    first = create_app(settings=settings, paypal=paypal, extractor=FakeExtractor(),
                       note_writer=TemplateNoteWriter())
    case_id = first.state.workflow.run_scenario("B")
    first_head = first.state.workflow.db.verify_chain(case_id)
    assert first_head["ok"] and first_head["entries"] > 0

    restarted = create_app(settings=settings, paypal=paypal, extractor=FakeExtractor(),
                           note_writer=TemplateNoteWriter())
    db = restarted.state.workflow.db
    assert db.get_case(case_id)["archived_at"] is None
    assert db.verify_chain(case_id)["head"] == first_head["head"]
    assert TestClient(restarted).get("/healthz").json()["persistence"] == "persistent-disk-configured"


@pytest.mark.parametrize("override, message", [
    ({"db_path": "relative.db"}, "inside the absolute persistent data directory"),
    ({"reset_on_start": True}, "TRADEOS_RESET_ON_START=0"),
    ({"operator_token": ""}, "TRADEOS_OPERATOR_TOKEN"),
])
def test_persistent_profile_rejects_unsafe_configuration(tmp_path, override, message):
    with pytest.raises(ValueError, match=message):
        private_settings(tmp_path, **override)


def test_persistent_profile_refuses_database_outside_mount(tmp_path):
    with pytest.raises(ValueError, match="inside the absolute persistent data directory"):
        private_settings(tmp_path, db_path=str(tmp_path / "outside.db"))


def test_persistent_profile_loads_from_environment(tmp_path, monkeypatch):
    disk = tmp_path / "data"
    monkeypatch.setenv("TRADEOS_PERSISTENT_DATA_DIR", str(disk))
    monkeypatch.setenv("TRADEOS_DB_PATH", str(disk / "tradeos.db"))
    monkeypatch.setenv("TRADEOS_RESET_ON_START", "0")
    monkeypatch.setenv("TRADEOS_OPERATOR_TOKEN", TOKEN)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://private.example")
    settings = Settings.from_env()
    assert settings.persistent_data_dir == str(disk)
    assert settings.db_path == str(disk / "tradeos.db")
    assert settings.reset_on_start is False


def test_render_persistent_blueprint_keeps_sqlite_on_mounted_disk():
    service = yaml.safe_load((ROOT / "render-persistent.yaml").read_text())["services"][0]
    disk = service["disk"]
    env = {item["key"]: item for item in service["envVars"]}
    assert disk["mountPath"] == "/var/data" and disk["sizeGB"] >= 1
    assert env["TRADEOS_DB_PATH"]["value"] == "/var/data/tradeos.db"
    assert env["TRADEOS_PERSISTENT_DATA_DIR"]["value"] == disk["mountPath"]
    assert env["TRADEOS_RESET_ON_START"]["value"] == "0"
    assert env["TRADEOS_OPERATOR_TOKEN"]["sync"] is False
    assert env["TRADEOS_MCP"]["value"] == "1"
    assert env["TRADEOS_MCP_TOKEN"]["sync"] is False


def test_backup_captures_a_consistent_snapshot_without_overwriting(tmp_path):
    settings = private_settings(tmp_path)
    app = create_app(settings=settings, paypal=MockPayPalClient(), extractor=FakeExtractor(),
                     note_writer=TemplateNoteWriter())
    case_id = app.state.workflow.run_scenario("B")
    destination = tmp_path / "export" / "snapshot.db"
    cases, digest = backup(Path(settings.db_path), destination)
    assert cases >= 1 and len(digest) == 64
    copied = Database(str(destination))
    assert copied.get_case(case_id) is not None
    assert copied.verify_chain(case_id)["ok"]
    assert copied.verify_chain(case_id)["head"] == app.state.workflow.db.verify_chain(case_id)["head"]
    before = destination.read_bytes()
    with pytest.raises(FileExistsError):
        backup(Path(settings.db_path), destination)
    assert destination.read_bytes() == before


def test_backup_refuses_broken_audit_chain_and_cleans_stage(tmp_path):
    settings = private_settings(tmp_path)
    app = create_app(settings=settings, paypal=MockPayPalClient(), extractor=FakeExtractor(),
                     note_writer=TemplateNoteWriter())
    case_id = app.state.workflow.run_scenario("B")
    with app.state.workflow.db.connect() as conn:
        changed = conn.execute("UPDATE audit_events SET title='tampered' WHERE case_id=?", (case_id,))
        assert changed.rowcount > 0
    destination = tmp_path / "export" / "snapshot.db"
    with pytest.raises(ValueError, match="invalid audit chain"):
        backup(Path(settings.db_path), destination)
    assert not destination.exists()
    assert not list(destination.parent.glob("*.tmp"))


def test_backup_refuses_broken_foreign_keys(tmp_path):
    settings = private_settings(tmp_path)
    app = create_app(settings=settings, paypal=MockPayPalClient(), extractor=FakeExtractor(),
                     note_writer=TemplateNoteWriter())
    case_id = app.state.workflow.run_scenario("B")
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DELETE FROM products WHERE sku=(SELECT product_sku FROM cases WHERE id=?)", (case_id,))
    destination = tmp_path / "export" / "snapshot.db"
    with pytest.raises(ValueError, match="foreign-key check"):
        backup(Path(settings.db_path), destination)
    assert not destination.exists()


def test_backup_script_can_run_directly_from_repository():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/backup_db.py"), "--help"], cwd=ROOT,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0 and "source" in result.stdout and "destination" in result.stdout
