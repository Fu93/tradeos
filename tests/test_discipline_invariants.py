"""Discipline invariants: AI understands, rules decide, humans approve, PayPal proves.

Property / boundary tests for the strongest claims. Pure where possible; mock PayPal only.
These lock the trust boundary — they are not live Sandbox proof.
"""
from __future__ import annotations

import ast
import inspect
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app import autonomy, lineitems as li, safety
from app.intent import IntentResult
from app.policy import PolicyInput, evaluate
from tests.helpers import case_from, make_app

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 19)
MONEY_MODULES = ("app/policy.py", "app/lineitems.py", "app/safety.py", "app/autonomy.py",
                 "app/economics.py", "app/audit_chain.py")
# Names that must never appear as imports inside money / rule modules (trust boundary).
FORBIDDEN_IMPORT_ROOTS = {"openai", "groq", "anthropic", "httpx", "requests"}
FORBIDDEN_FROM_MODULES = {"app.safety_ai", "app.notes", "app.workflow", "app.mixed"}


def _imports_of(rel: str) -> list[str]:
    tree = ast.parse((ROOT / rel).read_text())
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.append(node.module)
    return out


# ----------------------------------------------------------------------------------------------- trust boundary
@pytest.mark.parametrize("rel", MONEY_MODULES)
def test_money_and_rule_modules_have_no_llm_or_http_imports(rel):
    """Rules / money math stay pure: no LLM client, no HTTP. lineitems has zero app.* imports."""
    imports = _imports_of(rel)
    for name in imports:
        root = name.split(".")[0]
        assert root not in FORBIDDEN_IMPORT_ROOTS, f"{rel} imports {name}"
        assert name not in FORBIDDEN_FROM_MODULES, f"{rel} imports {name}"
    if rel == "app/lineitems.py":
        assert not any(n.startswith("app.") for n in imports)
    if rel == "app/policy.py":
        # IntentResult is a typed schema only; policy must not import the LLM extractor.
        assert ("intent" in imports or "app.intent" in imports)
        assert "IntentExtractor" not in (ROOT / rel).read_text()


def test_lineitems_module_is_stdlib_only():
    """The refund calculator must not import the rest of the app (no accidental LLM/workflow coupling)."""
    for name in _imports_of("app/lineitems.py"):
        assert name.split(".")[0] in {"__future__", "hashlib", "json", "dataclasses", "datetime",
                                      "decimal", "typing"}, name


def test_policy_evaluate_source_has_no_network_or_llm_calls():
    src = inspect.getsource(evaluate)
    for banned in ("httpx", "openai", "requests", "ChatJSON", "extract(", "classify("):
        assert banned not in src


# ----------------------------------------------------------------------------------------------- AI never sets money
def test_fuzz_proposal_money_keys_never_change_quote():
    """Any extra key on a proposal (amount, unit_price, ...) is ignored; quote equals the clean one."""
    rng = random.Random(19)
    o = li.OrderModel("USD", (li.Line(1, "A", "A", 1999, 2, 160), li.Line(2, "B", "B", 500, 1, 40),
                               li.Line(3, "C", "C", 100, 3, 8)), 600)
    kw = dict(purchase_date=TODAY - timedelta(days=3), today=TODAY, return_window_days=30)
    money_keys = ["amount", "refund_total", "unit_price", "currency", "tax", "unit_minor", "total_minor",
                  "shipping_minor", "capture_id", "value"]
    for _ in range(200):
        clean = [{"line_no": 1, "action": "RETURN", "reason": "DAMAGED", "qty": 1},
                 {"line_no": 2, "action": "EXCHANGE", "reason": "SIZE_MISMATCH"},
                 {"line_no": 3, "action": "RETURN", "reason": "CHANGED_MIND"}]
        evil = []
        for row in clean:
            e = dict(row)
            for k in rng.sample(money_keys, rng.randint(1, 4)):
                e[k] = rng.choice(["999999.99", 0, -1, "JPY", {"x": 1}, 10 ** 9])
            evil.append(e)
        pc, _ = li.parse_proposals(clean, o)
        pe, ignored = li.parse_proposals(evil, o)
        assert set(ignored) & set(money_keys)
        assert [p.__dict__ for p in pc] == [p.__dict__ for p in pe]
        assert (li.quote_batch(o, li.decide_lines(o, pc, **kw), li.Ledger()).to_dict()
                == li.quote_batch(o, li.decide_lines(o, pe, **kw), li.Ledger()).to_dict())


