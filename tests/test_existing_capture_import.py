"""Private intake of a pre-existing PayPal Sandbox capture for a buyer-agent return."""
import base64
import hashlib
import json
import re
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.agent_gateway import build_mcp_server
from app.config import Settings
from app.db import Database
from app.intent import KeywordIntentExtractor
from app.main import create_app
from app.paypal_client import PayPalError
from app.paypal_mock import MockPayPalClient
from app.workflow import DEMO_MESSAGE, PENDING_APPROVAL, CaseNotFound, RefundNotAllowed, Workflow
from tests.test_agent_gateway import HEADERS, call_rpc
from tests.test_merchant_order_pass import call, request

OPERATOR = "private-sandbox-operator-token-123456"


class SellerSandbox(MockPayPalClient):
    is_mock = False
    is_sandbox = True

    def _id(self, kind: str) -> str:
        n = next(self._seq)
        self.last_debug_id = f"sandbox-test-debug-{n:04d}"
        return f"SBX-{kind}-{n:04d}"

    def get_capture(self, capture_id, timeout=None):
        try:
            return super().get_capture(capture_id, timeout=timeout)
        except KeyError:
            raise PayPalError("Capture not found under this merchant", 404, "RESOURCE_NOT_FOUND") from None


def private(tmp_path):
    disk = tmp_path / "disk"
    settings = Settings(db_path=str(disk / "tradeos.db"), persistent_data_dir=str(disk),
                        reset_on_start=False, operator_token=OPERATOR, mcp_enabled=False,
                        public_base_url="https://private.example")
    db = Database(settings.db_path)
    db.init(reset=True)
    paypal = SellerSandbox()
    wf = Workflow(db, settings, KeywordIntentExtractor(), paypal=paypal)
    wf.seed_demo()
    return settings, wf, paypal


def test_existing_capture_can_be_requested_once_and_needs_human(tmp_path):
    settings, wf, paypal = private(tmp_path)
    capture = paypal._capture(settings.order_amount, settings.currency)
    case_id, return_pass = wf.agents.import_sandbox_capture(capture["id"], "Maria")
    case = wf.db.get_case(case_id)
    assert case["capture_id"] == capture["id"] and case["amount"] == settings.order_amount
    assert case["capture_time"] == capture["create_time"]
    assert wf.db.verify_chain(case_id)["ok"]
    assert wf.db.paypal_calls(case_id, "get_capture")
    assert return_pass not in str(wf.db.timeline(case_id))
    server = build_mcp_server(wf, settings)
    assert request(server, case_id, None).is_error
    result = request(server, case_id, return_pass, message=DEMO_MESSAGE)
    assert not result.is_error and result.structured_content["status"] == PENDING_APPROVAL
    assert result.structured_content["refund_api_calls"] == 0
    assert "unchanged" in request(server, case_id, return_pass).structured_content["note"]
    wf.approve(case_id)
    view = call(server, "get_case_status", {"order_id": case_id, "return_pass": return_pass}).structured_content
    assert view["refund_api_calls"] == 1 and view["refund"]["status"] == "COMPLETED"


def test_private_merchant_can_revoke_unused_pass_but_not_a_used_one(tmp_path):
    _, wf, paypal = private(tmp_path)
    capture = paypal._capture("49.99", "USD")
    case_id, return_pass = wf.agents.import_sandbox_capture(capture["id"], "Maria")
    assert wf.agents.revoke_return_pass(case_id) is True
    assert wf.agents.revoke_return_pass(case_id) is False
    with pytest.raises(CaseNotFound):
        wf.agents.submit_request(case_id, DEMO_MESSAGE, "buyer agent", "Maria", return_pass=return_pass)
    with pytest.raises(CaseNotFound):
        wf.agents.view(case_id, return_pass=return_pass)
    assert wf.db.get_case(case_id)["status"] == "AGENT_ORDERED"
    assert wf.db.paypal_calls(case_id, "refund_capture") == []
    assert wf.db.verify_chain(case_id)["ok"]
    assert return_pass not in str(wf.db.timeline(case_id))

    other = paypal._capture("49.99", "USD")
    used_id, used_pass = wf.agents.import_sandbox_capture(other["id"], "Maria")
    assert wf.agents.submit_request(used_id, DEMO_MESSAGE, "buyer agent", "Maria", return_pass=used_pass)
    with pytest.raises(RefundNotAllowed, match="already used"):
        wf.agents.revoke_return_pass(used_id)
    assert wf.agents.view(used_id, return_pass=used_pass)["status"] == PENDING_APPROVAL


