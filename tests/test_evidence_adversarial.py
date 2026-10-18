"""Adversarial review of the evidence report: every case type, XSS, no secrets/paths, read-only, large chains."""
import json
import re

import pytest

from app import lineitems as li
from tests.helpers import FakeExtractor, app_ctx, case_from, make_app  # noqa: F401
from tests.test_evidence import run_a

XSS = '<script>alert(1)</script><img src=x onerror=alert(2)> "quoted" \'single\' {{7*7}} ${7*7}'
FORBIDDEN = ("Bearer", "access_token", "client_secret", "CLIENT_SECRET", "WH-TEST", "transmission_sig",
             "admin_token", "ADMIN_TOKEN", "OPENAI", "XAI_API", "api_key", "/workspace", "/home/", "/tmp/",
             "/opt/render", "tradeos.db", ".sqlite", "Traceback", "password")
ES_BURN = "La suela se derritió con el calor y me quemé el pie. Es peligroso."


def _scan(text):
    low = text.lower()
    for bad in FORBIDDEN:
        assert bad.lower() not in low, bad


def _check_case(client, cid):
    j = client.get(f"/cases/{cid}/evidence.json")
    h = client.get(f"/cases/{cid}/evidence")
    assert j.status_code == 200 and h.status_code == 200
    _scan(j.text)
    _scan(h.text)
    assert "<script>" not in h.text.lower() and "onerror=alert" not in h.text.replace("&#34;", '"')
    d = j.json()
    assert d["verification"]["ok"] and d["chain_head"] == d["chain_entries"][-1]["entry_hash"]
    return d, h.text


def test_every_case_type_renders_and_is_clean(app_ctx):
    client, pp, wf = app_ctx
    cids = {"A": run_a(client), "B": case_from(client.post("/demo/run/B", follow_redirects=False))}
    cids["M"] = wf.run_scenario("M")
    batch = wf.db.get_batch(f"{cids['M']}-B1")
    wf.mixed.approve_batch(cids["M"], batch["id"], li.to_str(batch["amount_minor"], batch["currency"]),
                           batch["items_hash"])
    for name, cid in cids.items():
        d, _ = _check_case(client, cid)
        assert d["environment"]["paypal_mode"] == "mock", name
    assert _check_case(client, cids["A"])[0]["paypal_ids"]["refund_id"]
    assert "Refund API: NOT CALLED" in client.get(f"/cases/{cids['B']}/evidence").text


def test_safety_gated_and_xss_cases(settings):
    client, pp, wf = make_app(settings, extractor=FakeExtractor(core={
        "intent": "REFUND_REQUEST", "reason": "DAMAGED", "requested_action": "REFUND"}))
    safety = case_from(client.post("/cases/free", data={"message": ES_BURN}, follow_redirects=False))
    d, html = _check_case(client, safety)
    assert "refund_id" not in d["paypal_ids"] and not pp.refund_capture.called and "Refund API: NOT CALLED" in html
    xss = case_from(client.post("/cases/free", data={"message": XSS}, follow_redirects=False))
    d, html = _check_case(client, xss)
    assert "alert(" not in html  # the HTML report renders no free text at all (ids, types, hashes only)
    r = client.get(f"/cases/{xss}/evidence.json")
    assert r.headers["content-type"].startswith("application/json") and "attachment" in r.headers["content-disposition"]
    assert r.headers.get("x-content-type-options", "").lower() == "nosniff"
    assert not pp.refund_capture.called


def test_large_chain_and_unknown_ids(app_ctx):
    client, pp, wf = app_ctx
    cid = run_a(client)
    for i in range(1500):
        wf.db.audit(cid, "note", f"entry {i}", {"i": i})
    d, _ = _check_case(client, cid)
    assert len(d["chain_entries"]) >= 1500
    for bad in ("nope", "../../etc/passwd", "A-%00", "A-" + "0" * 5000, "%3Cscript%3E"):
        assert client.get(f"/cases/{bad}/evidence").status_code in (404, 400)
        assert client.get(f"/cases/{bad}/evidence.json").status_code in (404, 400)


def test_only_get_is_allowed_and_no_state_change(app_ctx):
    client, pp, wf = app_ctx
    cid = run_a(client)
    for url in (f"/cases/{cid}/evidence", f"/cases/{cid}/evidence.json"):
        for m in ("post", "put", "delete", "patch"):
            assert getattr(client, m)(url).status_code in (404, 405)
