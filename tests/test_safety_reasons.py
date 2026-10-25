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

from app.safety import CLEAR_REASONS, FAULT_REASONS, GATED_CLASSES, assess, assess_any
from app.workflow import NEEDS_SAFETY, PENDING_APPROVAL
from tests.helpers import FakeExtractor, make_wf

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


def previous_rule(message, product, reason, intent=None) -> bool:
    """Safety Gate 3.2 for comparison: the reading only counted when it was DAMAGED."""
    return assess(message, product, reason if reason in FAULT_REASONS else None).flagged


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
    """Escalate-only, checked against the previous rule on every combination of a message pool, products, readings
    and intents: whatever 3.2 flagged, 3.3 flags too."""
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
