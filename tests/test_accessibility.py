"""Structural accessibility checks that survive refactors: skip link, landmark target, focus styles."""
from pathlib import Path

from tests.helpers import app_ctx, case_from  # noqa: F401

CSS = (Path(__file__).parent.parent / "app" / "static" / "style.css").read_text()


def test_every_page_has_skip_link_and_main_target(app_ctx):
    client, _, _ = app_ctx
    for path in ("/", "/queue", "/disputes"):
        html = client.get(path).text
        assert 'href="#main"' in html and '<main id="main"' in html, path
        assert html.index('href="#main"') < html.index("<header"), path  # first focusable element


def test_active_case_tab_is_marked_current(app_ctx):
    client, _, _ = app_ctx
    cid = case_from(client.post("/demo/run/A", follow_redirects=False))
    html = client.get(f"/?case={cid}").text
    assert html.count('aria-current="true"') == 1


def test_css_has_visible_focus_and_reduced_motion():
    assert ":focus-visible" in CSS and "outline: 3px" in CSS
    assert "prefers-reduced-motion: reduce" in CSS and ".skip-link:focus" in CSS
