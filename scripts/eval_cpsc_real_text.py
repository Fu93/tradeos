"""Run the Safety Gate on real consumer hazard reports (CPSC SaferProducts.gov sample): keyword-only, optionally + AI.

  python scripts/eval_cpsc_real_text.py                         # keyword layer only, no network
  python scripts/eval_cpsc_real_text.py --base-url https://integrate.api.nvidia.com/v1 --model openai/gpt-oss-20b \
      --key-env NVIDIA_API_KEY                                  # + the opt-in AI layer (escalate-only OR)

Input: docs/eval/cpsc_real_text_sample.jsonl (built by scripts/cpsc_build_sample.py, labelled by hand before this
script was first run). These are reports TO A REGULATOR, not merchant support traffic, and every published report
describes a harm or a risk of harm, so this set measures RECALL only (no benign rows). The keyword layer gets no
intent-LLM reading (llm_reason=None), as in scripts/eval_safety_ai.py. Nothing here changes app logic and the
keyword patterns were not tuned on this set. Never prints keys.
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

from app.safety import assess  # noqa: E402
from app.safety_ai import LLMSafetyClassifier  # noqa: E402

DATA = ROOT / "docs/eval/cpsc_real_text_sample.jsonl"


def load(path: Path = DATA) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def product_of(row: dict) -> dict:
    return {"sku": row["report_no"], "name": row["product"], "category": row["product_category"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url")
    ap.add_argument("--model")
    ap.add_argument("--key-env", help="NAME of the env var holding the key")
    ap.add_argument("--out", default=str(ROOT / "docs/eval/cpsc_real_text_results.json"))
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=30.0)
    a = ap.parse_args()
    rows = load()
    use_ai = bool(a.base_url and a.model and a.key_env)
    key = os.environ.get(a.key_env or "", "") if use_ai else ""
    if use_ai and not key:
        print(f"env var {a.key_env} is empty", file=sys.stderr)
        return 2

    def one(row: dict) -> dict:
        prod = product_of(row)
        kw = assess(row["message"], prod, None)
        res = {"id": row["id"], "report_no": row["report_no"], "stratum": row["stratum"], "label": row["label_escalate"],
               "label_basis": row["label_basis"], "borderline": row["label_borderline"], "product_class": kw.product_class,
               "keyword": kw.flagged, "keyword_trigger": kw.trigger}
        if use_ai:
            c = LLMSafetyClassifier(key, a.base_url, a.model, timeout=a.timeout)
            v = None
            for attempt in range(3):  # retry transient errors in the EVAL only (the live layer does not retry)
                v = c.classify(row["message"], prod)
                if v is not None:
                    break
                time.sleep(2 * (attempt + 1))
            res.update({"ai_ok": v is not None, "ai": bool(v and v.escalate), "ai_hazard": v.hazard if v else None,
                        "ai_error": c.last_error if v is None else None})
            res["combined"] = res["keyword"] or res["ai"]
        return res

    with ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(one, rows))
    pos = [r for r in res if r["label"] == 1]
    neg = [r for r in res if r["label"] == 0]
    layers = ["keyword"] + (["ai", "combined"] if use_ai else [])
    out = {"dataset": "cpsc_real_text_sample.jsonl", "n": len(res), "n_pos": len(pos), "n_neg": len(neg),
           "model": a.model if use_ai else None, "base_url_host": a.base_url.split("/")[2] if use_ai else None,
           "ai_errors": sum(1 for r in res if not r.get("ai_ok", True)) if use_ai else None, "rows": res}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"n={len(res)} pos={len(pos)} neg={len(neg)} ai={'on' if use_ai else 'off'} ai_errors={out['ai_errors']}")
    for name in layers:
        miss = sum(1 for r in pos if not r[name])
        fp = sum(1 for r in neg if r[name])
        print(f"{name:9s} miss {miss}/{len(pos)} = {100 * miss / len(pos):.1f}%" + (f" | FP {fp}/{len(neg)}" if neg else ""))
    for key_name in ("stratum", "label_basis", "product_class"):
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in pos:
            groups[str(r[key_name])].append(r)
        print(f"\nmisses by {key_name}:")
        for g, rs in sorted(groups.items()):
            print(f"  {g:30s} n={len(rs):3d} " + " ".join(f"{n}={sum(not r[n] for r in rs)}" for n in layers))
    nb = [r for r in pos if not r["borderline"]]
    print(f"\nexcluding {len(pos) - len(nb)} borderline rows: " + " ".join(
        f"{n} miss {sum(not r[n] for r in nb)}/{len(nb)}" for n in layers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
