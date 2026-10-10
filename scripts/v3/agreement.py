"""Dual-judge agreement (Cohen's kappa per field) + adjudication merge + review CSV for held-out v2.

  python scripts/v3/agreement.py stats            # kappas, disagreement list -> docs/eval/v3/heldout-v2-disagreements.json
  python scripts/v3/agreement.py freeze           # merge judges + author adjudication -> heldout-v2-labels.json + review CSV
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "scripts/v3")]
from judge_label import load  # noqa: E402

E = ROOT / "docs/eval/v3"
FAM = {"REFUND": "REFUND", "REPAIR": "WARRANTY", "REPLACE_SAME": "WARRANTY", "SEND_PART": "WARRANTY",
       "EXCHANGE_VARIANT": "EXCHANGE", "RESHIP": "FULFILMENT", "INFORMATION": "INFO"}
STATUS = "LLM-generated, dual-LLM-labelled, author-adjudicated, pending human review"
T = "CREATE_SUPPLIER_TASK"


def kappa(a: list, b: list) -> float | None:
    n = len(a)
    if n == 0:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return round((po - pe) / (1 - pe), 3) if pe < 1 else 1.0


def fields(l: dict) -> dict:
    items = l.get("items") or []
    g = [x["goal"] for it in items[:1] for x in it.get("goals") or []]
    return {"speech_act": l["speech_act"], "primary_issue": items[0]["issue_type"] if items else "NONE",
            "goal_family": FAM.get(g[0], "NONE") if g else "NONE", "multi_item": len(items) >= 2,
            "safety": l["safety"] != "NONE", "required_action": l["required_action"]}


def meta() -> dict:
    d = json.loads((E / "heldout-v2-design.json").read_text())
    m = {c["id"]: {"kind": c["kind"], "lang": c["lang"], "generator": c["generator"], "designed": c["designed_action"],
                   "tags": c.get("tags", [])} for c in d["cells"]}
    for p in d["pairs"]:
        for i, s in enumerate("AB"):
            m[f"{p['pair_id']}{s}"] = {"kind": "pair:" + p["pair_type"], "lang": p["lang"], "generator": p["generator"],
                                       "designed": p["designed"][i], "tags": [p["pair_type"]]}
    return m


PRIMARY = ("B", "C")  # B = nvidia/nemotron-3-ultra (NVIDIA), C = meta/muse-glimmer-30b (Meta)
SUPPLEMENTARY = "A"   # z-ai/glm-5.3: account rate-limited (HTTP 429) after 71 labels; reported on its subset only
JUDGE_MODELS = {"A": "z-ai/glm-5.3", "B": "nvidia/nemotron-3-ultra-550b-a55b", "C": "meta/muse-glimmer-30b"}


def judge_labels(j: str) -> dict:
    f = E / f"judge-heldout_v2-{j}.json"
    if not f.exists():
        return {}
    return {k: v[j] for k, v in json.loads(f.read_text())["labels"].items() if j in v}


def both() -> tuple[dict, dict]:
    return judge_labels(PRIMARY[0]), judge_labels(PRIMARY[1])


FIELDS = ["speech_act", "primary_issue", "goal_family", "multi_item", "safety", "required_action"]


def pair_stats(X: dict, Y: dict, ids: list) -> dict:
    fx, fy = {i: fields(X[i]) for i in ids}, {i: fields(Y[i]) for i in ids}
    return {"n": len(ids), "fields": {f: {"kappa": kappa([fx[i][f] for i in ids], [fy[i][f] for i in ids]),
                                          "raw": round(sum(fx[i][f] == fy[i][f] for i in ids) / max(1, len(ids)), 3)}
                                      for f in FIELDS}}


def stats() -> dict:
    """Adapted protocol (disclosed): judge B (NVIDIA Nemotron-ultra) on all items; second LLM judges A (GLM-5.3) and
    C (Meta muse-glimmer) on the subsets they completed before the cutoff (NVIDIA account throttling); the design-grid
    intended action (author-specified before generation) on all items. Any disagreement -> author adjudication."""
    items = {i["id"]: i for i in load("heldout_v2")}
    M = meta()
    J = {j: judge_labels(j) for j in "ABC"}
    B = J["B"]
    out = {"n_items": len(items), "coverage": {j: len(v) for j, v in J.items()}, "missing_B": [i for i in items if i not in B]}
    out["B_vs_A"] = pair_stats(B, J["A"], [i for i in items if i in B and i in J["A"]])
    out["B_vs_C"] = pair_stats(B, J["C"], [i for i in items if i in B and i in J["C"]])
    out["A_vs_C"] = pair_stats(J["A"], J["C"], [i for i in items if i in J["A"] and i in J["C"]])
    ids = [i for i in items if i in B]
    out["B_vs_design_action"] = {"n": len(ids), "kappa": kappa([B[i]["required_action"] for i in ids], [M[i]["designed"] for i in ids]),
                                 "raw": round(sum(B[i]["required_action"] == M[i]["designed"] for i in ids) / max(1, len(ids)), 3)}
    sec = [i for i in ids if i in J["A"] or i in J["C"]]
    out["second_llm_judge_coverage"] = len(sec)
    by = defaultdict(list)
    for i in sec:
        by[M[i]["generator"]].append(i)
    def second(i):
        return (J["A"].get(i) or J["C"].get(i))["required_action"]
    out["B_vs_second_judge_action_by_generator"] = {g: {"n": len(v), "kappa": kappa([B[i]["required_action"] for i in v], [second(i) for i in v]),
                                                        "raw": round(sum(B[i]["required_action"] == second(i) for i in v) / len(v), 3)}
                                                    for g, v in by.items()}
    dis = []
    for i in items:
        votes = {"B": B.get(i, {}).get("required_action"), "A": J["A"].get(i, {}).get("required_action"),
                 "C": J["C"].get(i, {}).get("required_action"), "design": M[i]["designed"]}
        present = {k: v for k, v in votes.items() if v}
        if len(set(present.values())) > 1 or "B" not in present:
            dis.append({"id": i, "lang": M[i]["lang"], "kind": M[i]["kind"], "tags": M[i]["tags"], "votes": present,
                        "B_rule": B.get(i, {}).get("deciding_rule"), "B_reason": str(B.get(i, {}).get("reasoning", ""))[:500],
                        "A_reason": str(J["A"].get(i, {}).get("reasoning", ""))[:300],
                        "C_reason": str(J["C"].get(i, {}).get("reasoning", ""))[:300],
                        "message": items[i]["message"], "customer": items[i]["customer"], "linked_order": items[i]["linked_order"]})
    out["n_to_adjudicate"] = len(dis)
    out["confusion_B_vs_design"] = Counter(f"{B[i]['required_action']}|{M[i]['designed']}" for i in ids
                                           if B[i]["required_action"] != M[i]["designed"]).most_common()
    (E / "heldout-v2-disagreements.json").write_text(json.dumps(dis, ensure_ascii=False, indent=1))
    (E / "heldout-v2-agreement.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def freeze() -> None:
    A, B = both()
    items = {i["id"]: i for i in load("heldout_v2")}
    M = meta()
    adj = json.loads((E / "heldout-v2-adjudication.json").read_text())
    S = judge_labels(SUPPLEMENTARY)
    labels, csv_rows = {}, []
    for i, it in items.items():
        a, b = A.get(i), B.get(i)
        if i in adj:
            req = adj[i]["required_action"]
            acc = set(adj[i].get("acceptable_actions") or [req]) | {req}
            src, note = "author-adjudicated", adj[i]["reason"]
        elif a and all(x["required_action"] == a["required_action"] for x in (b, S.get(i)) if x) \
                and a["required_action"] == M[i]["designed"]:
            req = a["required_action"]
            accs = [set(x.get("acceptable_actions") or []) for x in (a, b, S.get(i)) if x]
            acc = set.intersection(*accs) | {req}
            src, note = "all labels agree (judge B + design" + (" + C" if b else "") + (" + A" if S.get(i) else "") + ")", ""
        else:
            raise SystemExit(f"{i}: not adjudicated and judges do not agree")
        if req != T:
            acc.discard(T)  # guide: CREATE_SUPPLIER_TASK is never acceptable for a non-task label
        labels[i] = {"required_action": req, "acceptable_actions": sorted(acc), "source": src, "note": note,
                     "judge_B_nemotron": a["required_action"] if a else None,
                     "judge_C_muse": b["required_action"] if b else None,
                     "judge_A_glm_subset": S.get(i, {}).get("required_action"),
                     "designed": M[i]["designed"], "lang": M[i]["lang"], "kind": M[i]["kind"], "generator": M[i]["generator"]}
    comp = {"n": len(labels), "by_required_action": Counter(l["required_action"] for l in labels.values()),
            "non_supplier": sum(T not in l["acceptable_actions"] for l in labels.values()),
            "by_lang": Counter(l["lang"] for l in labels.values()),
            "by_generator": Counter(l["generator"] for l in labels.values()),
            "by_source": Counter(l["source"] for l in labels.values()),
            "pairs": sum(l["kind"].startswith("pair:") for l in labels.values())}
    out = {"status": STATUS, "labelling_guide": "docs/eval/v3/labelling-guide-v3.md",
           "judges": {"primary": {k: JUDGE_MODELS[k] for k in PRIMARY}, "supplementary_subset": {"A": JUDGE_MODELS["A"]}}, "composition": comp,
           "messages": {i: items[i] for i in items}, "labels": labels}
    (E / "heldout-v2-labels.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=dict))
    # review CSV: all adjudicated rows + edge cases until ~40, covering every language
    pri = [i for i in labels if labels[i]["source"] == "author-adjudicated"]
    edge = [i for i in labels if i not in pri and (labels[i]["designed"] != labels[i]["required_action"]
                                                   or len(labels[i]["acceptable_actions"]) > 1)]
    rows = pri + edge
    for lg in ("en", "zh-Hant", "es", "de", "ja"):
        if not any(labels[i]["lang"] == lg for i in rows[:40]):
            rows.insert(0, next(i for i in labels if labels[i]["lang"] == lg))
    rows = list(dict.fromkeys(rows))[: max(40, len(pri))]
    path = E / "heldout-v2-review.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "lang", "kind", "customer", "linked_order", "message", "designed", "judge_B_nemotron", "judge_C_muse", "judge_A_glm_subset",
                    "final_required_action", "acceptable_actions", "label_source", "adjudication_note",
                    "human_verdict (agree/disagree)", "human_note"])
        for i in rows:
            l, it = labels[i], items[i]
            w.writerow([i, l["lang"], l["kind"], it["customer"], it["linked_order"] or "", it["message"], l["designed"],
                        l["judge_B_nemotron"], l["judge_C_muse"], l["judge_A_glm_subset"] or "", l["required_action"], "|".join(l["acceptable_actions"]), l["source"],
                        l["note"], "", ""])
    print(json.dumps(comp, indent=1, default=dict), "\nCSV rows:", len(rows), path)


if __name__ == "__main__":
    print(json.dumps(stats(), indent=1, ensure_ascii=False)[:3000] if sys.argv[1] == "stats" else freeze())
