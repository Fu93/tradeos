"""Read-only check that the demo serves the exact commit intended for submission.

This does not prove a refund works. Run sandbox_verify.py separately for live PayPal evidence.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone

import httpx


def check(url: str, commit: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("--commit must be a full 40-character lowercase Git SHA")
    response = httpx.get(f"{url.rstrip('/')}/healthz", timeout=15, follow_redirects=False)
    response.raise_for_status()
    health = response.json()
    expected = {
        "ok": True,
        "version": commit,
        "paypal_mode": "sandbox",
        "llm_configured": True,
        "webhook_configured": True,
        "auto_enabled": False,
    }
    failed = {key: {"expected": value, "observed": health.get(key)}
              for key, value in expected.items() if health.get(key) != value}
    return {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "url": url.rstrip('/'),
            "expected_commit": commit, "checks": expected, "observed": {k: health.get(k) for k in expected},
            "passed": not failed, "failures": failed,
            "scope": "read-only deployment/configuration preflight; run sandbox_verify.py for PayPal evidence"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="HTTPS URL of the deployed demo")
    parser.add_argument("--commit", required=True, help="full deployed Git commit SHA")
    args = parser.parse_args()
    try:
        result = check(args.url, args.commit)
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(2, f"preflight could not run: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
