"""Safety Gate 3.3: for a hazard-class product, only a clearly harmless reason skips the safety review.

The word rules ("sparks", "burning smell", ...) can never list every way a customer describes a fault: on a kettle,
"keeps tripping", "hot to touch", "battery bulging" got past them. So for products in GATED_CLASSES the gate no
longer asks "did the customer use one of our fault words?" but "did the extractor read the return as one of three
reasons that say nothing about how the product works (wrong size, wrong item, changed mind)?". Everything else goes
to a person. These tests pin that, and that it only ever adds reviews (never removes one).
"""
from __future__ import annotations

import itertools
import json
import random
from pathlib import Path

import pytest

from app.safety import CLEAR_REASONS, GATED_CLASSES, SAFETY_RULE_VERSION, assess, assess_any
from app.workflow import NEEDS_SAFETY, PENDING_APPROVAL
from tests.helpers import FakeExtractor, case_from, make_app, make_wf
from tests.reference import safety_3_2

PHRASES = json.loads(Path("docs/eval/gated-phrasings.json").read_text())
REASONS = ("SIZE_MISMATCH", "DAMAGED", "WRONG_ITEM", "NOT_AS_DESCRIBED", "CHANGED_MIND", "OTHER", "UNKNOWN")
INTENTS = ("REFUND_REQUEST", "EXCHANGE_REQUEST", "ORDER_STATUS", "UNKNOWN")

HAZARD_PRODUCTS = {
    "MAINS_HEATING": {"name": "Electric Kettle 1.7L",
                      "category": "Home & Garden > Kitchen & Dining > Kitchen Appliances > Electric Kettles"},
    "GAS": {"name": "Portable Camping Gas Stove", "category": "Sporting Goods > Outdoor Recreation > Camping Stoves"},
    "BATTERY_THERMAL": {"name": "20000mAh Power Bank", "category": "Electronics > Electronics Accessories > Power"},
    "MAINS_ELECTRIC": {"name": "6-Outlet Surge Protector Power Strip",
                       "category": "Electronics > Electronics Accessories > Power > Surge Protectors"},
}
SHIRT = {"name": "Cotton Crew T-Shirt", "category": "Apparel & Accessories > Clothing > Shirts & Tops"}


def previous_rule(message, product, reason) -> bool:
    """The released Safety Gate 3.2, frozen in tests/reference/safety_3_2.py: an independent oracle, not the new code
    with an argument dropped (which would compare 3.3 with itself)."""
    return safety_3_2.assess(message, product, reason).flagged


def test_the_reference_is_the_released_3_2_rule():
    assert safety_3_2.SAFETY_RULE_VERSION == "safety-gate/3.2.0-main"
    assert "intent" not in safety_3_2.assess.__code__.co_varnames
    assert SAFETY_RULE_VERSION != safety_3_2.SAFETY_RULE_VERSION


def test_every_hazard_class_has_a_test_product():
    assert {assess(None, p).product_class for p in HAZARD_PRODUCTS.values()} == set(GATED_CLASSES)


def test_the_word_rules_miss_these_fault_descriptions():
    """The phrasing set is honest: these really get past the word lists, and these really do not."""
    kettle = HAZARD_PRODUCTS["MAINS_HEATING"]
    assert not [m for m in PHRASES["fault_missed_by_words"] if assess(m, kettle, None).flagged]
    assert all(assess(m, kettle, None).flagged for m in PHRASES["fault_caught_by_words"])
    assert len(PHRASES["fault_missed_by_words"]) >= 30


@pytest.mark.parametrize("cls", sorted(HAZARD_PRODUCTS))
@pytest.mark.parametrize("reason", sorted(set(REASONS) - CLEAR_REASONS))
def test_a_fault_on_a_hazard_product_goes_to_a_person_whatever_the_words(cls, reason):
    product = HAZARD_PRODUCTS[cls]
    for message in PHRASES["fault_missed_by_words"]:
        gate = assess(message, product, reason, "REFUND_REQUEST")
        assert gate.flagged, (cls, reason, message)
        assert gate.trigger in ("gated_product_unclear", "gated_product_fault")


def test_only_a_clearly_harmless_reason_skips_the_review():
    kettle = HAZARD_PRODUCTS["MAINS_HEATING"]
    for reason in CLEAR_REASONS:
        assert not assess("I'd like to return it.", kettle, reason, "REFUND_REQUEST").flagged
        # ...unless the words themselves report a fault or harm: the word rules still apply on top
        assert assess("Wrong size, and it sparked when I plugged it in.", kettle, reason, "REFUND_REQUEST").flagged
    unclear = assess("The colour is not what the listing showed.", kettle, "NOT_AS_DESCRIBED", "REFUND_REQUEST")
    assert unclear.flagged and unclear.trigger == "gated_product_unclear"
    assert "Only a wrong size, a wrong item or a change of mind skips this review" in unclear.summary


