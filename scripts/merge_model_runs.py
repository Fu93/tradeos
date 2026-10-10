"""Merge the production-model runs (openai/gpt-oss-20b via NVIDIA, eval-only) into docs/eval/routing-results.json
next to the earlier openai/gpt-oss-120b (Groq) runs, rescore everything and write a side-by-side comparison
(docs/eval/routing-model-comparison.md). Rules and labels are not touched; this only re-reads saved rows."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import eval_routing as ev  # noqa: E402

EVAL = ROOT / "docs/eval"
SRC_20B = {"original": EVAL / "routing-results-original-20b.json", "heldout": EVAL / "routing-results-heldout-20b.json"}
K20, K120 = "llm-20b-nvidia", "llm-120b-groq"


def main() -> None:
    res = json.loads((EVAL / "routing-results.json").read_text())
    for s, sres in res["sets"].items():
        runs = sres["runs"]
        if "llm" in runs:  # earlier run: 120b on Groq (meta predates the provider field)
            r = runs.pop("llm")
            r["meta"].update(provider="Groq", model="openai/gpt-oss-120b")
            r["meta"].setdefault("aborted", None)
            r["meta"].setdefault("n_planned", len(r["rows"]))
            r["meta"].setdefault("n_completed", len(r["rows"]))
            runs[K120] = r
        src = json.loads(SRC_20B[s].read_text())
        assert src["rule_version"] == res["rule_version"], "rule version changed"
        r20 = src["sets"][s]["runs"]["llm"]
        assert r20["meta"]["provider"] == "NVIDIA" and r20["meta"]["model"] == "openai/gpt-oss-20b"
        assert r20["meta"]["n_completed"] == r20["meta"]["n_planned"] and not r20["meta"]["aborted"], "incomplete 20b run"
        assert r20["meta"]["llm_fallbacks"] == 0
        sres["runs"] = {K20: r20, K120: runs[K120], "keyword": runs["keyword"]}
    res["model"] = "per run: see meta.provider / meta.model (production = openai/gpt-oss-20b on Groq)"
    ev.OUT_JSON = EVAL / "routing-results.json"
    ev.OUT_MD = EVAL / "routing-results.md"
    ev.finalize(res)
    (EVAL / "routing-model-comparison.md").write_text(comparison(res))
    print("ok")


def comparison(res: dict) -> str:
    p = ev.p
    L = ["# Model comparison — 20b (production model, via NVIDIA) vs 120b (via Groq)", "",
         f"Rules `{res['rule_version']}` and frozen labels identical for every run. Rates are `correct/n (%)`, "
         "key rates with a Wilson 95% CI. Sets are reported separately.", "",
         "* **20b** = `openai/gpt-oss-20b`, the production extractor model, but served by **NVIDIA** "
         "(integrate.api.nvidia.com, eval-only key) because the Groq free-tier daily token cap for 20b was used up "
         "and Groq quota is kept for the live app. Same model, **different provider** than production (Groq): "
         "serving stack / decoding defaults can differ, so this is the production model, not a production replay.",
         "* **120b** = `openai/gpt-oss-120b` via Groq (the earlier round-2 run). Not the production model.",
         "* The held-out set was **not** used for tuning: rules 0.2.0 were committed before any held-out run, and "
         "nothing was changed after seeing either model's results.", ""]
    spec = [("issue_type (after text checks)", "issue_type", True),
            ("customer_goal (after text checks)", "customer_goal", True),
            ("mixed flag", "mixed_flag", False),
            ("required_action strict", "action_strict", True),
            ("required_action lenient", "action_lenient", True),
            ("all three dimensions right", "all_three_strict", False),
            ("supplier-task precision", "task_precision", True),
            ("supplier-task recall (automatic)", "task_recall", True),
            ("false trigger on non-task cases", "false_trigger_non_task", True),
            ("should be human/clarify but automated", "automated_but_should_be_manual", True),
            ("duplicate rows that created a new task", "duplicate_new_task", False),
            ("task draft completeness", "completeness", False),
            ("automatic actions demoted by confidence", "demoted", False)]
    for s, sres in res["sets"].items():
        runs = sres["runs"]
        L += [f"## {ev.SET_TITLE[s]}", "", "| Metric | 20b via NVIDIA (production model) | 120b via Groq | keyword fallback |",
              "| --- | --- | --- | --- |"]
        for label, key, ci in spec:
            L.append(f"| {label} | " + " | ".join(p(runs[k]["overall"][key], ci) for k in (K20, K120, "keyword")) + " |")
        L.append("| latency p50 per case (ms) | " + " | ".join(str(runs[k]["overall"]["latency_p50"])
                                                          for k in (K20, K120, "keyword")) + " |")
        a = {r["id"]: r for r in runs[K20]["rows"]}
        b = {r["id"]: r for r in runs[K120]["rows"]}
        o = runs[K20]["overall"]
        L += ["", f"**Every 20b required_action outside acceptable_actions — {s}**", "",
              "| id | lang | label issue/goal → action | 20b issue/goal → action | conf | kind | deciding rule (decided_by) | 120b action |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        wrong = [r for r in runs[K20]["rows"] if r["action"] not in r["acceptable"]]
        for r in wrong:
            kind = ("FALSE TRIGGER" if r["id"] in o["false_triggers"] else "MISSED TRIGGER" if r["id"] in o["missed_triggers"]
                    else "AUTOMATED, SHOULD BE MANUAL" if r["id"] in o["automated_manual_ids"] else "wrong manual route")
            L.append(f"| {r['id']} | {r['lang']} | {r['issue_type']}/{r['customer_goal']}{'/mixed' if r['mixed'] else ''} → "
                     f"{r['required_action']} | {r['pred_issue']}/{r['pred_goal']}{'/mixed' if r['pred_mixed'] else ''} → "
                     f"{r['action']} | {r['confidence']} | {kind} | {(r['decided_by'] or '').replace('|', '/')[:200]} | "
                     f"{b.get(r['id'], {}).get('action')} |")
        if not wrong:
            L.append("| — | | none | | | | | |")
        diff = [i for i in a if i in b and a[i]["action"] != b[i]["action"]]
        both_wrong = [r["id"] for r in wrong if b.get(r["id"]) and b[r["id"]]["action"] not in r["acceptable"]]
        L += ["", f"Cases where the two models chose a different action: {len(diff)}/{len(a)} "
              f"({', '.join(diff) or 'none'}). Wrong for both models: {', '.join(both_wrong) or 'none'}.", ""]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
