"""Mutation sanity for the mixed-order money logic (dev tool, not part of CI).

Applies one small, deliberate bug at a time to app/lineitems.py or app/mixed.py in a THROWAWAY COPY of the repo and
checks that the mixed-order tests fail ("killed"). A "SURVIVED" line means a test gap on money logic.

    python scripts/mutation_sanity.py          # exit 0 only if every mutant is killed
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ["tests/test_lineitems.py", "tests/test_mixed_orders.py"]

# (file, original snippet, mutated snippet, what the bug would be in production)
MUTANTS = [
    ("app/lineitems.py", "qty = min(d.qty - used_r, free)", "qty = min(d.qty, free)", "second batch re-refunds units"),
    ("app/lineitems.py", "if total > remaining:", "if total > remaining + 1:", "over-refund by one minor unit"),
    ("app/lineitems.py", "if total > remaining:", "if total >= remaining:", "refuses an exact full balance"),
    ("app/lineitems.py", "ln.tax_unit_minor * qty, ship", "ln.tax_unit_minor, ship", "tax not multiplied by quantity"),
    ("app/lineitems.py", "ln.unit_minor * qty, ln.tax", "ln.unit_minor, ln.tax", "item price not multiplied by qty"),
    ("app/lineitems.py", "and used_r + qty == ln.qty):", "):", "shipping released on a partial-qty refund"),
    ("app/lineitems.py", "and ln.line_no not in ledger.shipping_released and used_r", "and True and used_r", "shipping refunded twice"),
    ("app/lineitems.py", "and d.merchant_error", "and True", "shipping refunded for changed-mind returns"),
    ("app/lineitems.py", "[:left]:", "[:left - 1]:", "allocation loses a minor unit"),
    ("app/lineitems.py", "if scaled != scaled.to_integral_value():", "if False:", "extra decimals silently truncated"),
    ("app/lineitems.py", 'ZERO_DECIMAL = frozenset({"JPY", "HUF", "TWD"})', 'ZERO_DECIMAL = frozenset({"JPY", "HUF"})', "TWD treated as 2-decimal"),
    ("app/lineitems.py", 'if "." in text and (exp == 0 or', 'if "." in text and (False and', "decimals accepted for JPY"),
    ("app/lineitems.py", "return f\"tos-mx-{case_id}-{digest[:10]}\"", "return f\"tos-mx-{case_id}\"", "request id not item-specific"),
    ("app/lineitems.py", "payload = {\"case\": case_id, \"attempt\": attempt,", "payload = {\"case\": case_id,", "retry after FAILED reuses request id"),
    ("app/lineitems.py", "if capture != order.total:", "if False:", "capture/order mismatch ignored"),
    ("app/lineitems.py", "if k not in ALLOWED_PROPOSAL_KEYS:", "if False:", "ignored AI fields not reported"),
    ("app/lineitems.py", 'ALLOWED_PROPOSAL_KEYS = frozenset({"line_no", "action", "reason", "qty"})',
     'ALLOWED_PROPOSAL_KEYS = frozenset({"line_no", "action", "reason", "qty", "amount"})', "AI 'amount' accepted"),
    ("app/lineitems.py", "elif not ln.returnable:", "elif False:", "final-sale item refunded"),
    ("app/lineitems.py", "if injection_suspected:", "if False:", "injection text ignored"),
    ("app/lineitems.py", 'elif p.action not in ("RETURN", "EXCHANGE"):', "elif False:", "UNKNOWN request becomes a refund"),
    ("app/lineitems.py", "if exchange_lines or ledger.exchange_qty:", "if False:", "whole-order shipping released although a unit is exchanged"),
    ("app/lineitems.py", "if ledger.refund_qty.get(ln.line_no, 0) + got != ln.qty:", "if False:", "whole-order shipping released on a partial return"),
    ("app/lineitems.py", "if ln.line_no not in in_batch and ln.line_no not in ledger.shipping_released)", "if ln.line_no not in in_batch)", "already-released shipping share refunded again"),
    ("app/lineitems.py", "if q.line_no == last:", "if False:", "earlier lines' shipping shares lost on the completing batch"),
    ("app/lineitems.py", "if not ship and q.line_no not in ledger.shipping_released:", "if not ship:", "released share added twice"),
    ("app/lineitems.py", 'if shipping_policy == "WITHDRAWAL_FULL" and refund_lines:', 'if shipping_policy != "NEVER" and refund_lines:', "MERCHANT_ERROR policy refunds whole-order shipping"),
    ("app/lineitems.py", '(shipping_policy in ("MERCHANT_ERROR", "WITHDRAWAL_FULL")', '(shipping_policy == ("MERCHANT_ERROR"', "default policy loses merchant-error shipping"),
    ("app/mixed.py", "if expected_total != shown or expected_hash != batch[\"items_hash\"]:", "if False:", "stale screen approves"),
    ("app/mixed.py", "if batch[\"status\"] != PROPOSED:", "if False:", "double approval allowed"),
    ("app/mixed.py", "if not (proposed and approved):", "if not (proposed or approved):", "approval not required on the chain"),
    ("app/mixed.py", "if batch[\"status\"] != APPROVED:\n            raise", "if False:\n            raise", "unapproved batch can be sent"),
    ("app/mixed.py", "or quote.total_minor != batch[\"amount_minor\"]):", "):", "tampered amount not detected"),
    ("app/mixed.py", "if cap_minor - self.ledger(case_id, exclude=batch_id).refunded_minor < batch[\"amount_minor\"]:", "if False:", "ledger balance ignored"),
    ("app/mixed.py", "RELEASED = (DECLINED, FAILED)", "RELEASED = (DECLINED,)", "FAILED batch keeps units reserved"),
    ("app/mixed.py", "if not same and new_status != FAILED:", "if False:", "PayPal amount mismatch ignored"),
    ("app/mixed.py", "amount=body_amount, custom_id", "custom_id", "partial refund sent without amount (full refund!)"),
    ("app/mixed.py", "if batch[\"amount_minor\"] == 0:", "if batch[\"amount_minor\"] >= 0:", "refund call skipped for real amounts"),
]

# Mutants that cannot change behaviour because a second, independent check already catches the same bug (defence in
# depth). They are reported, not hidden: removing one guard leaves the other guard enforcing the rule.
EQUIVALENT = {
    "shipping refunded twice": "a fully-refunded line has no free units, so no shipping share can be re-released",
    "whole-order shipping released although a unit is exchanged": "a whole-order return needs every unit of every line refunded, which already excludes any exchanged unit",
    "released share added twice": "a line with a released share is fully refunded, so it can never appear in a later batch",
    "tampered amount not detected": "items_hash and the chained amount already differ for any tampered amount",
}


def main() -> int:
    survived: list[str] = []
    equivalent: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "repo"
        shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.db", ".venv", ".pytest_cache",
                                                                  ".mypy_cache", ".ruff_cache", "venv*"))
        env = {**os.environ, "PAYPAL_MOCK": "1"}
        base = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", *TESTS], cwd=work, env=env,
                              capture_output=True, text=True)
        if base.returncode != 0:
            print("Baseline fails; fix the tests first.\n" + base.stdout[-1500:])
            return 2
        for i, (rel, old, new, what) in enumerate(MUTANTS, 1):
            path = work / rel
            original = path.read_text()
            if original.count(old) != 1:
                print(f"[{i:02d}] SKIPPED (snippet not found exactly once): {what}")
                survived.append(what)
                continue
            path.write_text(original.replace(old, new))
            try:
                res = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", *TESTS], cwd=work, env=env,
                                     capture_output=True, text=True, timeout=300)
                killed = res.returncode != 0
            finally:
                path.write_text(original)
            if not killed and what in EQUIVALENT:
                print(f"[{i:02d}] EQUIVALENT {what} -- {EQUIVALENT[what]}")
                equivalent.append(what)
                continue
            print(f"[{i:02d}] {'killed  ' if killed else 'SURVIVED'} {what}")
            if not killed:
                survived.append(what)
    print(f"\n{len(MUTANTS) - len(survived) - len(equivalent)}/{len(MUTANTS)} mutants killed, "
          f"{len(equivalent)} equivalent (redundant guard), {len(survived)} survived")
    return 0 if not survived else 1


if __name__ == "__main__":
    sys.exit(main())
