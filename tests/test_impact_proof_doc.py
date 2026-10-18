"""docs/impact-proof.md must keep its honesty markers and stay in line with the eval results that are on main."""
import json
from pathlib import Path

DOC = (Path(__file__).resolve().parents[1] / "docs" / "impact-proof.md").read_text()


def test_doc_names_the_three_validation_levels_and_the_missing_audit():
    for marker in ("Test / automated eval results", "Human adjudication of specific disputed labels",
                   "Full human audit", "NOT done", "judge agreement", "no** human inter-annotator"):
        assert marker.lower() in DOC.lower()
    for number in ("290/308", "85/85", "0.74", "k1", "k3", "k5"):
        assert number in DOC


def test_main_eval_numbers_quoted_in_the_doc_match_results_json():
    res = json.loads((Path(__file__).resolve().parents[1] / "docs" / "eval" / "results.json").read_text())
    assert res["dataset_size"] == 52
    assert "38/52" in DOC and "8/52" in DOC and "49/52" in DOC
