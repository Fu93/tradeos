import json
import os
import sys
from pathlib import Path

import pytest

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


def test_model_eval_requires_key_before_writing(monkeypatch, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("eval_intent", ROOT / "scripts/eval_intent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    output = tmp_path / "results.json"
    output.write_text("previous results")
    monkeypatch.setattr(mod, "OUT_JSON", output)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["eval_intent.py"])
    with pytest.raises(SystemExit, match="2"):
        mod.main()
    assert output.read_text() == "previous results"


def test_keyword_eval_runs_without_key(monkeypatch, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("eval_intent", ROOT / "scripts/eval_intent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["eval_intent.py", "--keyword-only", "--limit", "1",
                                          "--output-dir", str(tmp_path)])
    mod.main()
    result = json.loads((tmp_path / "results.json").read_text())
    assert result["dataset_size"] == 1 and result["model"] is None
    assert "llm" not in result
    report = (tmp_path / "results.md").read_text()
    assert "keyword fallback only; no model call" in report
    assert f"[dataset.json]({os.path.relpath(mod.DATASET, tmp_path)})" in report


def test_model_eval_records_provider_fallback_instead_of_aborting(monkeypatch, tmp_path):
    """Same resilient path as production: a provider 400/outage becomes keyword fallback per case,
    not a hard stop that leaves the previous report untouched mid-run."""
    import importlib.util
    from types import SimpleNamespace

    from app.intent import IntentResult

    spec = importlib.util.spec_from_file_location("eval_intent", ROOT / "scripts/eval_intent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setenv("LLM_API_KEY", "test-only-key")
    monkeypatch.setattr(sys, "argv", ["eval_intent.py", "--limit", "1", "--delay", "0",
                                          "--output-dir", str(tmp_path)])

    class FailingExtractor:
        def __init__(self, *args, **kwargs):
            pass

        def extract(self, message):
            return SimpleNamespace(
                llm_unavailable=True, note="HTTP 400", extractor="keyword-fallback (LLM unavailable)",
                result=IntentResult(intent="UNKNOWN", reason="UNKNOWN", requested_action="UNKNOWN"),
                assist=None)

    monkeypatch.setattr(mod, "LLMIntentExtractor", FailingExtractor)
    mod.main()
    result = json.loads((tmp_path / "results.json").read_text())
    assert result["dataset_size"] == 1
    row = result["rows"][0]
    assert row["llm_unavailable"] is True and row["llm_error"] == "HTTP 400"
    assert result["llm_meta"]["fallbacks"] == 1
    assert result["llm_meta"]["per_case_errors"] == [{"id": row["id"], "error": "HTTP 400"}]
    assert (tmp_path / "results.md").exists()


def test_chat_json_client_json_validate_failed_is_retried_then_reported(monkeypatch, tmp_path):
    """eval_intent uses LLMIntentExtractor/ChatJSONClient: mocked Groq json_validate_failed must not abort."""
    import importlib.util

    import httpx

    from app.intent import LLMIntentExtractor

    spec = importlib.util.spec_from_file_location("eval_intent", ROOT / "scripts/eval_intent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setenv("LLM_API_KEY", "test-only-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setattr(sys, "argv", ["eval_intent.py", "--limit", "1", "--delay", "0",
                                          "--output-dir", str(tmp_path)])

    def handler(request):
        return httpx.Response(400, json={
            "error": {"message": "Failed to validate JSON", "code": "json_validate_failed"}
        })

    real_init = LLMIntentExtractor.__init__

    def patched_init(self, api_key, base_url, model, timeout=20.0, transport=None, fallback=None):
        real_init(self, api_key, base_url, model, timeout=timeout,
                  transport=httpx.MockTransport(handler), fallback=fallback)

    monkeypatch.setattr(mod, "LLMIntentExtractor", type(
        "PatchedLLM", (LLMIntentExtractor,), {"__init__": patched_init}))
    # RecordingTransport wraps the real network; bypass by constructing extractor ourselves in main —
    # instead patch RecordingTransport to the mock.
    class MockRec(httpx.MockTransport):
        def __init__(self):
            super().__init__(handler)
            self.last = None
            self.retries_429 = 0

        def handle_request(self, request):
            resp = super().handle_request(request)
            resp.read()
            self.last = {"status": resp.status_code, "latency_s": 0.01, "usage": {}}
            return resp

    monkeypatch.setattr(mod, "RecordingTransport", MockRec)
    # Restore normal LLMIntentExtractor (MockRec is the transport)
    monkeypatch.setattr(mod, "LLMIntentExtractor", LLMIntentExtractor)
    mod.main()
    result = json.loads((tmp_path / "results.json").read_text())
    row = result["rows"][0]
    assert row["llm_unavailable"] is True
    assert "HTTP 400" in (row["llm_error"] or "")
    assert result["llm_meta"]["fallbacks"] == 1


def test_sample_eval_requires_separate_output(monkeypatch, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("eval_intent", ROOT / "scripts/eval_intent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    output = tmp_path / "results.json"
    output.write_text("previous results")
    monkeypatch.setattr(mod, "OUT_JSON", output)
    monkeypatch.setattr(sys, "argv", ["eval_intent.py", "--keyword-only", "--limit", "1"])
    with pytest.raises(SystemExit, match="2"):
        mod.main()
    assert output.read_text() == "previous results"
    monkeypatch.setattr(sys, "argv", ["eval_intent.py", "--keyword-only", "--limit", "1",
                                          "--output-dir", str(output.parent)])
    with pytest.raises(SystemExit, match="2"):
        mod.main()
    assert output.read_text() == "previous results"


def test_report_render_failure_preserves_existing_json(monkeypatch, tmp_path):
    import importlib.util
    from app.intent import KeywordIntentExtractor

    spec = importlib.util.spec_from_file_location("eval_intent", ROOT / "scripts/eval_intent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    output = tmp_path / "results.json"
    output.write_text("previous results")
    message = json.loads(mod.DATASET.read_text())["messages"][0]
    row = {**message, "keyword": KeywordIntentExtractor().extract(message["message"]).result.model_dump()}

    def fail_render(_results, _dataset_link):
        raise RuntimeError("render failed")

    monkeypatch.setattr(mod, "render_md", fail_render)
    with pytest.raises(RuntimeError, match="render failed"):
        mod.write([row], None, "2026-11-05T00:00:00+00:00", 0, out_json=output, out_md=tmp_path / "results.md")
    assert output.read_text() == "previous results"


def test_report_stage_failure_preserves_existing_files(monkeypatch, tmp_path):
    import importlib.util
    from app.intent import KeywordIntentExtractor

    spec = importlib.util.spec_from_file_location("eval_intent", ROOT / "scripts/eval_intent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    output = tmp_path / "results.json"
    report = tmp_path / "results.md"
    output.write_text("previous json")
    report.write_text("previous markdown")
    message = json.loads(mod.DATASET.read_text())["messages"][0]
    row = {**message, "keyword": KeywordIntentExtractor().extract(message["message"]).result.model_dump()}
    stage = mod._stage_report
    calls = 0

    def fail_second_stage(path, content):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk full")
        return stage(path, content)

    monkeypatch.setattr(mod, "_stage_report", fail_second_stage)
    with pytest.raises(OSError, match="disk full"):
        mod.write([row], None, "2026-11-05T00:00:00+00:00", 0, out_json=output, out_md=report)
    assert output.read_text() == "previous json"
    assert report.read_text() == "previous markdown"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("mode", ["--keyword-only", "--rescore"])
def test_saved_model_outputs_cannot_be_reused_for_changed_dataset(monkeypatch, tmp_path, mode):
    import importlib.util

    spec = importlib.util.spec_from_file_location("eval_intent", ROOT / "scripts/eval_intent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    saved = (ROOT / "docs/eval/results.json").read_bytes()
    output = tmp_path / "results.json"
    output.write_bytes(saved)
    dataset = json.loads(mod.DATASET.read_text())
    dataset["messages"][0]["message"] += " changed"
    new_dataset = tmp_path / "dataset.json"
    new_dataset.write_text(json.dumps(dataset))
    monkeypatch.setattr(mod, "DATASET", new_dataset)
    monkeypatch.setattr(sys, "argv", ["eval_intent.py", mode, "--output-dir", str(tmp_path)])

    with pytest.raises(SystemExit, match="2"):
        mod.main()
    assert output.read_bytes() == saved
    assert not (tmp_path / "results.md").exists()
