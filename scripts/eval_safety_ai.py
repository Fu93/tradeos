"""Measure the Safety Gate on our own safety dataset: keyword-only vs keyword + AI layer.

  python scripts/eval_safety_ai.py --base-url https://integrate.api.nvidia.com/v1 --model openai/gpt-oss-20b \
      --key-env NVIDIA_API_KEY --out docs/eval/safety_ai_results.json

Labels were written by us (scripts/safety_eval_data.py); this is NOT real customer traffic. Miss = a label-1 row
that is not escalated; false positive = a label-0 row that is escalated. The keyword layer is run with
llm_reason=None (the intent LLM is not part of this measurement). Never prints keys.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.safety import assess  # noqa: E402
from app.safety_ai import LLMSafetyClassifier  # noqa: E402
from safety_eval_data import PRODUCTS, ROWS  # noqa: E402


def rate(num: int, den: int) -> str:
    return f"{num}/{den} = {100 * num / den:.1f}%" if den else "n/a"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--key-env", required=True, help="NAME of the env var holding the key")
    ap.add_argument("--out", default=str(ROOT / "docs/eval/safety_ai_results.json"))
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--sleep", type=float, default=0.0, help="seconds between calls per worker (throttle)")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--dump-dataset", action="store_true")
    a = ap.parse_args()
    if a.dump_dataset:
        with open(ROOT / "docs/eval/safety_ai_dataset.jsonl", "w", encoding="utf-8") as f:
            for i, (cat, pk, lang, msg, label) in enumerate(ROWS, 1):
                f.write(json.dumps({"id": i, "category": cat, "product": PRODUCTS[pk]["name"], "product_category":
                                    PRODUCTS[pk]["category"], "language": lang, "message": msg, "label_escalate": label},
                                   ensure_ascii=False) + "\n")
        return 0
    key = os.environ.get(a.key_env, "")
    if not key:
        print(f"env var {a.key_env} is empty", file=sys.stderr)
        return 2

    def one(row):
        cat, pk, lang, msg, label = row
        prod = PRODUCTS[pk]
        kw = assess(msg, prod, None).flagged
        c = LLMSafetyClassifier(key, a.base_url, a.model, timeout=a.timeout)
        v = None
        for attempt in range(3):  # retry transient errors in the EVAL only (the live layer does not retry)
            v = c.classify(msg, prod)
            if v is not None:
                break
            time.sleep(2 * (attempt + 1))
        if a.sleep:
            time.sleep(a.sleep)
        return {"category": cat, "language": lang, "product": prod["name"], "message": msg, "label": label,
                "keyword": kw, "ai_ok": v is not None, "ai": bool(v and v.escalate), "ai_hazard": v.hazard if v else None,
                "ai_error": c.last_error if v is None else None}

    with ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(one, ROWS))
    for r in res:
        r["combined"] = r["keyword"] or r["ai"]  # escalate-only OR; an AI error contributes False (keyword stands)
    pos = [r for r in res if r["label"] == 1]
    neg = [r for r in res if r["label"] == 0]
    out = {"model": a.model, "base_url_host": a.base_url.split("/")[2], "n": len(res), "n_pos": len(pos), "n_neg": len(neg),
           "ai_errors": sum(1 for r in res if not r["ai_ok"]), "rows": res}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"model={a.model} n={len(res)} pos={len(pos)} neg={len(neg)} ai_errors={out['ai_errors']}")
    for name in ("keyword", "ai", "combined"):
        miss = sum(1 for r in pos if not r[name])
        fp = sum(1 for r in neg if r[name])
        print(f"{name:9s} miss rate {rate(miss, len(pos))} | false-positive rate {rate(fp, len(neg))}")
    print("\nby category (miss keyword / miss combined | FP keyword / FP combined):")
    cats = defaultdict(list)
    for r in res:
        cats[r["category"]].append(r)
    for c, rs in cats.items():
        p = [r for r in rs if r["label"] == 1]
        n = [r for r in rs if r["label"] == 0]
        print(f"  {c:24s} pos={len(p):2d} miss {sum(not r['keyword'] for r in p)}/{sum(not r['combined'] for r in p)}"
              f" | neg={len(n):2d} fp {sum(r['keyword'] for r in n)}/{sum(r['combined'] for r in n)}")
    print("\nCOMBINED misses:")
    for r in pos:
        if not r["combined"]:
            print("  -", r["category"], r["language"], r["message"][:90])
    print("\nCOMBINED false positives (AI-added only):")
    for r in neg:
        if r["combined"] and not r["keyword"]:
            print("  -", r["category"], r["language"], r["message"][:90])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
