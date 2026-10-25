"""Integrity of the real-text safety eval artifacts (CPSC sample + results) and the numbers the docs quote."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "docs/eval/cpsc_real_text_sample.jsonl"
RESULTS = ROOT / "docs/eval/cpsc_real_text_results.json"
DOC = ROOT / "docs/eval/cpsc_real_text.md"


def rows():
    return [json.loads(line) for line in SAMPLE.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_sample_shape_and_labels():
    rs = rows()
    assert len(rs) == 100 and [r["id"] for r in rs] == list(range(1, 101))
    assert len({r["report_no"] for r in rs}) == 100
    assert {r["stratum"]: sum(x["stratum"] == r["stratum"] for x in rs) for r in rs} == {
        "injury": 35, "incident_no_injury": 35, "no_incident_no_injury": 30}
    for r in rs:
        assert 60 <= len(r["message"]) <= 500
        assert r["label_escalate"] in (0, 1)
        assert r["label_basis"] in ("harm_reported", "hazard_no_harm", "energised_product_fault_rule")


def test_results_match_the_sample_and_the_doc():
    res = json.loads(RESULTS.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in rows()}
    assert res["n"] == 100 and res["ai_errors"] == 0
    for r in res["rows"]:
        assert r["report_no"] == by_id[r["id"]]["report_no"] and r["label"] == by_id[r["id"]]["label_escalate"]
        assert r["combined"] == (r["keyword"] or r["ai"])
    pos = [r for r in res["rows"] if r["label"] == 1]
    miss = {k: sum(not r[k] for r in pos) for k in ("keyword", "ai", "combined")}
    doc = DOC.read_text(encoding="utf-8")
    assert f"**{miss['keyword']} / {len(pos)}**" in doc
    assert f"{miss['ai']} / {len(pos)}" in doc and f"{miss['combined']} / {len(pos)}" in doc


# The frozen results file records the keyword layer as it was when the AI run was made. The plural-category fix
# (docs/safety-gate.md, "Product class: plural categories") turned ONE row from not-flagged to flagged: id 33, a gasoline
# can in category "Fuel, Lighters and Fireworks" - the plural "Lighters" now reaches the GAS class, so "leaked" counts as
# a fault on a gated product. The frozen file is NOT rescored; this test pins the difference.
KEYWORD_FLIPPED_BY_PLURAL_FIX = {33}


def test_keyword_layer_result_is_reproducible_offline():
    from app.safety import assess
    res = {r["id"]: r for r in json.loads(RESULTS.read_text(encoding="utf-8"))["rows"]}
    for r in rows():
        prod = {"sku": r["report_no"], "name": r["product"], "category": r["product_category"]}
        now = assess(r["message"], prod, None).flagged
        if r["id"] in KEYWORD_FLIPPED_BY_PLURAL_FIX:
            assert res[r["id"]]["keyword"] is False and now is True, r["id"]  # frozen miss, now caught (escalate-only)
        else:
            assert now == res[r["id"]]["keyword"], r["id"]