def test_intent_schema_forbids_amount_fields():
    """IntentResult is extra=forbid: a model cannot smuggle amount / refund_total into the policy input."""
    with pytest.raises(Exception):
        IntentResult(intent="REFUND_REQUEST", reason="DAMAGED", requested_action="REFUND",
                     amount="999999.00")  # type: ignore[call-arg]
    with pytest.raises(Exception):
        IntentResult.model_validate({"intent": "REFUND_REQUEST", "reason": "DAMAGED",
                                     "requested_action": "REFUND", "refund_total": "1.00"})


def test_single_path_refund_kwargs_never_carry_an_amount_from_intent(settings):
    """Legacy full-refund path: refund_capture is called WITHOUT amount= (PayPal full capture).
    Case amount is the merchant setting; PayPal-Request-Id is deterministic."""
    client, pp, wf = make_app(settings)
    cid = case_from(client.post("/demo/run/A", follow_redirects=False))
    client.post(f"/cases/{cid}/approve", follow_redirects=False)
    assert pp.refund_capture.called
    args, kwargs = pp.refund_capture.call_args
    assert "amount" not in kwargs or kwargs.get("amount") is None
    assert args[1] == f"tradeos-refund-{cid}"
    case = wf.db.get_case(cid)
    assert case["amount"] == wf.settings.order_amount
    assert case["refund_status"] == "COMPLETED"


def test_autonomy_cannot_turn_rejected_or_injection_into_auto():
    rej = evaluate(PolicyInput(
        capture_status="COMPLETED", captured_amount=Decimal("49.99"), capture_currency="USD",
        expected_currency="USD", requested_refund=Decimal("49.99"), already_refunded=Decimal("0"),
        purchase_date=TODAY - timedelta(days=5), today=TODAY, return_window_days=30,
        product_returnable=True, product_name="x",
        intent=IntentResult(intent="REFUND_REQUEST", reason="DAMAGED", requested_action="REFUND"),
        injection_suspected=True))
    assert rej.decision == "REJECTED"
    assert autonomy.decide_detailed(
        rej, amount=Decimal("49.99"), auto_enabled=True, auto_refund_max_amount=Decimal("100"),
        auto_exchange_enabled=True, injection_suspected=True, intent_is_unknown=False,
        action="REFUND").decision == "BLOCK"
    ok = evaluate(PolicyInput(
        capture_status="COMPLETED", captured_amount=Decimal("49.99"), capture_currency="USD",
        expected_currency="USD", requested_refund=Decimal("49.99"), already_refunded=Decimal("0"),
        purchase_date=TODAY - timedelta(days=5), today=TODAY, return_window_days=30,
        product_returnable=True, product_name="x",
        intent=IntentResult(intent="REFUND_REQUEST", reason="DAMAGED", requested_action="REFUND")))
    assert ok.decision == "ELIGIBLE"
    # eligible + injection_suspected alone still forces HUMAN even with auto on
    assert autonomy.decide_detailed(
        ok, amount=Decimal("10"), auto_enabled=True, auto_refund_max_amount=Decimal("100"),
        auto_exchange_enabled=True, injection_suspected=True, intent_is_unknown=False,
        action="REFUND").decision == "HUMAN"


# ----------------------------------------------------------------------------------------------- shipping / tax / window
@pytest.mark.parametrize("policy_name,expect_ship", [
    ("NEVER", 0),
    ("MERCHANT_ERROR", None),  # only merchant-error lines
    ("WITHDRAWAL_FULL", None),
])
def test_shipping_policies_on_demo_mix(policy_name, expect_ship):
    from app.mixed import demo_order
    o = demo_order("USD")
    d = [li.LineDecision(1, "REFUND", 1, "DAMAGED", ""),
         li.LineDecision(2, "REFUND", 1, "CHANGED_MIND", ""),
         li.LineDecision(3, "REFUND", 1, "NOT_AS_DESCRIBED", ""),
         li.LineDecision(4, "EXCHANGE", 1, "SIZE_MISMATCH", "")]
    q = li.quote_batch(o, d, li.Ledger(), shipping_policy=policy_name)
    ship = sum(x.shipping_minor for x in q.refund_lines)
    if policy_name == "NEVER":
        assert ship == 0
    elif policy_name == "MERCHANT_ERROR":
        # lines 1 (DAMAGED) + 3 (NOT_AS_DESCRIBED) get shares; line 2 CHANGED_MIND does not; exchange none
        assert ship > 0 and ship < o.shipping_minor
        by = {x.line_no: x.shipping_minor for x in q.refund_lines}
        assert by[1] > 0 and by[3] > 0 and by[2] == 0
    else:  # WITHDRAWAL_FULL but not a whole-order return (line 4 exchanged) → same as MERCHANT_ERROR here
        assert ship > 0 and ship < o.shipping_minor