def test_an_order_status_question_is_not_a_return_and_other_products_are_unchanged():
    kettle = HAZARD_PRODUCTS["MAINS_HEATING"]
    assert not assess("Where is my order?", kettle, "OTHER", "ORDER_STATUS").flagged
    assert assess("Where is my order? It sparked.", kettle, "OTHER", "ORDER_STATUS").flagged  # words still count
    for reason in REASONS:  # a T-shirt is not a hazard-class product: no reading puts it under review by itself
        assert not assess("It isn't working properly.", SHIRT, reason, "REFUND_REQUEST").flagged


def test_the_new_rule_only_ever_adds_reviews():
    """Escalate-only, checked against the released 3.2 on a message pool x products x readings x intents: whatever 3.2
    flagged, 3.3 flags too."""
    pool = (PHRASES["fault_missed_by_words"] + PHRASES["fault_caught_by_words"] + PHRASES["benign"]
            + ["The sole melted in the heat and burned my foot.", "It caught fire!", ""])
    products = [*HAZARD_PRODUCTS.values(), SHIRT, None]
    rng = random.Random(33)
    combos = list(itertools.product(products, REASONS, INTENTS))
    checked = flagged_before = added = 0
    for message in pool:
        for product, reason, intent in rng.sample(combos, 40):
            before, after = previous_rule(message, product, reason), assess(message, product, reason, intent).flagged
            assert after or not before, (message, product, reason, intent)
            checked += 1
            flagged_before += before
            added += after and not before
    assert checked >= 2000 and flagged_before > 300 and added > 100  # the property is exercised both ways


def test_mixed_orders_use_the_same_rule_line_by_line():
    kettle, shirt = HAZARD_PRODUCTS["MAINS_HEATING"], SHIRT
    for order in ([shirt, kettle], [kettle, shirt]):  # whichever line the hazard product is on
        assert assess_any("It keeps tripping.", order, "OTHER", "REFUND_REQUEST").flagged, order
    assert not assess_any("I changed my mind.", [shirt, kettle], "CHANGED_MIND", "REFUND_REQUEST").flagged


@pytest.mark.parametrize("reason,expected", [("OTHER", NEEDS_SAFETY), ("NOT_AS_DESCRIBED", NEEDS_SAFETY),
                                             ("UNKNOWN", NEEDS_SAFETY), ("CHANGED_MIND", PENDING_APPROVAL)])
def test_end_to_end_a_hazard_product_order(settings, reason, expected):
    """Through the real workflow: a kettle bought by an agent from the catalogue, a message the word lists miss."""
    from app.catalog import CatalogProduct
    core = {"intent": "REFUND_REQUEST", "reason": reason, "requested_action": "REFUND"}
    wf, paypal = make_wf(settings, extractor=FakeExtractor(core=core))
    kettle = CatalogProduct(id="KTL1", title="Electric Kettle 1.7L", brand="", price="39.99", currency="USD",
                            category=HAZARD_PRODUCTS["MAINS_HEATING"]["category"], retailer="shop.example")
    order = wf.agents.place_order("Maria", agent="a", product=kettle)
    wf.agents.submit_request(order, "It keeps tripping the breaker.", agent="a", on_behalf_of="Maria")
    case = wf.db.get_case(order)
    assert case["status"] == expected and paypal.refund_capture.call_count == 0
    if expected == NEEDS_SAFETY:
        gate = next(e for e in wf.db.timeline(order) if e["stage"] == "safety")["detail"]
        assert gate["trigger"] == "gated_product_unclear" and gate["product_class"] == "MAINS_HEATING"


def test_the_money_backstop_applies_the_same_rule(settings):
    """A case whose stored reading no longer clears it (a tampered row, a direct POST) cannot be approved."""
    from app.catalog import CatalogProduct
    from app.workflow import RefundNotAllowed
    core = {"intent": "REFUND_REQUEST", "reason": "CHANGED_MIND", "requested_action": "REFUND"}
    wf, paypal = make_wf(settings, extractor=FakeExtractor(core=core))
    kettle = CatalogProduct(id="KTL1", title="Electric Kettle 1.7L", brand="", price="39.99", currency="USD",
                            category=HAZARD_PRODUCTS["MAINS_HEATING"]["category"], retailer="shop.example")
    order = wf.agents.place_order("Maria", agent="a", product=kettle)
    wf.agents.submit_request(order, "I changed my mind.", agent="a", on_behalf_of="Maria")
    assert wf.db.get_case(order)["status"] == PENDING_APPROVAL
    wf.db.update_case(order, intent_json=json.dumps({**core, "reason": "OTHER"}))
    with pytest.raises(RefundNotAllowed, match="Safety Gate"):
        wf.approve(order)
    assert paypal.refund_capture.call_count == 0


