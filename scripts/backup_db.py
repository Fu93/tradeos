"""Take a consistent, verified SQLite backup while the Sandbox app is running.

Usage: python scripts/backup_db.py /var/data/tradeos.db /safe/offsite/tradeos-2026-11-05.db
The destination must not already exist. Transfer it to protected offsite storage separately.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import Database  # noqa: E402


def backup(source: Path, destination: Path) -> tuple[int, str]:
    if not source.is_file():
        raise ValueError(f"source database does not exist: {source}")
    if source.resolve() == destination.resolve():
        raise ValueError("source and destination must differ")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    staged = Path(name)
    try:
        uri = f"file:{quote(str(source.resolve()), safe='/')}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=30)) as original:
            with closing(sqlite3.connect(staged)) as copy:
                original.backup(copy)
                if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("backup failed SQLite integrity check")
                if copy.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise ValueError("backup failed foreign-key check")

        backed_up = Database(str(staged))
        with backed_up.connect() as conn:
            case_ids = [row[0] for row in conn.execute("SELECT id FROM cases ORDER BY id")]
        for case_id in case_ids:
            verdict = backed_up.verify_chain(case_id)
            if not verdict["ok"] or verdict["entries"] == 0:
                raise ValueError(f"backup has an invalid audit chain for case {case_id}: {verdict['reason']}")
        with closing(sqlite3.connect(staged)) as copy:
            copy.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        with staged.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        # Hard-link publication is atomic and refuses to replace a previous backup.
        os.link(staged, destination)
        return len(case_ids), digest
    finally:
        staged.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(f"{staged}{suffix}").unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        cases, digest = backup(args.source, args.destination)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"backup refused: {exc}", file=sys.stderr)
        return 1
    print(f"saved {args.destination} ({cases} cases; SHA-256 {digest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
