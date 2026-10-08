import json
from pathlib import Path

from app.intent import IntentResult

ROOT = Path(__file__).resolve().parents[1]


def test_eval_dataset_labels_match_schema():
    data = json.loads((ROOT / "docs/eval/dataset.json").read_text())
    msgs = data["messages"]
    assert 40 <= len(msgs) <= 60
    assert len({m["id"] for m in msgs}) == len(msgs)
    assert {m["lang"] for m in msgs} == {"en", "zh-Hant", "es", "de", "ja", "mixed"}
    assert sum(m["injection"] for m in msgs) >= 5
    for m in msgs:
        IntentResult(**m["expected"])  # every label is a valid schema value


def test_eval_scoring_keyword_only():
    import importlib.util
    spec = importlib.util.spec_from_file_location("eval_intent", ROOT / "scripts/eval_intent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    exp = {"intent": "EXCHANGE_REQUEST", "reason": "SIZE_MISMATCH", "requested_action": "EXCHANGE"}
    bad = {"intent": "EXCHANGE_REQUEST", "reason": "UNKNOWN", "requested_action": "EXCHANGE"}
    rows = [{"id": "x1", "expected": {"intent": "REFUND_REQUEST", "reason": "UNKNOWN", "requested_action": "REFUND"},
             "keyword": bad}, {"id": "x2", "expected": exp, "keyword": exp}]
    s = mod.score(rows, "keyword")
    assert s["exact"] == 1 and s["intent"] == 1
    assert s["unwarranted_accept"] == ["x1"]  # an injected "EXCHANGE" would pass the request check