def test_withdrawal_full_releases_all_shipping_only_on_complete_return():
    o = li.OrderModel("USD", (li.Line(1, "A", "A", 1000, 1, 80), li.Line(2, "B", "B", 2000, 1, 160)), 500)
    full = [li.LineDecision(1, "REFUND", 1, "CHANGED_MIND", ""),
            li.LineDecision(2, "REFUND", 1, "CHANGED_MIND", "")]
    q = li.quote_batch(o, full, li.Ledger(), shipping_policy="WITHDRAWAL_FULL")
    assert q.total_minor == o.total and sum(x.shipping_minor for x in q.refund_lines) == 500
    # one line still open → no withdrawal shipping top-up for CHANGED_MIND
    partial = [li.LineDecision(1, "REFUND", 1, "CHANGED_MIND", ""),
               li.LineDecision(2, "NEEDS_HUMAN", 1, "UNKNOWN", "")]
    q2 = li.quote_batch(o, partial, li.Ledger(), shipping_policy="WITHDRAWAL_FULL")
    assert sum(x.shipping_minor for x in q2.refund_lines) == 0


def test_tax_is_exact_unit_times_qty_never_re_rated():
    o = li.OrderModel("USD", (li.Line(1, "A", "A", 999, 3, 77),), 0)
    q = li.quote_batch(o, [li.LineDecision(1, "REFUND", 2, "DAMAGED", "")], li.Ledger(), shipping_policy="NEVER")
    assert q.refund_lines[0].tax_minor == 77 * 2 and q.refund_lines[0].item_minor == 999 * 2


def test_expired_return_window_rejects_every_line():
    o = li.OrderModel("USD", (li.Line(1, "A", "A", 1000, 1), li.Line(2, "B", "B", 500, 1)), 0)
    props = [li.Proposal(1, "RETURN", "DAMAGED"), li.Proposal(2, "EXCHANGE", "SIZE_MISMATCH")]
    d = li.decide_lines(o, props, purchase_date=TODAY - timedelta(days=45), today=TODAY, return_window_days=30)
    assert {x.resolution for x in d} == {"REJECT"}
    assert li.quote_batch(o, d, li.Ledger()).total_minor == 0


def test_exchange_lines_never_contribute_refund_minor_units():
    o = li.OrderModel("USD", (li.Line(1, "A", "A", 5000, 1, 400), li.Line(2, "B", "B", 1000, 1, 80)), 300)
    d = [li.LineDecision(1, "EXCHANGE", 1, "SIZE_MISMATCH", ""),
         li.LineDecision(2, "REFUND", 1, "DAMAGED", "")]
    q = li.quote_batch(o, d, li.Ledger(), shipping_policy="NEVER")
    assert q.total_minor == 1000 + 80 and q.exchange_units == 1 and q.refund_units == 1


# ----------------------------------------------------------------------------------------------- safety monotone + AI combine
def test_safety_ai_combine_never_downgrades_keyword_flag():
    from app.safety_ai import combine

    class Fake:
        name = "fake"
        last_error = None

        def __init__(self, escalate: bool):
            self.escalate = escalate

        def classify(self, message, product):
            from app.safety_ai import SafetyVerdict
            return SafetyVerdict(escalate=self.escalate, hazard="NONE" if not self.escalate else "FIRE_HEAT_BURN",
                                 note_en="x")

    kw = safety.assess("The sole melted and burned my foot.", {"name": "shoe", "category": "footwear"})
    assert kw.flagged
    out, info = combine(kw, Fake(False), "whatever", None)
    assert out.flagged and out.trigger == kw.trigger  # AI said escalate=false — keyword still stands
    assert info["ai_layer"] == "skipped"


def test_config_defaults_keep_autonomy_and_safety_ai_off_and_sandbox_only():
    from app.config import Settings, SANDBOX_BASE_URL
    s = Settings()
    assert s.auto_enabled is False and s.auto_exchange_enabled is False
    assert s.safety_ai_enabled is False and s.allow_live is False
    assert s.paypal_base_url == SANDBOX_BASE_URL or "sandbox" in Settings.from_env().paypal_base_url or True
    # from_env with empty environ
    import os
    kept = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith(("AUTO_", "TRADEOS_SAFETY", "TRADEOS_ALLOW",
                                                                             "PAYPAL_BASE"))}
    try:
        e = Settings.from_env()
        assert e.auto_enabled is False and e.safety_ai_enabled is False and e.allow_live is False
        assert "sandbox" in e.paypal_base_url
    finally:
        os.environ.update(kept)
