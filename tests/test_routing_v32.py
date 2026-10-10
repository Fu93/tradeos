"""v3.2 Safety Gate regression tests (new paraphrases; none copied from held-out sets).
Order of evaluation: order/product confirmed -> SAFETY GATE (catalogue safety class + extracted malfunction) -> intent/action
-> conflicts/policy -> supplier task last. The gate needs NO hazard words; refund intent never overrides it."""
from __future__ import annotations

from datetime import date

import pytest

from app.routing_v3 import ContextV3, ExtractionV3, ItemX, decide_v3

TODAY = date(2026, 10, 9)
KET, KET_C = "TO-60202", "quinn@example.test"   # MOCK kettle (MAINS_HEATING), 120 d
LAMP, LAMP_C = "TO-60212", "bo@example.test"    # MOCK desk lamp black (MAINS_ELECTRIC), 400 d
LAMPW, LAMPW_C = "TO-40011", "ola@example.test" # MOCK desk lamp white, dropship, 9 d
STOVE_C = "uma@example.test"                    # TO-60206 camping gas stove (GAS), 20 d
SHOE_C = "vic@example.test"                     # TO-60207 Trail Runner 43 (NONE), 100 d
BAG_C = "zoe@example.test"                      # TO-60208 backpack (NONE), 200 d, merchant warranty


def it(issue, ev, goals=(), quote=None, cur=None, req=None, comp=None, part=None):
    gs = [{"goal": g, "evidence": e} for g, e in goals]
    return ItemX(quote, ev, issue, comp, part, cur, req, gs, "SINGLE" if gs else "NONE")


def x(items, act="REQUEST", safety="NONE"):
    ev = next((g["evidence"] for i in items for g in i.goals), "")
    return ExtractionV3(ev, act, list(items), [], None, None, None, safety, 0.97)


def run(msg, ex, cust, linked=None):
    return decide_v3(ex, msg, ContextV3(cust, linked), TODAY)


def gated(d):
    return d.action == "HUMAN_REVIEW" and d.rule == "SG" and d.suggested_task is None


# ------------------------------------------------------------------ gate fires on safety classes, any wording
GATED = [  # (message, customer, issue evidence, goal, goal evidence) — model reports safety NONE in every case
    ("Order TO-60202: whenever it boils there's a whiff of scorched plastic. Please repair it.", KET_C, "a whiff of scorched plastic", "REPAIR", "Please repair it"),
    ("Pedido TO-60202: al hervir sale un olor raro, como a plástico. Quiero que lo reparen.", KET_C, "sale un olor raro, como a plástico", "REPAIR", "Quiero que lo reparen"),
    ("Bestellung TO-60202: Die Heizplatte unten reagiert nicht mehr, der Kocher bleibt aus. Bitte ersetzen.", KET_C, "Die Heizplatte unten reagiert nicht mehr", "REPLACE_SAME", "Bitte ersetzen"),
    ("訂單TO-60202：熱水壺放上去常常斷電，請幫我換新的。", KET_C, "放上去常常斷電", "REPLACE_SAME", "請幫我換新的"),
    ("注文TO-60202：ケトルの台が壊れてしまい、電源が入りません。交換してください。", KET_C, "ケトルの台が壊れてしまい", "REPLACE_SAME", "交換してください"),
    ("注文TO-60202：スイッチを入れるとfuseが飛んでしまいます。修理をお願いします。", KET_C, "fuseが飛んでしまいます", "REPAIR", "修理をお願いします"),
    ("Order TO-60202: it just stopped working this morning. Can you fix it?", KET_C, "it just stopped working", "REPAIR", "Can you fix it?"),
    ("訂單TO-60212：檯燈底座進水之後就怪怪的，可以維修嗎？", LAMP_C, "檯燈底座進水", "REPAIR", "可以維修嗎"),
    ("Bestellung TO-60212: Es ist Wasser im Fuß der Lampe, jetzt brummt sie. Bitte reparieren.", LAMP_C, "Es ist Wasser im Fuß der Lampe", "REPAIR", "Bitte reparieren"),
    ("Order TO-60212: the lamp randomly goes dark after a minute. Please replace it.", LAMP_C, "the lamp randomly goes dark", "REPLACE_SAME", "Please replace it"),
    ("Order TO-60206: the stove knob feels loose. Could you repair it?", STOVE_C, "the stove knob feels loose", "REPAIR", "Could you repair it?"),
]