def test_end_to_end_an_order_status_question_on_a_hazard_product_is_not_a_safety_case(settings):
    from app.catalog import CatalogProduct
    core = {"intent": "ORDER_STATUS", "reason": "OTHER", "requested_action": "INFO"}
    wf, _ = make_wf(settings, extractor=FakeExtractor(core=core))
    kettle = CatalogProduct(id="KTL1", title="Electric Kettle 1.7L", brand="", price="39.99", currency="USD",
                            category=HAZARD_PRODUCTS["MAINS_HEATING"]["category"], retailer="shop.example")
    order = wf.agents.place_order("Maria", agent="a", product=kettle)
    wf.agents.submit_request(order, "When will it arrive?", agent="a", on_behalf_of="Maria")
    assert wf.db.get_case(order)["status"] != NEEDS_SAFETY


def test_the_measurement_script_offline():
    """scripts/eval_gate_phrasings.py with the keyword fallback (what runs when the LLM is down): every fault the word
    lists miss is caught, and the price is paid in harmless returns read as UNKNOWN going to a person."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("eval_gate", "scripts/eval_gate_phrasings.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from app.intent import KeywordIntentExtractor
    summary = module.run(KeywordIntentExtractor(), pace=0)["summary"]
    missed = summary["fault_missed_by_words"]
    assert missed["flagged_by_words_3_2"] == 0 and missed["flagged_by_gate_3_3"] == missed["judgements"] == 120
    assert summary["fault_caught_by_words"]["flagged_by_gate_3_3"] == summary["fault_caught_by_words"]["judgements"]
    assert summary["benign"]["flagged_by_gate_3_3"] <= summary["benign"]["judgements"]


def _kettle_case(settings, core, message):
    from app.catalog import CatalogProduct
    wf, paypal = make_wf(settings, extractor=FakeExtractor(core=core))
    kettle = CatalogProduct(id="KTL1", title="Electric Kettle 1.7L", brand="", price="39.99", currency="USD",
                            category=HAZARD_PRODUCTS["MAINS_HEATING"]["category"], retailer="shop.example")
    order = wf.agents.place_order("Maria", agent="a", product=kettle)
    wf.agents.submit_request(order, message, agent="a", on_behalf_of="Maria")
    return wf, paypal, order


@pytest.mark.parametrize("stored", [None, {}, {"intent": "REFUND_REQUEST"}])
def test_the_money_backstop_fails_closed_without_a_stored_reading(settings, stored):
    """No reading on the row (edited by hand, an older case): a hazard-class product is refused, not waved through."""
    from app.workflow import RefundNotAllowed
    core = {"intent": "REFUND_REQUEST", "reason": "CHANGED_MIND", "requested_action": "REFUND"}
    wf, paypal, order = _kettle_case(settings, core, "I changed my mind.")
    assert wf.db.get_case(order)["status"] == PENDING_APPROVAL
    wf.db.update_case(order, intent_json=None if stored is None else json.dumps(stored))
    with pytest.raises(RefundNotAllowed, match="Safety Gate"):
        wf.approve(order)
    assert paypal.refund_capture.call_count == 0


def test_the_backstop_still_lets_a_non_hazard_product_through_without_a_reading(settings):
    """Failing closed is for hazard-class products only: the demo sneakers (Case A) with no stored reading approve."""
    client, pp, wf = make_app(settings)
    cid = case_from(client.post("/demo/run/A", follow_redirects=False))
    case = wf.db.get_case(cid)
    if case["status"] != PENDING_APPROVAL:
        pytest.skip(f"Case A is {case['status']} in this configuration")
    wf.db.update_case(cid, intent_json=None)
    wf._refuse_if_safety(wf.db.get_case(cid))  # does not raise


def _mixed_with_kettle_on(settings, line_no):
    client, pp, wf = make_app(settings)
    cid = wf.mixed.create_case(message="Line by line as listed, please.")
    items = wf.db.get_items(cid)
    wf.db.upsert_product(items[line_no - 1]["sku"], "Electric kettle 1.7 L", "appliance", True, "79.00", "demo")
    wf.mixed.process(cid)
    return client, wf, cid


@pytest.mark.parametrize("line_no,reading,flagged", [(1, "DAMAGED", True), (2, "CHANGED_MIND", False),
                                                     (3, "NOT_AS_DESCRIBED", True), (4, "SIZE_MISMATCH", False)])
def test_mixed_intake_judges_each_line_with_its_own_reading(settings, line_no, reading, flagged):
    """Case M's per-line readings (DEMO_PROPOSALS): a kettle on a line read as damaged or not as described goes to a
    person at intake, with an audit entry and no batch; on a line read as a change of mind or a wrong size it does
    not. Before 3.3 intake judged the message alone and only the approve-time backstop caught line 3."""
    from app.mixed import DEMO_PROPOSALS
    assert next(p["reason"] for p in DEMO_PROPOSALS if p["line_no"] == line_no) == reading
    client, wf, cid = _mixed_with_kettle_on(settings, line_no)
    case = wf.db.get_case(cid)
    safety = [e for e in wf.db.timeline(cid) if e["stage"] == "safety"]
    if flagged:
        assert case["status"] == NEEDS_SAFETY and not wf.db.list_batches(cid)
        assert safety[0]["detail"]["product_class"] == "MAINS_HEATING"
        assert safety[0]["detail"]["rule_version"] == SAFETY_RULE_VERSION
        assert client.post(f"/cases/{cid}/approve", follow_redirects=False).status_code == 409
    else:
        assert case["status"] != NEEDS_SAFETY and not safety and wf.db.list_batches(cid)
    assert not wf.db.paypal_calls(cid, "refund_capture")


def test_the_rule_version_that_judged_a_case_is_on_its_hash_chain(settings):
    core = {"intent": "REFUND_REQUEST", "reason": "CHANGED_MIND", "requested_action": "REFUND"}
    wf, _, order = _kettle_case(settings, core, "I changed my mind.")
    intent = next(e for e in wf.db.timeline(order) if e["stage"] == "intent")["detail"]
    assert intent["safety_gate"] == {"flagged": False, "rule_version": SAFETY_RULE_VERSION}
    wf2, _, held = _kettle_case(settings, {**core, "reason": "OTHER"}, "It keeps tripping.")
    safety = next(e for e in wf2.db.timeline(held) if e["stage"] == "safety")["detail"]
    assert safety["rule_version"] == SAFETY_RULE_VERSION
    assert wf.db.verify_chain(order)["ok"]


def test_known_gap_two_reasons_in_one_message(settings):
    """Documented limit (docs/safety-gate.md): one reason per message. When the reading is a clear reason and the
    fault is described in words on no list, the return is not held. Pinned so a fix shows up as a change here."""
    kettle = HAZARD_PRODUCTS["MAINS_HEATING"]
    assert not assess("I changed my mind, it also keeps tripping.", kettle, "CHANGED_MIND", "REFUND_REQUEST").flagged
    assert not assess("Too small, and the cord is frayed.", kettle, "SIZE_MISMATCH", "REFUND_REQUEST").flagged


def test_the_live_measurement_refuses_keyword_readings():
    """A live run where the model fails on a message stops instead of recording keyword readings as model readings."""
    import importlib.util
    from app.intent import Extraction, KeywordIntentExtractor
    spec = importlib.util.spec_from_file_location("eval_gate", "scripts/eval_gate_phrasings.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Down:
        name = "llm:test"

        def extract(self, message):
            fb = KeywordIntentExtractor().extract(message)
            return Extraction(result=fb.result, extractor="keyword (LLM unavailable)", llm_unavailable=True,
                              note="LLM call failed (HTTP 429)")
    with pytest.raises(module.FallbackDetected, match="nothing written"):
        module.run(Down(), pace=0, live=True)


def test_the_mixed_backstop_fails_closed_on_a_line_without_a_reading(settings):
    """A kettle on line 2 (read CHANGED_MIND) gets a batch; if that line's stored reading disappears, approval of the
    batch is refused rather than treated as clear."""
    from app import lineitems as li
    client, wf, cid = _mixed_with_kettle_on(settings, 2)
    batch = wf.db.list_batches(cid)[0]
    assert batch["status"] == "PROPOSED"
    wf.db.update_item(cid, 2, proposal_json=None)
    r = client.post(f"/cases/{cid}/batches/{batch['id']}/approve", follow_redirects=False,
                    data={"expected_total": li.to_str(batch["amount_minor"], batch["currency"]),
                          "expected_hash": batch["items_hash"]})
    assert r.status_code == 409 and "Needs human safety review" in r.text
    assert not wf.db.paypal_calls(cid, "refund_capture")
