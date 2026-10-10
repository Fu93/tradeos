"""One-off: add issue_type / customer_goal labels to the original 100 (round 2), BEFORE any round-2 run.
required_action is mapped 1:1 from the frozen round-1 expected_route (not re-labelled)."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
ds = json.loads((ROOT / "docs/eval/routing-dataset.json").read_text())
MAP = {"SUPPLIER_REQUIRED": "CREATE_SUPPLIER_TASK", "NEEDS_CLARIFICATION": "CLARIFY_WITH_CUSTOMER",
       "NEEDS_HUMAN_REVIEW": "HUMAN_REVIEW", "DIRECT_WORKFLOW": "DIRECT_WORKFLOW"}
S, DF, M, P, N, U = "SIZE_MISMATCH", "DEFECT", "MISSING_ITEM", "PART_NEED", "NO_ISSUE_INQUIRY", "UNCLEAR"
EX, RS, RP, BP, INF, UG = "EXCHANGE", "RESHIP", "REPAIR", "BUY_PART", "INFORMATION", "UNCLEAR"
dims = {}
for i in range(1, 26):
    dims[f"E{i:02d}"] = (S, EX); dims[f"R{i:02d}"] = (M, RS); dims[f"D{i:02d}"] = (DF, RP); dims[f"P{i:02d}"] = (P, BP)
dims.update({
 "E20": (N, INF), "E21": (S, UG), "E22": (S, UG), "E23": (N, INF),
 "R20": (N, INF), "R21": (U, UG), "R22": (N, INF), "R23": (N, INF),
 "D12": (DF, UG), "D15": (DF, UG), "D18": (DF, UG), "D20": (N, INF), "D21": (DF, UG), "D22": (DF, INF),
 "D23": (N, INF),
 "P20": (N, INF), "P21": (N, INF), "P22": (DF, UG), "P23": (DF, UG),
})
cases = []
for c in ds["cases"]:
    issue, goal = dims[c["id"]]
    cases.append({"id": c["id"], "issue_type": issue, "customer_goal": goal, "mixed": False,
                  "required_action": MAP[c["expected_route"]],
                  "acceptable_actions": [MAP[r] for r in c["acceptable_routes"]]})
out = {"description": "Round-2 addition: issue_type / customer_goal labels for the original 100 cases, following "
       "docs/eval/heldout-labelling-guide.md. Added BEFORE the round-2 run. required_action is the frozen round-1 "
       "expected_route mapped 1:1 (SUPPLIER_REQUIRED->CREATE_SUPPLIER_TASK, NEEDS_CLARIFICATION->"
       "CLARIFY_WITH_CUSTOMER, NEEDS_HUMAN_REVIEW->HUMAN_REVIEW). Round-1 results had no such dimensions. "
       "The original set was written by the same author as the rules: it is a regression set of known "
       "scenarios, not unseen data.",
       "labelled_at": "2026-10-09", "cases": cases}
(ROOT / "docs/eval/routing-dataset-dims.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
