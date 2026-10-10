"""Held-out v3 report: v3.1 (k1 primary, k3/k5) vs v3 frozen 04b65fc and rules 0.2.0. Writes heldout-v3-summary.json and
prints markdown sections used in heldout-v3-results.md."""
import json, statistics, sys
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts/v3")]
from eval_v3 import wilson  # noqa
E = ROOT / "docs/eval/v3"; T = "CREATE_SUPPLIER_TASK"
L = json.loads((E / "heldout-v3-labels.json").read_text())["labels"]
JN = json.loads((E / "judge-heldout_v3-N.json").read_text())["labels"]; JM = json.loads((E / "judge-heldout_v3-M.json").read_text())["labels"]
noreq = {i for i, v in L.items() if v["slice"] == "complaint_only" or (JN[i]["speech_act"] == JM[i]["speech_act"] == "COMPLAINT_ONLY")}
safety = {i for i, v in L.items() if v["safety_case"]}
RUNS = {"v3.1 k1 (primary)": ("results/heldout_v3-v3-final.json", "k1"), "v3.1 k3": ("results/heldout_v3-v3-final.json", "k3"),
        "v3.1 k5": ("results/heldout_v3-v3-final.json", "k5"), "v3 frozen 04b65fc (k1)": ("results/heldout_v3-v3frozen04b65fc-final.json", "k1"),
        "rules 0.2.0": ("results/heldout_v3-baseline020-final.json", "k1")}
SL = ["buyer_vs_seller", "order_conflict", "multi_item", "safety", "intent_revision", "complaint_only", "normalisation", "normal_task", "other"]
out = {}
for name, (f, k) in RUNS.items():
    R = json.loads((E / f).read_text()); res = R["results"]
    act = {i: r["actions"].get(k, r["action1"]) for i, r in res.items() if i in L}
    n = len(act); strict = sum(act[i] == L[i]["required_action"] for i in act); len_ = sum(act[i] in L[i]["acceptable_actions"] for i in act)
    pred = [i for i in act if act[i] == T]; true = [i for i in act if L[i]["required_action"] == T]
    tp = [i for i in pred if L[i]["required_action"] == T]; neg = [i for i in act if T not in L[i]["acceptable_actions"]]
    ft = [i for i in pred if i in neg]
    saf = [i for i in act if i in safety]; nr = [i for i in act if i in noreq]
    lat = [r["latency_s"] for r in res.values() if r.get("latency_s") is not None]
    errs = [{"id": i, "lang": L[i]["lang"], "kind": L[i]["kind"], "pred": act[i], "label": L[i]["required_action"],
             "acceptable": L[i]["acceptable_actions"], "rule": res[i].get("rule1", "0.2.0"), "reason": (res[i].get("reason") or "")[:150]}
            for i in act if act[i] not in L[i]["acceptable_actions"]]
    out[name] = {"n": n, "strict": strict, "strict_ci": wilson(strict, n), "lenient": len_, "lenient_ci": wilson(len_, n),
                 "task_pred": len(pred), "task_tp": len(tp), "task_true": len(true),
                 "precision": round(len(tp) / len(pred), 3) if pred else None, "recall": round(len(tp) / len(true), 3),
                 "false_triggers": ft, "non_supplier_n": len(neg),
                 "safety_human": sum(act[i] == "HUMAN_REVIEW" for i in saf), "safety_n": len(saf),
                 "safety_automated": [i for i in saf if act[i] in (T, "DIRECT_WORKFLOW")],
                 "noreq_tasks": [i for i in nr if act[i] == T], "noreq_n": len(nr),
                 "slices": {s: [sum(act[i] in L[i]["acceptable_actions"] for i in act if L[i]["slice"] == s),
                                sum(1 for i in act if L[i]["slice"] == s)] for s in SL},
                 "by_lang": {lg: [sum(act[i] in L[i]["acceptable_actions"] for i in act if L[i]["lang"] == lg),
                                  sum(1 for i in act if L[i]["lang"] == lg)] for lg in ("en", "zh-Hant", "es", "de", "ja")},
                 "latency_median_s": round(statistics.median(lat), 1) if lat else None,
                 "latency_p90_s": round(sorted(lat)[int(.9 * len(lat))], 1) if lat else None,
                 "usage": R.get("meta", {}).get("usage"), "retries": R.get("meta", {}).get("retries"), "wall_s": R.get("meta", {}).get("wall_s"),
                 "errors": errs}
    o = out[name]
    o["bar_met"] = len(tp) >= 36 and len(pred) == len(tp) and not ft and len(neg) >= 183 and not o["safety_automated"]
(E / "heldout-v3-summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print("| run | correct (lenient) / n [Wilson 95%] | strict | tasks TP/pred (prec) | recall TP/true | false triggers / non-supplier | safety → human | tasks on no-request | bar |")
print("|---|---|---|---|---|---|---|---|---|")
for k, o in out.items():
    print(f"| {k} | {o['lenient']}/{o['n']} [{o['lenient_ci'][0]}–{o['lenient_ci'][1]}] | {o['strict']}/{o['n']} | {o['task_tp']}/{o['task_pred']} ({o['precision']}) | "
          f"{o['task_tp']}/{o['task_true']} ({o['recall']}) | {len(o['false_triggers'])}/{o['non_supplier_n']} {o['false_triggers']} | {o['safety_human']}/{o['safety_n']} | "
          f"{len(o['noreq_tasks'])}/{o['noreq_n']} | {'MET' if o['bar_met'] else 'not met'} |")
print("\n| slice | " + " | ".join(out) + " |\n|---|" + "---|" * len(out))
for s in SL:
    print(f"| {s} | " + " | ".join(f"{o['slices'][s][0]}/{o['slices'][s][1]}" for o in out.values()) + " |")
for k in ("v3.1 k1 (primary)",):
    print(f"\n### Errors, {k}\n\n| id | lang | kind | predicted | label (acceptable) | rule | reason |\n|---|---|---|---|---|---|---|")
    for e in out[k]["errors"]:
        print(f"| {e['id']} | {e['lang']} | {e['kind']} | {e['pred']} | {e['label']} ({'/'.join(e['acceptable'])}) | {e['rule']} | {e['reason']} |")
for k in out:
    o = out[k]; print(f"\n{k}: latency median {o['latency_median_s']} s p90 {o['latency_p90_s']} s; usage {o['usage']}; retries {o['retries']}; wall {o['wall_s']} s; errors by rule {dict(Counter(e['rule'] for e in o['errors']))}")
