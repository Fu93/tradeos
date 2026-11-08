"""Validate the audit-head snapshot before retaining it outside TradeOS.

Usage: python scripts/validate_audit_heads.py audit-heads-<commit>.json
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HASH = re.compile(r"[0-9a-f]{64}\Z")


def validate(payload: object) -> int:
    if not isinstance(payload, dict):
        raise ValueError("snapshot must be a JSON object")
    generated_at = payload.get("generated_at")
    if not isinstance(generated_at, str):
        raise ValueError("generated_at is missing")
    try:
        timestamp = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("generated_at is invalid") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() != timezone.utc.utcoffset(timestamp):
        raise ValueError("generated_at must be UTC")
    heads = payload.get("heads")
    if not isinstance(heads, list) or not heads:
        raise ValueError("heads must be a nonempty list")
    case_ids: set[str] = set()
    for item in heads:
        if not isinstance(item, dict):
            raise ValueError("each head must be an object")
        case_id, seq, head = item.get("case_id"), item.get("seq"), item.get("head")
        if not isinstance(case_id, str) or not case_id or case_id in case_ids:
            raise ValueError("case IDs must be nonempty and unique")
        if type(seq) is not int or not 1 <= seq <= 2**63 - 1:
            raise ValueError("head sequence must be a positive SQLite integer")
        if not isinstance(head, str) or HASH.fullmatch(head) is None:
            raise ValueError("head must be a 64-character lowercase SHA-256 hex string")
        case_ids.add(case_id)
    return len(heads)


def main(path: str) -> int:
    try:
        count = validate(json.loads(Path(path).read_text()))
    except (OSError, ValueError) as exc:
        print(f"invalid audit-head snapshot: {exc}", file=sys.stderr)
        return 1
    print(f"validated {count} audit-chain heads")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/validate_audit_heads.py PATH", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
