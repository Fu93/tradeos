"""Manual mutation sanity for the Safety Gate (not collected by pytest; run: python tests/mutation_sanity.py).

Applies each source mutation in turn, runs tests/test_safety_gate.py, and requires the suite to FAIL (mutant killed).
The working tree is always restored."""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MUTANTS = [
    ("workflow: gate hit no longer routes to safety review", "app/workflow.py",
     "        if gate.flagged:\n            self._route_to_safety_review(case_id, gate, intent)\n            return\n", ""),
    ("workflow: server-side backstop removed (and status check)", "app/workflow.py",
     "        if case.get(\"status\") == NEEDS_SAFETY or case.get(\"decision\") == NEEDS_SAFETY:", "        if False:"),
    ("workflow: backstop re-scan ignores the message", "app/workflow.py",
     "        if safety_assess(case.get(\"customer_message\"), product, reason).flagged:", "        if False:"),
    ("safety: harm rule disabled", "app/safety.py", "    if harm:\n", "    if False and harm:\n"),
    ("safety: gated-product fault rule disabled", "app/safety.py", "    if cls in GATED_CLASSES:\n", "    if False:\n"),
    ("safety: LLM reason no longer counts", "app/safety.py", "if llm_reason in FAULT_REASONS:", "if False:"),
    ("safety: accent stripping removed", "app/safety.py", "if ord(ch) < 0x250:", "if False:"),
    ("safety: letter-spacing variant removed", "app/safety.py", "return [n] if joined == n else [n, joined]", "return [n]"),
    ("mixed: gate removed from case M", "app/mixed.py", "        if gate.flagged:  # Safety Gate first", "        if False:  # Safety Gate first"),
    ("mixed: batch approve backstop removed", "app/mixed.py", "                wf._refuse_if_safety(case)\n", ""),
    ("workflow.clean_message: zero-width turned into spaces again", "app/workflow.py",
     '("" if unicodedata.category(ch) == "Cf" else " ")', '" "'),
    ("views: approve button state - status check dropped", "app/workflow.py",
     "                self._refuse_if_safety(case)\n                if case.get(\"decision\") == MIXED:", "                if case.get(\"decision\") == MIXED:"),
]


def main() -> int:
    survived = []
    for name, rel, old, new in MUTANTS:
        path = ROOT / rel
        src = path.read_text()
        if old not in src:
            print(f"SKIP (pattern not found): {name}")
            survived.append(name + " [pattern not found]")
            continue
        path.write_text(src.replace(old, new, 1))
        try:
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "tests/test_safety_gate.py"], cwd=ROOT,
                               capture_output=True, text=True)
        finally:
            path.write_text(src)
        killed = r.returncode != 0
        print(("KILLED  " if killed else "SURVIVED"), name)
        if not killed:
            survived.append(name)
    print(f"\n{len(MUTANTS) - len(survived)}/{len(MUTANTS)} mutants killed")
    return 1 if survived else 0


if __name__ == "__main__":
    raise SystemExit(main())
