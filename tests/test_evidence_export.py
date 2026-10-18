"""Evidence export: read-only report + JSON whose hash chain can be re-checked without TradeOS code."""
import hashlib
import json

from tests.helpers import app_ctx, case_from  # noqa: F401
from tests.test_evidence import run_a


def _sha(entry, case_id):
    canon = json.dumps({"case_id": case_id, "seq": entry["seq"], "type": entry["type"], "ts": entry["ts"],
                        "payload": entry["payload"], "prev_hash": entry["prev_hash"]},
                       sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(canon).hexdigest()


def test_json_export_chain_recomputes_independently_and_lists_paypal_ids(app_ctx):
    client, _, wf = app_ctx
    cid = run_a(client)
    r = client.get(f"/cases/{cid}/evidence.json")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    d = r.json()
    prev = "0" * 64
    for e in d["chain_entries"]:
        assert e["prev_hash"] == prev and _sha(e, cid) == e["entry_hash"]
        prev = e["entry_hash"]
    assert d["chain_head"] == prev and d["verification"]["ok"] is True
    case = wf.db.get_case(cid)
    assert d["paypal_ids"]["refund_id"] == case["refund_id"] and d["paypal_ids"]["capture_id"] == case["capture_id"]
    assert any(c["operation"] == "refund_capture" and c["debug_id"] for c in d["paypal_calls"])
    assert d["summary"]["approval_source"] == "human"
    assert "token" not in r.text.lower() and "secret" not in r.text.lower()


def test_html_report_and_rejected_case_shows_refund_not_called(app_ctx):
    client, _, wf = app_ctx
    cid = case_from(client.post("/demo/run/B", follow_redirects=False))
    h = client.get(f"/cases/{cid}/evidence")
    assert h.status_code == 200 and "Evidence report" in h.text
    assert "Refund API: NOT CALLED" in h.text and "Intact" in h.text
    assert client.get(f"/cases/{cid}/evidence.json").json()["paypal_ids"].get("refund_id") is None


def test_export_is_read_only_and_404s_for_unknown_case(app_ctx):
    client, pp, wf = app_ctx
    cid = run_a(client)
    before = (len(wf.db.chain_entries(cid)), pp.refund_capture.call_count)
    for _ in range(2):
        client.get(f"/cases/{cid}/evidence")
        client.get(f"/cases/{cid}/evidence.json")
    assert (len(wf.db.chain_entries(cid)), pp.refund_capture.call_count) == before
    assert client.get("/cases/nope/evidence").status_code == 404
    assert client.get("/cases/nope/evidence.json").status_code == 404


def test_dashboard_links_to_report(app_ctx):
    client, _, _ = app_ctx
    cid = run_a(client)
    assert f"/cases/{cid}/evidence" in client.get(f"/?case={cid}").text
