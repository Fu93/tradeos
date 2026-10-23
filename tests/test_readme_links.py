"""Docs hygiene: relative links resolve, the README keeps its overview, every doc is indexed, no stale scope claims."""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
README = (ROOT / "README.md").read_text()
DOCS = ROOT / "docs"
SPLIT_DOCS = ("how-it-works.md", "evidence.md", "configuration.md", "hackathon.md")


def _relative_links(text):
    return set(re.findall(r"\]\((?!https?:|#|mailto:)([^)\s]+)\)", text))


def test_relative_links_resolve():
    targets = _relative_links(README)
    assert targets
    missing = [t for t in targets if not (ROOT / t.split("#")[0]).exists()]
    assert not missing, missing


def test_split_docs_relative_links_resolve():
    for name in SPLIT_DOCS:
        text = (DOCS / name).read_text()
        missing = [t for t in _relative_links(text) if not (DOCS / t.split("#")[0]).resolve().exists()]
        assert not missing, (name, missing)


def test_overview_sections_present():
    for h in ("## The problem", "## How it works", "## Status and roadmap", "## Documentation"):
        assert h in README, h
    assert "```mermaid" in README and "Refund API" in README.split("```mermaid")[1].split("```")[0]
    assert "Sandbox only" in README.split("## Status and roadmap")[1]


def test_every_doc_is_indexed():
    idx = README.split("## Documentation")[1].split("\n## ")[0]
    for name in ("safety-gate.md", "partial-refunds.md", "disputes-readonly.md", "sandbox-verification.md",
                 "impact-proof.md", "demo-video-script.md", *SPLIT_DOCS):
        assert f"docs/{name}" in idx, name


def test_detailed_sections_kept_in_docs():
    how = (DOCS / "how-it-works.md").read_text()
    for h in ("## Autonomy: who approves a case", "### How TradeOS uses PayPal", "## Scope and known limits"):
        assert h in how, h
    evidence = (DOCS / "evidence.md").read_text()
    assert "## Evidence tiers" in evidence and "## Evaluation: 52 multilingual messages" in evidence
    hackathon = (DOCS / "hackathon.md").read_text()
    assert "## Judge quick start" in hackathon and "## Built during the hackathon" in hackathon


def test_scope_does_not_contradict_partial_refunds():
    scope = (DOCS / "how-it-works.md").read_text().split("## Scope and known limits")[1]
    assert "autonomous financial decisions, partial refunds" not in scope