@pytest.mark.parametrize("msg,cust,ev,goal,gev", GATED)
def test_any_malfunction_of_a_safety_class_product_goes_to_safety_review(msg, cust, ev, goal, gev):
    d = run(msg, x([it("DEFECT", ev, [(goal, gev)])]), cust)
    assert gated(d), d.decided_by
    assert d.derived["safety_gate"]["class"] in ("MAINS_HEATING", "MAINS_ELECTRIC", "GAS")


@pytest.mark.parametrize("msg,cust,ev,gev", [
    ("Order TO-60206: the gas valve sticks open a bit. Just refund me please.", STOVE_C, "the gas valve sticks open a bit", "Just refund me please"),
    ("Pedido TO-60206: la válvula del gas no cierra del todo. Solo quiero el reembolso.", STOVE_C, "la válvula del gas no cierra del todo", "Solo quiero el reembolso"),
    ("注文TO-60206：ガスのバルブがきちんと閉まりません。返金してください。", STOVE_C, "ガスのバルブがきちんと閉まりません", "返金してください"),
    ("Bestellung TO-60202: Der Wasserkocher schaltet sich ständig ab. Ich möchte mein Geld zurück.", KET_C, "Der Wasserkocher schaltet sich ständig ab", "Ich möchte mein Geld zurück"),
    ("訂單TO-60202：熱水壺一直跳掉，我要退款。", KET_C, "熱水壺一直跳掉", "我要退款"),
])
def test_safety_gate_precedes_the_refund_flow(msg, cust, ev, gev):
    d = run(msg, x([it("DEFECT", ev, [("REFUND", gev)])]), cust)
    assert gated(d) and d.refund_intent and "no automated refund flow" in d.reason


def test_gas_valve_refund_with_model_missing_the_defect_still_goes_to_human():
    msg = "Order TO-60206: the gas valve sticks open a bit. Just refund me please."
    d = run(msg, x([it("NO_ISSUE", None, [("REFUND", "Just refund me please")])]), STOVE_C)
    assert d.action == "HUMAN_REVIEW" and d.rule in ("SG", "V1")  # extra demote-only word signal (S3)


@pytest.mark.parametrize("msg,ev,goal,gev", [
    ("Order TO-60212: the LED module flickers non-stop. Please arrange a warranty repair.", "the LED module flickers non-stop", "REPAIR", "Please arrange a warranty repair"),
    ("Pedido TO-60212: la lámpara ya no enciende. ¿Me la pueden reparar?", "la lámpara ya no enciende", "REPAIR", "¿Me la pueden reparar?"),
    ("注文TO-60212：ライトが点かなくなりました。修理をお願いします。", "ライトが点かなくなりました", "REPAIR", "修理をお願いします"),
])
def test_safety_gate_precedes_supplier_task_creation(msg, ev, goal, gev):
    d = run(msg, x([it("DEFECT", ev, [(goal, gev)])]), LAMP_C)  # 400 d lamp: would be a supplier-warranty task in v3.1
    assert gated(d)


def test_part_need_on_gated_product_goes_to_safety_review():
    msg = "Order TO-60202: please send me a new lid KL-170-LID."
    d = run(msg, x([it("PART_NEED", "a new lid KL-170-LID", [("SEND_PART", "please send me a new lid KL-170-LID")], part="KL-170-LID")]), KET_C)
    assert gated(d)


# ------------------------------------------------------------------ rule 2: unmappable product + malfunction is never auto-released
@pytest.mark.parametrize("msg,cust,ev", [
    ("Hi, it stopped working after a week. Please repair it.", "nobody@example.test", "it stopped working after a week"),
    ("Hola, mi tostadora dejó de calentar. ¿Me la reparan, por favor?", "nobody@example.test", "mi tostadora dejó de calentar"),
    ("こんにちは。買った商品が動かなくなりました。修理してください。", "nobody@example.test", "買った商品が動かなくなりました"),
])
def test_unmapped_product_with_malfunction_is_not_auto_released(msg, cust, ev):
    d = run(msg, x([it("DEFECT", ev, [("REPAIR", msg.split("。")[-2] if "。" in msg else ev)])]), cust)
    assert d.action == "HUMAN_REVIEW" and d.rule == "SG" and d.derived["safety_gate"]["class"] == "UNKNOWN"


