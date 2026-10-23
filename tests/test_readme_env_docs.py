"""Docs drift guard: every environment variable that app/config.py reads is documented in docs/configuration.md."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_config_env_var_is_documented():
    names = set(re.findall(r'_env(?:_bool)?\("([A-Z][A-Z0-9_]+)"', (ROOT / "app" / "config.py").read_text()))
    assert names, "pattern found no env vars: update this test"
    readme = (ROOT / "docs" / "configuration.md").read_text()
    assert sorted(n for n in names if n not in readme) == []


def test_readme_says_safety_ai_is_off_by_default():
    readme = (ROOT / "docs" / "configuration.md").read_text()
    row = next(line for line in readme.splitlines() if line.startswith("| `TRADEOS_SAFETY_AI` |"))
    assert "| `0` |" in row and "Off by default" in row
