"""Measure the Safety Gate on hazard-class products with the extractor TradeOS actually runs.

    python scripts/eval_gate_phrasings.py                 # the extractor .env configures (the LLM if LLM_API_KEY is set)
    python scripts/eval_gate_phrasings.py --keyword-only  # offline: the deterministic keyword fallback
    python scripts/eval_gate_phrasings.py --pace 2.5      # seconds between model calls (Groq free tier: 30 a minute)

For every message in docs/eval/gated-phrasings.json the extractor reads it once (intent and reason, exactly as in a
real case), then the gate judges it on one product of each hazard class (kettle, camping gas stove, power bank,
power strip). Reported per group:

* fault_missed_by_words: faults described in words that are on none of the gate's lists. "words" = the 3.2 rule
  (word lists, plus a DAMAGED reading); "gate" = 3.3 (also any reading other than wrong size, wrong item or a change of
  mind). Higher is better.
* fault_caught_by_words: the same, for faults the word lists do know.
* benign: returns that say nothing about how the product works. A flag here is a false positive: a person reads a
  harmless return. Lower is better, but a false positive costs a minute of someone's time, a miss does not.

A live run refuses to mix extractors: without LLM_API_KEY it stops (use --keyword-only for the offline figures), and if
the model fails on any message (quota, timeout: TradeOS then falls back to the keyword reader) it stops and writes
nothing, because a "live" result half made of keyword readings would understate the false positives and the misses.

Each run writes docs/eval/gated-phrasings-results-<extractor>.json with every message's reading and outcome, so a
change of model or rule can be compared line by line. Nothing here decides anything or touches PayPal.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.intent import KeywordIntentExtractor, LLMIntentExtractor, build_extractor  # noqa: E402
from app.safety import FAULT_REASONS, SAFETY_RULE_VERSION, assess  # noqa: E402

PRODUCTS = {
    "MAINS_HEATING": {"name": "Electric Kettle 1.7L",
                      "category": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Electric Kettles"},
    "GAS": {"name": "Portable Camping Gas Stove", "category": "Sporting Goods > Outdoor Recreation > Camping Stoves"},
    "BATTERY_THERMAL": {"name": "20000mAh Power Bank", "category": "Electronics > Electronics Accessories > Power"},
    "MAINS_ELECTRIC": {"name": "6-Outlet Surge Protector Power Strip",
                       "category": "Electronics > Electronics Accessories > Power > Surge Protectors"},
}


class FallbackDetected(RuntimeError):
    """The model did not answer for a message, so the keyword fallback did: the live run is not a live run."""


def run(extractor, pace: float, live: bool = False) -> dict:
    phrases = json.loads((ROOT / "docs/eval/gated-phrasings.json").read_text())
    groups: dict[str, dict] = {}
    rows = []
    for group in ("fault_missed_by_words", "fault_caught_by_words", "benign"):
        words = gate = total = 0
        for message in phrases[group]:
            extraction = extractor.extract(message)
            if live and extraction.llm_unavailable:
                raise FallbackDetected(f"the model did not answer for {message!r} ({extraction.note}); "
                                       "nothing written. Wait for the quota to reset or raise --pace, then run again.")
            reason, intent = extraction.result.reason, extraction.result.intent
            for cls, product in PRODUCTS.items():
                by_words = assess(message, product, reason if reason in FAULT_REASONS else None).flagged
                by_gate = assess(message, product, reason, intent).flagged
                words += by_words
                gate += by_gate
                total += 1
                rows.append({"group": group, "message": message, "class": cls, "intent": intent, "reason": reason,
                             "words_3_2": by_words, "gate_3_3": by_gate, "extractor": extraction.extractor,
                             "llm_unavailable": extraction.llm_unavailable})
            if pace:
                time.sleep(pace)
        groups[group] = {"judgements": total, "flagged_by_words_3_2": words, "flagged_by_gate_3_3": gate}
    return {"rule_version": SAFETY_RULE_VERSION, "extractor": getattr(extractor, "name", type(extractor).__name__),
            "summary": groups, "rows": rows}


def main() -> int:
    argv = sys.argv[1:]
    pace = float(argv[argv.index("--pace") + 1]) if "--pace" in argv else 2.2
    if "--keyword-only" in argv:
        extractor, pace = KeywordIntentExtractor(), 0.0
    else:
        extractor = build_extractor(Settings.from_env())
        if not isinstance(extractor, LLMIntentExtractor):
            print("LLM_API_KEY is not set: no live run. Use --keyword-only for the offline figures.", file=sys.stderr)
            return 2
    try:
        result = run(extractor, pace, live=isinstance(extractor, LLMIntentExtractor))
    except FallbackDetected as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return 1
    name = "keyword" if isinstance(extractor, KeywordIntentExtractor) else "llm"
    out = ROOT / f"docs/eval/gated-phrasings-results-{name}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"extractor: {result['extractor']}  rule: {result['rule_version']}  -> {out.relative_to(ROOT)}")
    for group, s in result["summary"].items():
        print(f"  {group:24} words 3.2: {s['flagged_by_words_3_2']:3}/{s['judgements']}   "
              f"gate 3.3: {s['flagged_by_gate_3_3']:3}/{s['judgements']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
