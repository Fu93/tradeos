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


def test_committed_results_say_when_the_policy_rows_were_rescored():
    """A rescore recomputes the policy rows from saved model outputs. The page must say so, and say the outputs are
    older, every time: the generator writes that note itself, so a later rescore cannot silently drop it."""
    import json
    res = json.loads((ROOT / "docs/eval/results.json").read_text())
    md = (ROOT / "docs/eval/results.md").read_text()
    assert res["policy_scored_at"] != res["run_at"]
    assert f"Policy rows rescored {res['policy_scored_at']}" in md and "needs `LLM_API_KEY`" in md
    assert "Exchange missed" not in md and "Acceptable request missed" in md
    assert res["llm"]["unwarranted_accept"] == [] and res["injection"]["llm"]["unwarranted_accept"] == []


def test_render_md_omits_the_rescore_note_for_a_fresh_run():
    import importlib.util
    import json
    spec = importlib.util.spec_from_file_location("eval_intent", ROOT / "scripts/eval_intent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    res = json.loads((ROOT / "docs/eval/results.json").read_text())
    res["policy_scored_at"] = res["run_at"]
    assert "Policy rows rescored" not in mod.render_md(res)
