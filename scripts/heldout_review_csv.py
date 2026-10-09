"""Write docs/eval/heldout-review.csv for the human spot-check.

Pre-run: proposed labels + a pre-selected priority_review set (edge cases, all five languages).
Post-run (--results docs/eval/routing-results.json): adds the pipeline's actions and also flags every
held-out row whose LLM route was wrong (labels themselves are never changed here)."""
import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRE_PRIORITY = {  # chosen BEFORE the run: hardest / most debatable rows, every language
    "H03", "H07", "H17", "H23", "H45", "H51",          # en
    "H04", "H10", "H13", "H34", "H41", "H53",          # de
    "H05", "H50", "H54", "H60",                        # ja
    "H25", "H30", "H38", "H47",                        # zh-Hant
    "H39", "H48", "H52",                               # es
}
MAX_PRIORITY = 30


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results")
    args = ap.parse_args()
    labels = json.loads((ROOT / "docs/eval/heldout-labels.json").read_text())["cases"]
    preds: dict[str, dict] = {}
    if args.results:
        res = json.loads((ROOT / args.results).read_text())
        for mode, run in res["sets"]["heldout"]["runs"].items():
            for r in run["rows"]:
                preds.setdefault(r["id"], {})[mode] = r
    wrong = [c["id"] for c in labels if preds.get(c["id"], {}).get("llm")
             and preds[c["id"]]["llm"]["action"] not in c["acceptable_actions"]]
    extra = [w for w in wrong if w not in PRE_PRIORITY][: max(0, MAX_PRIORITY - len(PRE_PRIORITY))]
    cols = ["id", "message", "language", "category", "proposed_issue_type", "proposed_customer_goal",
            "proposed_mixed", "proposed_required_action", "acceptable_actions", "author_note",
            "priority_review", "priority_reason"]
    if preds:
        cols += ["pipeline_llm_issue", "pipeline_llm_goal", "pipeline_llm_action", "pipeline_llm_reason",
                 "pipeline_keyword_action"]
    cols += ["reviewer_agree (agree/disagree)", "reviewer_correct_issue_type", "reviewer_correct_customer_goal",
             "reviewer_correct_required_action", "reviewer_comment"]
    out = ROOT / "docs/eval/heldout-review.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for c in labels:
            reasons = []
            if c["id"] in PRE_PRIORITY:
                reasons.append("edge case (pre-selected before the run)")
            if c["id"] in wrong:
                reasons.append("LLM route differs from label")
            prio = "YES" if (c["id"] in PRE_PRIORITY or c["id"] in extra) else ""
            row = [c["id"], c["message"], c["language"], c["category"], c["issue_type"], c["customer_goal"],
                   c["mixed"], c["required_action"], "|".join(c["acceptable_actions"]), c["note"], prio,
                   "; ".join(reasons)]
            if preds:
                p = preds.get(c["id"], {})
                l, k = p.get("llm", {}), p.get("keyword", {})
                row += [l.get("pred_issue"), l.get("pred_goal"), l.get("action"), l.get("decided_by"), k.get("action")]
            row += ["", "", "", "", ""]
            w.writerow(row)
    print(f"{out}: {len(labels)} rows, priority {sum(1 for c in labels if c['id'] in PRE_PRIORITY or c['id'] in extra)}")


if __name__ == "__main__":
    main()