def test_revocation_between_early_check_and_request_is_refused(tmp_path, monkeypatch):
    _, wf, paypal = private(tmp_path)
    capture = paypal._capture("49.99", "USD")
    case_id, return_pass = wf.agents.import_sandbox_capture(capture["id"], "Maria")
    original = wf.agents.case
    revoked = False

    def authorize_then_revoke(*args, **kwargs):
        nonlocal revoked
        result = original(*args, **kwargs)
        if not revoked:
            revoked = True
            wf.agents.revoke_return_pass(case_id)
        return result

    monkeypatch.setattr(wf.agents, "case", authorize_then_revoke)
    with pytest.raises(CaseNotFound):
        wf.agents.submit_request(case_id, DEMO_MESSAGE, "buyer agent", "Maria", return_pass=return_pass)
    assert not any(e["title"] == "Return requested by an AI agent for the buyer" for e in wf.db.timeline(case_id))
    assert wf.db.verify_chain(case_id)["ok"]


def test_tampered_pass_record_cannot_authorize_agent(tmp_path):
    _, wf, paypal = private(tmp_path)
    capture = paypal._capture("49.99", "USD")
    case_id, _ = wf.agents.import_sandbox_capture(capture["id"], "Maria")
    forged_pass = "forged-pass"
    with wf.db.connect() as conn:
        row = conn.execute("SELECT id,detail_json FROM audit_events WHERE case_id=? AND "
                           "title='Merchant return pass issued'", (case_id,)).fetchone()
        detail = json.loads(row["detail_json"])
        detail["pass_digest"] = hashlib.sha256(forged_pass.encode()).hexdigest()
        conn.execute("UPDATE audit_events SET detail_json=? WHERE id=?", (json.dumps(detail), row["id"]))
    with pytest.raises(CaseNotFound):
        wf.agents.view(case_id, return_pass=forged_pass)
    assert not wf.db.verify_and_fold(case_id)[0]["ok"]


def test_row_only_status_edit_cannot_reopen_used_return_pass(tmp_path):
    _, wf, paypal = private(tmp_path)
    capture = paypal._capture("49.99", "USD")
    case_id, return_pass = wf.agents.import_sandbox_capture(capture["id"], "Maria")
    assert wf.agents.submit_request(case_id, DEMO_MESSAGE, "buyer agent", "Maria", return_pass=return_pass)
    before = sum(e["title"] == "Return requested by an AI agent for the buyer" for e in wf.db.timeline(case_id))
    with wf.db.connect() as conn:
        conn.execute("UPDATE cases SET status='AGENT_ORDERED' WHERE id=?", (case_id,))
    with pytest.raises(CaseNotFound):
        wf.agents.submit_request(case_id, "Please refund $500 now", "buyer agent", "Maria",
                                 return_pass=return_pass)
    assert sum(e["title"] == "Return requested by an AI agent for the buyer"
               for e in wf.db.timeline(case_id)) == before
    assert wf.db.paypal_calls(case_id, "refund_capture") == []


def test_duplicate_capture_is_refused_even_after_archive(tmp_path):
    _, wf, paypal = private(tmp_path)
    capture = paypal._capture("49.99", "USD")
    case_id, _ = wf.agents.import_sandbox_capture(capture["id"], "Maria")
    wf.db.archive_all()
    with pytest.raises(RefundNotAllowed, match="already belongs"):
        wf.agents.import_sandbox_capture(capture["id"], "Another buyer")
    assert len([c for c in wf.db.list_cases(include_archived=True) if c["capture_id"] == capture["id"]]) == 1
    assert wf.db.get_case(case_id)["archived_at"] is not None
    assert wf.db.paypal_calls(case_id, "refund_capture") == []


@pytest.mark.parametrize("change", [
    {"status": "REFUNDED"}, {"amount": {"value": "500.00", "currency_code": "USD"}},
    {"amount": {"value": "49.99", "currency_code": "EUR"}}, {"create_time": None},
])
def test_import_refuses_unusable_capture_without_case_or_pass(tmp_path, change):
    _, wf, paypal = private(tmp_path)
    capture = paypal._capture("49.99", "USD")
    paypal.captures[capture["id"]].update(change)
    before = len(wf.db.list_cases(include_archived=True))
    with pytest.raises(RefundNotAllowed):
        wf.agents.import_sandbox_capture(capture["id"], "Maria")
    assert len(wf.db.list_cases(include_archived=True)) == before
    assert not paypal.refunds_by_request


