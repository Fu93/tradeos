"""Both new pages are reachable from one nav, and style.css has exactly one .mainnav rule block."""
import re
from pathlib import Path

from tests.helpers import make_app


def test_nav_has_cases_queue_disputes_on_every_page(settings):
    client, _, _ = make_app(settings)
    for path in ("/", "/queue", "/disputes"):
        html = client.get(path).text
        nav = re.search(r'<nav class="mainnav".*?</nav>', html, re.S)
        assert nav, path
        assert re.findall(r'href="([^"]+)">([^<]+)</a>', nav.group(0)) == \
            [("/", "Cases"), ("/queue", "Queue"), ("/disputes", "Disputes")]


def test_single_mainnav_base_rule():
    css = Path("app/static/style.css").read_text()
    assert len(re.findall(r"^\.mainnav \{ display: flex", css, re.M)) == 1
