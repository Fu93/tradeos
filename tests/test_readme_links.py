"""README hygiene: every relative link resolves, the overview sections exist, no stale 'partial refunds out of scope'."""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
README = (ROOT / "README.md").read_text()


def test_relative_links_resolve():
    targets = set(re.findall(r"\]\((?!https?:|#|mailto:)([^)\s]+)\)", README))
    assert targets
    missing = [t for t in targets if not (ROOT / t.split("#")[0]).exists()]
    assert not missing, missing


def test_overview_sections_present():
    for h in ("## At a glance", "### Architecture", "### What is proven, and how strongly", "### Built during the hackathon",
              "### Documentation index"):
        assert h in README, h
    assert "```mermaid" in README and "Refund API" in README.split("```mermaid")[1].split("```")[0]


def test_every_doc_is_indexed():
    idx = README.split("### Documentation index")[1].split("\n## ")[0]
    for name in ("safety-gate.md", "partial-refunds.md", "disputes-readonly.md", "sandbox-verification.md",
                 "impact-proof.md", "demo-video-script.md"):
        assert f"docs/{name}" in idx, name


def test_scope_does_not_contradict_partial_refunds():
    scope = README.split("## Scope")[1]
    assert "autonomous financial decisions, partial refunds" not in scope
