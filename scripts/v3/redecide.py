"""Offline re-decision: re-apply the CURRENT rules to stored extractions of a results file (no LLM calls). DEV ONLY.
  python scripts/v3/redecide.py docs/eval/v3/results/dev_original-v3-dev3.json dev_original old"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts/v3")]
from judge_label import load  # noqa
from eval_v3 import TODAY, load_labels  # noqa
from app.routing_v3 import ContextV3, decide_v3, parse_extraction  # noqa

path, set_name, spec = sys.argv[1], sys.argv[2], sys.argv[3]
R = json.loads(Path(path).read_text())["results"]
L = load_labels(set_name, spec)
items = {i["id"]: i for i in load(set_name)}
ok = old_ok = 0
for k, v in R.items():
    it = items[k]
    d = decide_v3(parse_extraction(json.dumps(v["extraction"])), it["message"], ContextV3(it["customer"], it["linked_order"]), TODAY)
    acc = L[k]["acceptable_actions"]
    ok += d.action in acc
    old_ok += v["action1"] in acc
    if d.action != v["action1"] or d.action not in acc:
        flag = "FIXED" if d.action in acc and v["action1"] not in acc else ("BROKE" if v["action1"] in acc else "still")
        print(f"{flag:6} {k}: {v['action1']} -> {d.action} ({d.rule}) label {acc} | {d.reason[:90]}")
print(f"stored {old_ok}/{len(R)} -> current rules {ok}/{len(R)}")