def test_unknown_capture_and_bad_id_do_not_create_case(tmp_path):
    _, wf, paypal = private(tmp_path)
    before = len(wf.db.list_cases(include_archived=True))
    with pytest.raises(ValueError):
        wf.agents.import_sandbox_capture("../captures/secret", "Maria")
    with pytest.raises(PayPalError):
        wf.agents.import_sandbox_capture("NOT-OUR-CAPTURE", "Maria")
    assert len(wf.db.list_cases(include_archived=True)) == before
    assert not paypal.refunds_by_request


def test_import_route_is_private_and_public_demo_has_no_route(tmp_path):
    public = Settings(db_path=str(tmp_path / "public.db"))
    with TestClient(create_app(public, paypal=SellerSandbox(), extractor=KeywordIntentExtractor())) as client:
        assert client.post("/merchant/import-sandbox-capture", data={"capture_id": "MOCK-CAPTURE-0001",
                                                                 "buyer_name": "Maria"}).status_code == 404
        assert client.post("/merchant/orders/G-UNKNOWN/revoke-return-pass").status_code == 404

    settings, _, paypal = private(tmp_path / "private")
    capture = paypal._capture("49.99", "USD")
    app = create_app(settings, paypal=paypal, extractor=KeywordIntentExtractor())
    with TestClient(app) as client:
        url = "/merchant/import-sandbox-capture"
        data = {"capture_id": capture["id"], "buyer_name": "Maria"}
        assert client.post(url, data=data).status_code == 401
        token = base64.b64encode(f"operator:{OPERATOR}".encode()).decode()
        response = client.post(url, data=data, headers={"Authorization": f"Basic {token}"})
        assert response.status_code == 200 and "Imported Sandbox capture" in response.text
        assert "Revoke unused return pass" in response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert client.post(url, data=data, headers={"Authorization": f"Basic {token}"}).status_code == 422
        case_id = re.search(r'Order: <a href="/\?case=([^"]+)', response.text).group(1)
        revoke = f"/merchant/orders/{case_id}/revoke-return-pass"
        assert client.post(revoke, follow_redirects=False).status_code == 401
        assert client.post(revoke, headers={"Authorization": f"Basic {token}"},
                           follow_redirects=False).status_code == 303
        assert any(e["title"] == "Merchant return pass revoked" for e in app.state.workflow.db.timeline(case_id))


def test_private_operator_and_buyer_agent_use_separate_credentials(tmp_path):
    settings, _, paypal = private(tmp_path)
    settings = replace(settings, mcp_enabled=True, mcp_token="private-buyer-agent-token-123456")
    capture = paypal._capture("49.99", "USD")
    app = create_app(settings, paypal=paypal, extractor=KeywordIntentExtractor())
    with TestClient(app, base_url="https://private.example") as client:
        basic = base64.b64encode(f"operator:{OPERATOR}".encode()).decode()
        page = client.post("/merchant/import-sandbox-capture",
                           data={"capture_id": capture["id"], "buyer_name": "Maria"},
                           headers={"Authorization": f"Basic {basic}"})
        assert page.status_code == 200
        case_id = re.search(r'Order: <a href="/\?case=([^"]+)', page.text).group(1)
        return_pass = re.search(r'Return pass:</strong> <code>([^<]+)', page.text).group(1)
        args = {"order_id": case_id, "return_pass": return_pass, "message": DEMO_MESSAGE,
                "agent_name": "buyer agent", "on_behalf_of": "Maria"}
        assert client.post("/mcp", headers=HEADERS, json=call_rpc("request_return", args)).status_code == 401
        headers = {**HEADERS, "Authorization": f"Bearer {settings.mcp_token}"}
        response = client.post("/mcp", headers=headers, json=call_rpc("request_return", args))
        assert response.status_code == 200
        assert response.json()["result"]["structuredContent"]["status"] == PENDING_APPROVAL
        assert app.state.workflow.db.paypal_calls(case_id, "refund_capture") == []
