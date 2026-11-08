"""The deployment artifact validator must reject snapshots that cannot serve as audit evidence."""

import json

import pytest

from scripts.validate_audit_heads import main, validate


def snapshot():
    return {"generated_at": "2026-11-05T12:00:00Z",
            "heads": [{"case_id": "case-a", "seq": 2, "head": "a" * 64}]}


def test_valid_audit_snapshot_cli(tmp_path, capsys):
    path = tmp_path / "audit-heads.json"
    path.write_text(json.dumps(snapshot()))
    assert main(str(path)) == 0
    assert "validated 1 audit-chain heads" in capsys.readouterr().out


@pytest.mark.parametrize("change", [
    lambda data: data.update(generated_at="2026-11-05T12:00:00"),
    lambda data: data.update(heads=[]),
    lambda data: data["heads"].append(dict(data["heads"][0])),
    lambda data: data["heads"][0].update(seq=True),
    lambda data: data["heads"][0].update(seq=2**70),
    lambda data: data["heads"][0].update(head="not-a-hash"),
])
def test_invalid_audit_snapshots_are_refused(change, tmp_path, capsys):
    data = snapshot()
    change(data)
    with pytest.raises(ValueError):
        validate(data)
    path = tmp_path / "audit-heads.json"
    path.write_text(json.dumps(data))
    assert main(str(path)) == 1
    assert "invalid audit-head snapshot" in capsys.readouterr().err


def test_validator_rejects_truncated_json(tmp_path):
    path = tmp_path / "audit-heads.json"
    path.write_text('{"heads":')
    assert main(str(path)) == 1