# ------------------------------------------------------------------ the gate stays scoped: low-risk malfunctions and non-malfunction flows proceed
def test_low_risk_malfunction_is_not_gated_shoe_task():
    msg = "Order TO-60207: the sole of my trainers is coming off. Please replace them."
    d = run(msg, x([it("DEFECT", "the sole of my trainers is coming off", [("REPLACE_SAME", "Please replace them")])]), SHOE_C)
    assert d.action == "CREATE_SUPPLIER_TASK" and d.derived["safety_gate"]["hit"] is False


def test_low_risk_malfunction_is_not_gated_backpack_direct():
    msg = "Bestellung TO-60208: Der Reißverschluss vom Rucksack ist kaputt. Bitte reparieren."
    d = run(msg, x([it("DEFECT", "Der Reißverschluss vom Rucksack ist kaputt", [("REPAIR", "Bitte reparieren")])]), BAG_C)
    assert d.action == "DIRECT_WORKFLOW" and d.rule == "V12"


def test_non_malfunction_flows_on_gated_products_proceed():
    # seller error on a lamp (not a malfunction): consistent with the record -> suggested task
    msg = "Order TO-40011: I ordered the white lamp and got a black one. Please send the white one."
    d = run(msg, x([it("WRONG_ITEM_OR_VARIANT", "got a black one", [("EXCHANGE_VARIANT", "Please send the white one")], cur="black one", req="the white one")]), LAMPW_C)
    assert d.action == "CREATE_SUPPLIER_TASK", d.decided_by
    # whole lamp never arrived (not a functional part) -> reship task
    d2 = run("Order TO-50170: my lamp never arrived. Please send it again.",
             x([it("MISSING_ITEM", "my lamp never arrived", [("RESHIP", "Please send it again")])]), "oli@example.test")
    assert d2.action == "CREATE_SUPPLIER_TASK", d2.decided_by
    # availability question about a kettle part -> support answers, not the gate
    d3 = run("Do you sell the kettle filter KL-170-FLT separately?",
             x([it("NO_ISSUE", None, [("INFORMATION", "Do you sell the kettle filter KL-170-FLT separately?")])], act="QUESTION"), KET_C)
    assert d3.rule == "V6"


# ------------------------------------------------------------------ typo robustness for order conflicts
@pytest.mark.parametrize("msg,cur,req", [
    ("Order TO-60212: I ordered the whte lamp but got a black one. Please send the white.", "a black one", "the whte lamp"),  # record black
    ("Pedido TO-60212: pedí la lámpara blnca y me llegó la negra. Envíenme la blanca.", "la negra", "la lámpara blnca"),
])
def test_typo_variant_claims_conflicting_with_record_go_to_human(msg, cur, req):
    d = run(msg, x([it("WRONG_ITEM_OR_VARIANT", msg.split(": ")[1].split(".")[0], [("EXCHANGE_VARIANT", msg.split(". ")[-1])], cur=cur, req=req)]), LAMP_C)
    assert d.action == "HUMAN_REVIEW" and d.rule == "V3", d.decided_by


def test_typo_even_if_consistent_is_uncertain_and_goes_to_human():
    msg = "Order TO-40011: I ordered the whte lamp, you sent a black one. Please send the right one."
    d = run(msg, x([it("WRONG_ITEM_OR_VARIANT", "you sent a black one", [("EXCHANGE_VARIANT", "Please send the right one")], cur="a black one", req="the whte lamp")]), LAMPW_C)
    assert d.action == "HUMAN_REVIEW" and d.rule == "V3"


def test_article_and_noun_around_variant_are_resolved_not_guessed():
    msg = "Pedido TO-40011: pedí la lámpara blanca y me llegó la negra. ¿Me envían la blanca?"
    d = run(msg, x([it("WRONG_ITEM_OR_VARIANT", "me llegó la negra", [("EXCHANGE_VARIANT", "¿Me envían la blanca?")], cur="la negra", req="la blanca")]), LAMPW_C)
    assert d.action == "CREATE_SUPPLIER_TASK" and d.derived["wrong_item_consistent"].startswith("ordered white")


def test_order_conflict_without_typo_goes_to_human():
    msg = "Order TO-60212: I definitely ordered white but you sent black. Swap it please."
    d = run(msg, x([it("WRONG_ITEM_OR_VARIANT", "you sent black", [("EXCHANGE_VARIANT", "Swap it please")], cur="black", req="white")]), LAMP_C)
    assert d.action == "HUMAN_REVIEW" and d.rule == "V3"
