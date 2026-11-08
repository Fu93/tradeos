"""Check that a kept SQLite database still extends a separately retained audit-head snapshot.

Usage: python scripts/check_audit_anchor.py /var/data/tradeos.db audit-heads-<commit>.json
An audit-head file must come from outside the database (for example a CI artifact).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import Database  # noqa: E402
from scripts.validate_audit_heads import validate  # noqa: E402


def check_anchor(db_path: Path, snapshot_path: Path) -> int:
    if not db_path.is_file():
        raise ValueError(f"database does not exist: {db_path}")
    payload = json.loads(snapshot_path.read_text())
    count = validate(payload)
    db = Database(str(db_path))
    for item in payload["heads"]:
        if not db.extends_anchor(item["case_id"], item["seq"], item["head"]):
            raise ValueError(f"case {item['case_id']} does not extend anchored head at seq {item['seq']}")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    try:
        count = check_anchor(args.database, args.snapshot)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"audit anchor check failed: {exc}", file=sys.stderr)
        return 1
    print(f"verified {count} externally anchored audit chains")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
