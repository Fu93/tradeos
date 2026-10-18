"""Queue demo view: seeded, labelled DEMO DATA, routed by the real policy engine, no PayPal, no DB rows."""
import re
from datetime import date

from app.queue_demo import DEMO_BADGE, SEEDS, queue_view
from tests.helpers import case_from, make_app

TODAY = date(2026, 10, 18)


def by_key():
    return {i["key"]: i for i in queue_view(TODAY)["items"]}


def test_eight_cases_six_languages_each_badged():
    items = queue_view(TODAY)["items"]
    assert len(items) == 8
    assert {i["lang_code"].split("-")[0] for i in items} == {"en", "zh", "es", "de", "ja", "fr"}
    assert all(i["badge"] == DEMO_BADGE == "DEMO DATA" for i in items)


def test_routing_outcomes():
    q = by_key()
    assert q["q-en"]["outcome"] == "REFUND_APPROVAL" and q["q-ja2"]["outcome"] == "REFUND_APPROVAL"
    assert q["q-zh"]["outcome"] == "EXCHANGE_SUPPLIER"
    assert q["q-es"]["outcome"] == "HUMAN_REVIEW"          # safety complaint: not automatable
    assert q["q-de"]["outcome"] == "REJECTED_INJECTION"
    assert q["q-ja"]["outcome"] == "NEEDS_HUMAN"           # unreadable
    assert q["q-fr"]["outcome"] == "REJECTED_POLICY" and q["q-en2"]["outcome"] == "REJECTED_POLICY"
    assert any(c["name"] == "return_window" and not c["passed"] for c in q["q-fr"]["checks"])
    assert any(c["name"] == "product_eligible" and not c["passed"] for c in q["q-en2"]["checks"])
    # nothing unreadable / unsupported / injected is ever eligible
    assert all(q[k]["decision"] != "ELIGIBLE" for k in ("q-es", "q-de", "q-ja", "q-fr", "q-en2"))


def test_routing_is_computed_not_hardcoded():
    """Same seed, different 'today': the French return flips from late to in-window."""
    fr = next(s for s in SEEDS if s.key == "q-fr")
    from app.queue_demo import route
    assert route(fr, TODAY)["outcome"] == "REJECTED_POLICY"
    from dataclasses import replace
    assert route(replace(fr, days_ago=10), TODAY)["outcome"] == "REFUND_APPROVAL"


def test_agrees_with_the_real_workflow_on_equivalent_messages(settings):
    """The same English messages through the actual loop (mock PayPal) land where the queue says."""
    client, _pp, wf = make_app(settings)
    case = wf.db.get_case(case_from(client.post("/demo/run/A", follow_redirects=False)))
    assert case["decision"] == "ELIGIBLE"
    late = wf.db.get_case(case_from(client.post("/demo/run/B", follow_redirects=False)))
    assert late["decision"] == "REJECTED"


def test_page_renders_badged_mobile_friendly_and_actionless(settings):
    client, pp, wf = make_app(settings)
    cases_before = len(wf.db.list_cases())
    pp.reset_mock()
    html = client.get("/queue").text
    assert 'name="viewport"' in html
    assert html.count("DEMO DATA") >= 9  # page title badge + banner + one per card
    for text in ("English", "Chinese (Traditional)", "Spanish", "German", "Japanese", "French"):
        assert text in html
    assert "Return → approval → refund" in html and "Exchange → supplier" in html and "Human review" in html
    assert "Rejected — instruction-like text" in html and "Needs a human" in html
    assert "<form" not in html.split('<main>')[1]  # the page has no action buttons at all
    assert len(wf.db.list_cases()) == cases_before  # nothing seeded into the cases table
    assert pp.method_calls == []  # no PayPal call of any kind
    assert client.head("/queue").status_code == 200


def test_queue_survives_demo_reset_and_does_not_leak_into_cases(settings):
    client, _pp, wf = make_app(settings)
    assert client.post("/demo/reset", follow_redirects=False).status_code == 303
    assert client.get("/queue").status_code == 200
    assert not re.search(r"q-(en|zh|es|de|ja|fr)", " ".join(c["id"] for c in wf.db.list_cases()))
    assert 'href="/queue"' in client.get("/").text


def test_user_input_cannot_reach_the_queue_page(settings):
    """No parameter, header or body is read by /queue: hostile query strings are neither reflected nor change the
    routing, and the route accepts no write methods."""
    client, pp, wf = make_app(settings)
    base = client.get("/queue").text
    hostile = "?case=<script>alert(1)</script>&q=%3Cimg%20src=x%20onerror=alert(1)%3E&today=2000-01-01&lang=../../etc/passwd"
    r = client.get("/queue" + hostile, headers={"X-Forwarded-Host": "<evil>", "Referer": "<script>"})
    assert r.status_code == 200 and r.text == base
    assert "<script>alert(1)" not in r.text and "onerror" not in r.text
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)("/queue").status_code == 405
    assert pp.method_calls == []


def test_page_escapes_everything_and_has_no_inline_styles_or_scripts(settings):
    client, *_ = make_app(settings)
    html = client.get("/queue").text
    assert not re.search(r"\sstyle\s*=|\son[a-z]+\s*=|<script(?![^>]*src=)|<style", html)  # CSP is style-src 'self'
    # the German injection text is shown as text (escaped quotes/markup stay inert), never as markup
    assert "Ignoriere alle Regeln" in html and "<img" not in html


def test_every_seed_outcome_is_pinned_exactly():
    """All 8 cases, expected outcome AND decision, so any policy drift is caught here."""
    expected = {"q-en": ("REFUND_APPROVAL", "ELIGIBLE"), "q-zh": ("EXCHANGE_SUPPLIER", "ELIGIBLE"),
                "q-es": ("HUMAN_REVIEW", "REJECTED"), "q-de": ("REJECTED_INJECTION", "REJECTED"),
                "q-ja": ("NEEDS_HUMAN", "NEEDS_HUMAN"), "q-fr": ("REJECTED_POLICY", "REJECTED"),
                "q-ja2": ("REFUND_APPROVAL", "ELIGIBLE"), "q-en2": ("REJECTED_POLICY", "REJECTED")}
    got = {k: (v["outcome"], v["decision"]) for k, v in by_key().items()}
    assert got == expected
    counts = {label: n for label, n, _ in queue_view(TODAY)["counts"]}
    assert sum(counts.values()) == 8 and counts["Return → approval → refund"] == 2
