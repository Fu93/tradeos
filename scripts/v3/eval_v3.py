"""Evaluate routing v3 (or the 0.2.0 baseline) on a v3-labelled set. ALL LLM calls go to NVIDIA with the PRODUCTION
extractor model openai/gpt-oss-20b. Counted retries; an LLM failure after retries ABORTS the run (never a fallback).

  python scripts/v3/eval_v3.py --set dev_pairs --labels designed|judgeB|<path> [--k 5] [--pipeline v3|baseline020]
                               [--tag NAME] [--workers 6]

Output: docs/eval/v3/results/<set>-<pipeline>-<tag>.json (checkpointed per message; re-run the same command to resume).
For held-out v2 the brief allows exactly ONE run of the frozen build (tag 'final'); any later run must be tagged 'tuned-*'.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts/v3")]
from judge_label import load  # noqa: E402

from app.routing_v3 import (RULE_VERSION_V3, ContextV3, ExtractionUnavailable, LLMExtractorV3,  # noqa: E402
                            agreement_gate, decide_v3)

NV = "https://integrate.api.nvidia.com/v1"
MODEL = "openai/gpt-oss-20b"
TODAY = date(2026, 10, 9)
E = ROOT / "docs/eval/v3"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (round(100 * (c - h), 1), round(100 * (c + h), 1))


def load_labels(set_name: str, spec: str) -> dict:
    if set_name == "heldout_v4":
        L = json.loads((E / "heldout-v4-labels.json").read_text())["labels"]
        return {k: {"required_action": v["required_action"], "acceptable_actions": v["acceptable_actions"]} for k, v in L.items()}
    if set_name == "heldout_v3":
        L = json.loads((E / "heldout-v3-labels.json").read_text())["labels"]
        return {k: {"required_action": v["required_action"], "acceptable_actions": v["acceptable_actions"]} for k, v in L.items()}
    if set_name == "dev_v31_regress":
        return {c["id"]: {"required_action": c["label"], "acceptable_actions": [c["label"]]}
                for c in json.loads((E / "dev-v31-regression.json").read_text())["cases"]}
    if spec == "designed":
        design = json.loads((E / "heldout-v2-design.json").read_text())
        out = {}
        for c in design["cells"]:
            out[c["id"]] = {"required_action": c["designed_action"], "acceptable_actions": [c["designed_action"]]}
        for p in design["pairs"]:
            for i, s in enumerate("AB"):
                out[f"{p['pair_id']}{s}"] = {"required_action": p["designed"][i], "acceptable_actions": [p["designed"][i]]}
        return out
    if spec == "old":  # round-2 labels (pre-v3 taxonomy): DEV ONLY, approximate
        import eval_routing as ev
        src = "original" if set_name == "dev_original" else "heldout"
        return {c["id"]: {"required_action": c["required_action"],
                          "acceptable_actions": sorted(set(c["acceptable"]) | {c["required_action"]})} for c in ev.load_set(src)}
    path = E / f"judge-{set_name}-B.json" if spec == "judgeB" else Path(spec)
    j = json.loads(path.read_text())
    labels = j.get("labels", j)
    labels = {k: (v.get("B") or v.get("A") or v) if isinstance(v, dict) and ("A" in v or "B" in v) else v
              for k, v in labels.items()}
    return {k: {"required_action": v["required_action"],
                "acceptable_actions": sorted(set(v.get("acceptable_actions") or []) | {v["required_action"]})}
            for k, v in labels.items() if isinstance(v, dict) and v.get("required_action")}


class Retrying:
    """Counted retries around the production extractor (429 / 5xx / transport / schema)."""

    def __init__(self, llm: LLMExtractorV3, attempts: int = 5):
        self.llm, self.attempts, self.retries, self.lock = llm, attempts, 0, threading.Lock()

    def sample(self, msg: str, n: int, temp: float):
        last = None
        for a in range(self.attempts):
            try:
                return self.llm.sample(msg, n, temp)
            except ExtractionUnavailable as exc:
                last = exc
                with self.lock:
                    self.retries += 1
                time.sleep(min(60, 4 * 2 ** a))
        raise last


def run_v3(item: dict, ext: Retrying, k: int, temp: float = 0.6) -> dict:
    ctx = ContextV3(item["customer"], item["linked_order"])
    t = time.perf_counter()
    first = ext.sample(item["message"], 1, 0.0)[0]
    d = decide_v3(first, item["message"], ctx, TODAY)
    rec = {"action1": d.action, "rule1": d.rule, "family": d.family, "reason": d.reason, "derived": d.derived,
           "extraction": first.raw, "agreement": None}
    if d.action == "CREATE_SUPPLIER_TASK" and k > 1:
        extras = ext.sample(item["message"], k - 1, temp)
        votes, notes = [], []
        for e in extras:
            dd = decide_v3(e, item["message"], ctx, TODAY)
            votes.append(f"{dd.action}/{dd.family}")
            notes.append(f"{dd.rule}: {dd.reason[:120]}")
        rec["agreement"] = {"first": f"{d.action}/{d.family}", "extras": votes, "notes": notes,
                            "extra_extractions": [e.raw for e in extras]}
    rec["latency_s"] = round(time.perf_counter() - t, 2)
    rec["actions"] = {f"k{kk}": gate_action(rec, kk) for kk in (1, 3, 5) if kk <= max(1, k)}
    return rec


def gate_action(rec: dict, kk: int) -> str:
    if rec["action1"] != "CREATE_SUPPLIER_TASK" or kk == 1 or not rec["agreement"]:
        return rec["action1"]
    votes = [rec["agreement"]["first"]] + rec["agreement"]["extras"][: kk - 1]
    return rec["action1"] if all(v == votes[0] for v in votes) else "HUMAN_REVIEW"


def run_baseline(item: dict, svc_box: dict) -> dict:
    from app.routing import CaseContext
    svc = svc_box["svc"]
    t = time.perf_counter()
    rid = svc.triage(item["message"], CaseContext(customer=item["customer"], linked_order_id=item["linked_order"]))
    rc = svc.store.get_case(rid)
    exn = str((rc.get("extraction") or {}).get("extractor", ""))
    if exn.startswith("keyword") or "unavailable" in exn:
        raise RuntimeError("baseline fell back to keywords: abort (never fallback)")
    status = rc["status"]
    act = {"DIRECT_WORKFLOW": "DIRECT_WORKFLOW", "NEEDS_CLARIFICATION": "CLARIFY_WITH_CUSTOMER",
           "NEEDS_HUMAN_REVIEW": "HUMAN_REVIEW", "SUPPLIER_REQUIRED": "CREATE_SUPPLIER_TASK",
           "SUPPLIER_TASK_OPEN": "CREATE_SUPPLIER_TASK"}[status]
    return {"action1": act, "status": status, "latency_s": round(time.perf_counter() - t, 2), "actions": {"k1": act},
            "reason": (rc.get("decision") or {}).get("reason") or rc.get("status_reason")}


def score(results: dict, labels: dict, key: str = "k1") -> dict:
    ids = [i for i in results if i in labels]
    n = len(ids)
    strict = sum(results[i]["actions"].get(key, results[i]["action1"]) == labels[i]["required_action"] for i in ids)
    lenient = sum(results[i]["actions"].get(key, results[i]["action1"]) in labels[i]["acceptable_actions"] for i in ids)
    T = "CREATE_SUPPLIER_TASK"
    pred_t = [i for i in ids if results[i]["actions"].get(key) == T]
    true_t = [i for i in ids if labels[i]["required_action"] == T]
    neg = [i for i in ids if T not in labels[i]["acceptable_actions"]]
    tp = [i for i in pred_t if labels[i]["required_action"] == T]
    ft = [i for i in pred_t if T not in labels[i]["acceptable_actions"]]
    errors = [{"id": i, "pred": results[i]["actions"].get(key), "label": labels[i]["required_action"],
               "acceptable": labels[i]["acceptable_actions"], "rule": results[i].get("rule1"),
               "reason": (results[i].get("reason") or "")[:160]}
              for i in ids if results[i]["actions"].get(key) not in labels[i]["acceptable_actions"]]
    return {"n": n, "strict": strict, "strict_ci": wilson(strict, n), "lenient": lenient, "lenient_ci": wilson(lenient, n),
            "task_pred": len(pred_t), "task_true": len(true_t), "task_tp": len(tp),
            "task_precision": round(len(tp) / len(pred_t), 3) if pred_t else None,
            "task_recall": round(len(tp) / len(true_t), 3) if true_t else None,
            "false_triggers": ft, "non_supplier_n": len(neg), "errors": errors}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", required=True)
    ap.add_argument("--labels", default="judgeB")
    ap.add_argument("--pipeline", default="v3", choices=["v3", "baseline020"])
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--tag", default="dev")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--only", default="")
    ap.add_argument("--temp", type=float, default=0.6, help="temperature of the k-1 agreement samples")
    a = ap.parse_args()
    if a.set in ("heldout_v2", "heldout_v3", "heldout_v4") and not (a.tag == "final" or a.tag.startswith("tuned")):
        sys.exit("held-out v2 runs must be tagged 'final' (once) or 'tuned-*'")
    items = load(a.set)
    if a.only:
        keep = set(a.only.split(","))
        items = [i for i in items if i["id"] in keep]
    labels = load_labels(a.set, a.labels)
    out = E / "results" / f"{a.set}-{a.pipeline}-{a.tag}.json"
    out.parent.mkdir(exist_ok=True)
    res = json.loads(out.read_text()) if out.exists() else {"meta": {}, "results": {}}
    todo = [i for i in items if i["id"] not in res["results"]]
    print(f"{a.set} {a.pipeline} tag={a.tag}: {len(items)} items, {len(todo)} to run", flush=True)
    key = os.environ["NVIDIA_API_KEY"]
    llm = LLMExtractorV3(key, NV, MODEL, timeout=180.0, supports_n=True)
    ext = Retrying(llm)
    lock = threading.Lock()
    if a.pipeline == "baseline020":
        import tempfile
        from app.routing import RoutingConfig, RoutingService, RoutingStore
        from app.routing_extract import LLMRoutingExtractor
        from eval_routing import RetryTransport
        tmp = tempfile.mkdtemp()

        def worker(item):
            box = getattr(_tl, "box", None)
            if box is None:
                st = RoutingStore(f"{tmp}/r{threading.get_ident()}.db")
                st.init(reset=True)
                box = _tl.box = {"svc": RoutingService(st, LLMRoutingExtractor(key, NV, MODEL, timeout=180.0, transport=RetryTransport()), RoutingConfig(), today=lambda: TODAY)}
            return run_baseline(item, box)
        _tl = threading.local()
    else:
        def worker(item):
            return run_v3(item, ext, a.k, a.temp)
    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as pool:
        futs = {pool.submit(worker, it): it for it in todo}
        for f in as_completed(futs):
            it = futs[f]
            try:
                r = f.result()
            except Exception as exc:  # abort: never fall back
                print(f"ABORT on {it['id']}: {type(exc).__name__}: {str(exc)[:200]}", flush=True)
                pool.shutdown(cancel_futures=True)
                with lock:
                    out.write_text(json.dumps(res, ensure_ascii=False, indent=1))
                sys.exit(2)
            with lock:
                res["results"][it["id"]] = r
                out.write_text(json.dumps(res, ensure_ascii=False, indent=1))
            lab = labels.get(it["id"], {}).get("required_action", "?")
            print(f"{it['id']} {r['action1']} label={lab}", flush=True)
    res["meta"] = {"set": a.set, "pipeline": a.pipeline, "tag": a.tag, "model": MODEL, "provider": "NVIDIA",
                   "rules": RULE_VERSION_V3 if a.pipeline == "v3" else "0.2.0", "k": a.k, "agreement_temp": a.temp, "labels": a.labels,
                   "usage": llm.usage, "retries": ext.retries, "wall_s": round(time.time() - t0, 1)}
    res["score"] = {kk: score(res["results"], labels, kk) for kk in ("k1", "k3", "k5")
                    if all(kk in r["actions"] for r in res["results"].values())}
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    for kk, s in res["score"].items():
        print(kk, {x: s[x] for x in s if x not in ("errors",)})


if __name__ == "__main__":
    main()
