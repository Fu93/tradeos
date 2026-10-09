"""Build docs/eval/v3/heldout-v2-results.md from the frozen labels and the two held-out runs (v3 final, 0.2.0 baseline)."""
import json, math, statistics, sys
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts/v3")]
from eval_v3 import score, wilson  # noqa
E = ROOT / "docs/eval/v3"
T = "CREATE_SUPPLIER_TASK"
LAB = json.loads((E / "heldout-v2-labels.json").read_text())
labels = LAB["labels"]
v3 = json.loads((E / "results/heldout_v2-v3-final.json").read_text())
base = json.loads((E / "results/heldout_v2-baseline020-final.json").read_text())


def cp_lower(k, n, a=0.05):  # Clopper-Pearson one-sided lower bound for k=n
    return round(100 * (a ** (1 / n)), 1) if k == n else None


def block(name, res, key="k1"):
    s = score(res["results"], labels, key)
    lat = [r["latency_s"] for r in res["results"].values()]
    neg = s["non_supplier_n"]
    task_errs = [e for e in s["errors"] if e["pred"] == T or e["label"] == T]
    tasks_ok = s["task_tp"]
    out = [f"### {name}", "",
           f"- lenient correct: **{s['lenient']}/{s['n']}** ({100*s['lenient']/s['n']:.1f}%, Wilson 95% CI {s['lenient_ci'][0]}–{s['lenient_ci'][1]}); "
           f"strict (= required action): {s['strict']}/{s['n']} (CI {s['strict_ci'][0]}–{s['strict_ci'][1]})",
           f"- supplier tasks: predicted {s['task_pred']}, correct {s['task_tp']} of {s['task_true']} required → precision "
           f"{s['task_precision']}, recall {s['task_recall']}",
           f"- false triggers (task where task is not acceptable): **{len(s['false_triggers'])}** of {neg} non-supplier"
           + (f" ({', '.join(s['false_triggers'])})" if s["false_triggers"] else ""),
           f"- latency per message: median {statistics.median(lat):.1f} s, p90 {sorted(lat)[int(0.9*len(lat))-1]:.1f} s"]
    return s, out


lines = ["# Held-out v2 results (single final run)", "",
         f"Labels: `heldout-v2-labels.json` — status **{LAB['status']}**. Composition: {json.dumps(LAB['composition'], default=dict)}", "",
         f"v3 build: {v3['meta'].get('rules')} · extractor `{v3['meta']['model']}` via {v3['meta']['provider']} · k={v3['meta']['k']} "
         f"(extra samples temp {v3['meta'].get('agreement_temp')}) · tag `final` (run once). Baseline: rules 0.2.0, same model/provider, run once.", ""]
summ = {}
for kk in ("k1", "k3", "k5"):
    if all(kk in r["actions"] for r in v3["results"].values()):
        s, out = block(f"v3, agreement gate {kk} " + ("(pre-registered primary)" if kk == "k1" else "(trade-off)"), v3, kk)
        summ[kk] = s
        lines += out + [""]
sb, out = block("rules 0.2.0 baseline (same set)", base)
lines += out + [""]
s1 = summ["k1"]
safety = [i for i, l in labels.items() if "V1" in str(l.get("note", "")) or "safety" in l["kind"]]
saf_ok = sum(v3["results"][i]["action1"] == "HUMAN_REVIEW" for i in safety if i in v3["results"])
lines += ["## Breakthrough bar", "",
          f"Bar: ≥36 auto/suggested supplier tasks with 0 errors and 0 false triggers on ≥183 non-supplier cases.", ""]
for kk, s in summ.items():
    ok = s["task_tp"] >= 36 and not s["false_triggers"] and s["non_supplier_n"] >= 183
    lines.append(f"- {kk}: {s['task_tp']} correct tasks / {s['task_pred']} predicted, false triggers {len(s['false_triggers'])} on "
                 f"{s['non_supplier_n']} → **{'MET' if ok else 'NOT met'}**"
                 + (f" (if met: precision lower bound {cp_lower(s['task_tp'], s['task_pred'])}% one-sided 95%)" if ok else ""))
lines += ["", f"Safety-designed cells routed to a human by v3: {saf_ok}/{len(safety)} (automated safety rules S1–S4 + model S2).", "",
          "## Per-error list (v3, k1)", "", "| id | lang | kind | predicted | required (acceptable) | rule | v3 reason |", "|---|---|---|---|---|---|---|"]
for e in s1["errors"]:
    l = labels[e["id"]]
    lines.append(f"| {e['id']} | {l['lang']} | {l['kind']} | {e['pred']} | {e['label']} ({'/'.join(e['acceptable'])}) | {e['rule']} | {e['reason'].replace('|','/')[:140]} |")
lines += ["", "## Per-error list (baseline 0.2.0)", "", "| id | predicted | required | reason |", "|---|---|---|---|"]
for e in sb["errors"]:
    lines.append(f"| {e['id']} | {e['pred']} | {e['label']} | {(e['reason'] or '').replace('|','/')[:120]} |")
by_lang = Counter(); by_lang_ok = Counter()
for i, l in labels.items():
    by_lang[l["lang"]] += 1; by_lang_ok[l["lang"]] += v3["results"][i]["actions"]["k1"] in l["acceptable_actions"]
lines += ["", "## v3 (k1) by language", "", " · ".join(f"{k}: {by_lang_ok[k]}/{v}" for k, v in by_lang.items()), "",
          "## Cost / usage", "",
          f"- v3 run: {v3['meta']['usage']} · counted retries {v3['meta']['retries']} · wall {v3['meta']['wall_s']} s",
          f"- baseline run: retries counted by transport; wall {base['meta']['wall_s']} s",
          "- Cost estimate uses Groq list price for gpt-oss-20b (production provider): $0.075 / 1M input, $0.30 / 1M output tokens."]
u = v3["meta"]["usage"]
cost = u["prompt_tokens"] / 1e6 * 0.075 + u["completion_tokens"] / 1e6 * 0.30
lines.append(f"- v3 tokens for {len(v3['results'])} messages (incl. agreement samples): ${cost:.4f} total ≈ ${cost/len(v3['results']):.5f}/message at Groq prices.")
(E / "heldout-v2-results.md").write_text("\n".join(lines) + "\n")
json.dump({"v3": {k: {x: s[x] for x in s if x != "errors"} for k, s in summ.items()}, "baseline": {x: sb[x] for x in sb if x != "errors"}},
          open(E / "heldout-v2-summary.json", "w"), indent=1)
print("\n".join(lines[:40]))
