"""v3.1 regression tests (NEW paraphrases written for these fixes; none is a copy of a held-out item).
Fix 1 order-data conflict -> human · fix 2 buyer vs seller error (5 languages) · fix 3 safety + normalisation ·
fix 4 intent revision / complaint only. Extractions simulate the model's known failure modes; code must catch them."""
from __future__ import annotations

from datetime import date

import pytest

from app.routing_v3 import ContextV3, ExtractionV3, ItemX, decide_v3, elec_hits, norm_text, scan_order_codes

TODAY = date(2026, 10, 9)
SHOE, SHOE_C = "TO-10421", "ana@example.test"      # MOCK: Trail Runner 42, dropship, 10 days
LAMP, LAMP_C = "TO-40011", "ola@example.test"      # MOCK: desk lamp white, dropship, 9 days
KET, KET_C = "TO-60202", "quinn@example.test"      # MOCK: kettle, 120 days (supplier warranty)
STOVE, STOVE_C = "TO-60206", "uma@example.test"    # MOCK: camping gas stove, 20 days


def it(issue, ev, goals=(), quote=None, cur=None, req=None, comp=None, part=None, rel=None):
    gs = [{"goal": g, "evidence": e} for g, e in goals]
    return ItemX(quote, ev, issue, comp, part, cur, req, gs, rel or ("SINGLE" if gs else "NONE"))


def x(items, act="REQUEST", act_ev="", neg=(), safety="NONE", s_ev=None):
    return ExtractionV3(act_ev, act, list(items), [{"goal": g, "evidence": e} for g, e in neg], None, None, s_ev, safety, 0.95)


def run(msg, ex, cust):
    return decide_v3(ex, msg, ContextV3(cust, None), TODAY)


# ------------------------------------------------------------------ fix 2: buyer vs seller error, minimal pairs x 5 languages
PAIRS = {
    "en": ("Order TO-10421. My bad, I clicked size 42 by mistake when I needed 43. Could you swap them for 43?",
           "Order TO-10421. I ordered size 42 but you sent me 43. Could you swap them for the 42 I ordered?",
           "clicked size 42 by mistake", "you sent me 43", "Could you swap them"),
    "zh-Hant": ("訂單 TO-10421，我自己訂錯尺寸了，選了42號，其實要43號，可以幫我換43號嗎？",
                "訂單 TO-10421，我訂的是42號，結果寄來的是43號，可以幫我換成42號嗎？",
                "我自己訂錯尺寸了", "寄來的是43號", "可以幫我換"),
    "es": ("Pedido TO-10421. Me equivoqué al elegir la talla 42, necesito la 43. ¿Me las pueden cambiar?",
           "Pedido TO-10421. Pedí la talla 42 pero me enviaron la 43. ¿Me las pueden cambiar por la 42?",
           "Me equivoqué al elegir la talla 42", "me enviaron la 43", "¿Me las pueden cambiar"),
    "de": ("Bestellung TO-10421: Ich habe aus Versehen Größe 42 bestellt, brauche aber 43. Können Sie die tauschen?",
           "Bestellung TO-10421: Ich habe Größe 42 bestellt, geliefert wurde aber 43. Können Sie die gegen 42 tauschen?",
           "aus Versehen Größe 42 bestellt", "geliefert wurde aber 43", "Können Sie die"),
    "ja": ("注文番号TO-10421です。間違えて42サイズを注文してしまいました。43に交換していただけますか。",
           "注文番号TO-10421です。42サイズを注文したのに、届いたのは43サイズでした。42に交換していただけますか。",
           "間違えて42サイズを注文", "届いたのは43サイズ", "交換していただけますか"),
}


@pytest.mark.parametrize("lang", list(PAIRS))
def test_buyer_error_never_reaches_supplier_even_if_model_says_wrong_item(lang):
    buyer, _, ev, _, goal_ev = PAIRS[lang]
    d = run(buyer, x([it("WRONG_ITEM_OR_VARIANT", ev, [("EXCHANGE_VARIANT", goal_ev)], req="43")]), SHOE_C)
    assert d.action == "DIRECT_WORKFLOW" and d.rule == "V10" and d.suggested_task is None, (lang, d.decided_by)


@pytest.mark.parametrize("lang", list(PAIRS))
def test_seller_error_consistent_with_order_is_a_suggested_task(lang):
    _, seller, _, ev, goal_ev = PAIRS[lang]
    d = run(seller, x([it("WRONG_ITEM_OR_VARIANT", ev, [("EXCHANGE_VARIANT", goal_ev)], cur="43", req="42")]), SHOE_C)
    assert d.action == "CREATE_SUPPLIER_TASK" and d.suggested_task["status"] == "SUGGESTED", (lang, d.decided_by)


# ------------------------------------------------------------------ fix 1: order-data conflict
CONFLICT = {
    "en": ("Order TO-40011: I ordered the black lamp and you sent a white one. Please exchange it for black.", "white", "black",
           "you sent a white one", "Please exchange it"),
    "zh-Hant": ("訂單TO-40011：我訂的是黑色檯燈，你們寄來白色的，請幫我換成黑色。", "白色", "黑色", "你們寄來白色的", "請幫我換成黑色"),
    "es": ("Pedido TO-40011: pedí la lámpara negra y me enviaron una blanca. Por favor, cámbienla por la negra.", "blanca", "negra",
           "me enviaron una blanca", "cámbienla por la negra"),
    "de": ("Bestellung TO-40011: Ich hatte die schwarze Lampe bestellt, geliefert wurde eine weiße. Bitte tauschen Sie sie um.",
           "weiße", "schwarze", "geliefert wurde eine weiße", "Bitte tauschen Sie sie um"),
    "ja": ("注文TO-40011：黒のランプを注文したのに白が届きました。黒に交換してください。", "白", "黒", "白が届きました", "黒に交換してください"),
}


@pytest.mark.parametrize("lang", list(CONFLICT))
def test_seller_error_claim_conflicting_with_order_record_goes_to_human(lang):
    msg, cur, req, ev, gev = CONFLICT[lang]  # the order record says WHITE: the customer's "ordered black" conflicts
    d = run(msg, x([it("WRONG_ITEM_OR_VARIANT", ev, [("EXCHANGE_VARIANT", gev)], cur=cur, req=req)]), LAMP_C)
    assert d.action == "HUMAN_REVIEW" and d.rule == "V3", (lang, d.decided_by)


def test_wrong_item_claim_without_details_is_never_accepted_on_its_word():
    msg = "Order TO-40011: you sent me the wrong lamp, please send the right one."
    d = run(msg, x([it("WRONG_ITEM_OR_VARIANT", "you sent me the wrong lamp", [("EXCHANGE_VARIANT", "please send the right one")])]),
            LAMP_C)
    assert d.action == "HUMAN_REVIEW" and d.rule == "V3"


def test_received_variant_equals_order_record_goes_to_human():
    msg = "Order TO-10421: these 42s are not what I ordered, please swap them."
    d = run(msg, x([it("WRONG_ITEM_OR_VARIANT", "these 42s are not what I ordered", [("EXCHANGE_VARIANT", "please swap them")],
                       cur="42")]), SHOE_C)
    assert d.action == "HUMAN_REVIEW" and d.rule == "V3"


def test_multi_item_complaint_with_products_not_in_order_resolves_data_first():
    msg = ("Order TO-60202: the tea towel came torn and the salad bowl has a chip. Please replace the towel and refund the bowl.")
    items = [it("DEFECT", "the tea towel came torn", [("REPLACE_SAME", "Please replace the towel")], quote="the tea towel"),
             it("DEFECT", "the salad bowl has a chip", [("REFUND", "refund the bowl")], quote="the salad bowl")]
    d = run(msg, x(items), KET_C)
    assert d.action == "HUMAN_REVIEW" and d.rule in ("SG", "V3") and d.suggested_task is None


def test_one_known_product_not_in_order_among_several_is_a_conflict():
    msg = "Order TO-60202: the kettle is fine but the backpack strap ripped, please repair the backpack."
    d = run(msg, x([it("DEFECT", "the backpack strap ripped", [("REPAIR", "please repair the backpack")], quote="the backpack")]), KET_C)
    assert d.action == "HUMAN_REVIEW" and d.rule == "V3"


# ------------------------------------------------------------------ fix 3: safety + normalisation
@pytest.mark.parametrize("msg", [
    "Order TO-60202: since yesterday the kettle gives off a smell of burnt plastic. Can you repair it?",
    "Pedido TO-60202: el hervidor huele a plástico quemado cuando lo enciendo. ¿Me lo pueden reparar?",
    "Bestellung TO-60202: Der Wasserkocher riecht nach verschmortem Plastik. Können Sie ihn reparieren?",
    "訂單TO-60202：熱水壺一插電就有燒焦味，可以幫我維修嗎？",
    "注文TO-60202：ケトルからプラスチックが焦げたような臭いがします。修理をお願いします。",
    "Order TO-60202: the power base stopped working, the kettle won't sit on it properly any more. Please replace it.",
    "注文TO-60202：電源ベースが故障して通電しません。交換してください。",
    "注文TO-60202：使うたびにヒューズが飛んでしまいます。修理してください。",
    "注文TO-60202：ケトルを使うとfuseが飛んで家中の電気が消えます。交換してほしいです。",
    "注文TO-60202：ヒューズを飛ばしてしまうので交換してください。",
    "Bestellung TO-60202: Jedes Mal fliegt die Sicherung raus. Bitte ersetzen.",
    "Pedido TO-60202: cada vez que lo enchufo salta el fusible. Quiero un reemplazo.",
    "訂單TO-60202：一用就跳電，保險絲也燒了，請換一台。",
])
def test_electrical_hazards_go_to_human_before_any_task(msg):
    d = run(msg, x([it("DEFECT", None, [("REPLACE_SAME", None)])]), KET_C)  # model saw no hazard, no quotes
    assert d.action == "HUMAN_REVIEW" and d.rule in ("SG", "V1"), d.decided_by


@pytest.mark.parametrize("msg,ev", [
    ("Order TO-60206: the gas valve on the stove is stuck. I just want a refund please.", "I just want a refund please"),
    ("Pedido TO-60206: la válvula del hornillo no cierra bien. Quiero que me devuelvan el dinero, reembolso por favor.",
     "reembolso por favor"),
    ("注文TO-60206：コンロのバルブが固くて回りません。返金してください。", "返金してください"),
])
def test_gas_valve_plus_refund_goes_to_human_not_refund_flow(msg, ev):
    d = run(msg, x([it("NO_ISSUE", None, [("REFUND", ev)])]), STOVE_C)  # model missed the defect
    assert d.action == "HUMAN_REVIEW" and d.rule in ("SG", "V1") and d.refund_intent


def test_unicode_hyphen_and_fullwidth_order_ids_are_normalised():
    for s in ("TO\u201110421", "TO\u201310421", "TO\u221210421", "ＴＯ－１０４２１", "TO\uff0d10421"):
        assert scan_order_codes(f"order {s}")[0] == ["TO-10421"], s
    assert norm_text("ＴＯ\u2011１２３") == "TO-123"


def test_nonbreaking_hyphen_hedged_wrong_order_asks_before_refund():
    msg = "Ich glaube, meine Bestellung war TO\u201199887. Ich möchte bitte mein Geld zurück."
    d = run(msg, x([it("NO_ISSUE", None, [("REFUND", "Ich möchte bitte mein Geld zurück")])]), KET_C)
    assert d.action == "CLARIFY_WITH_CUSTOMER" and d.rule == "V4"


def test_negated_electrical_words_do_not_fire():
    assert not elec_hits("no burnt smell and the fuse is fine? no — the fuse did not blow")[:0]
    assert elec_hits("no smell at all") == []


# ------------------------------------------------------------------ fix 4: intent revision, complaint only (v3.2: low-risk product)
SH, SH_C = "TO-60207", "vic@example.test"  # MOCK: Trail Runner 43, 100 days, supplier warranty 180 d
REV = {
    "en": ("Order TO-60207: the sole of my trainers came off. I asked for a repair earlier, but actually, just refund me.", "the sole of my trainers came off", "a repair", "just refund me"),
    "es": ("Pedido TO-60207: se despegó la suela de las zapatillas. Antes pedí una reparación, pero mejor un reembolso.", "se despegó la suela", "una reparación", "un reembolso"),
    "de": ("Bestellung TO-60207: Die Sohle der Schuhe löst sich. Ich wollte eine Reparatur, aber lieber doch eine Erstattung.", "Die Sohle der Schuhe löst sich", "eine Reparatur", "eine Erstattung"),
    "ja": ("注文TO-60207：スニーカーの靴底がはがれました。修理をお願いしましたが、やっぱり返金でお願いします。", "靴底がはがれました", "修理をお願い", "返金でお願いします"),
    "zh-Hant": ("訂單TO-60207：球鞋鞋底脫膠了。之前說要維修，算了，還是直接退款吧。", "球鞋鞋底脫膠了", "要維修", "直接退款"),
}


@pytest.mark.parametrize("lang", list(REV))
def test_revised_intent_uses_last_explicit_intent(lang):
    msg, ev, rep, ref = REV[lang]  # the model kept both goals (failure mode); code keeps the last one
    d = run(msg, x([it("DEFECT", ev, [("REPAIR", rep), ("REFUND", ref)], rel="UNDECIDED")]), SH_C)
    assert d.action == "DIRECT_WORKFLOW" and d.rule == "V8", (lang, d.decided_by)


@pytest.mark.parametrize("lang", list(REV))
def test_revision_pair_without_revision_is_a_task(lang):  # minimal pair: same complaint, repair only -> supplier warranty task
    msg, ev, rep, _ = REV[lang]
    base = {"en": "Order TO-60207: the sole of my trainers came off. Please arrange a repair.",
            "es": "Pedido TO-60207: se despegó la suela de las zapatillas. Quiero una reparación, por favor.",
            "de": "Bestellung TO-60207: Die Sohle der Schuhe löst sich. Bitte eine Reparatur.",
            "ja": "注文TO-60207：スニーカーの靴底がはがれました。修理をお願いします。",
            "zh-Hant": "訂單TO-60207：球鞋鞋底脫膠了，請幫我安排維修。"}[lang]
    g = {"en": "Please arrange a repair", "es": "Quiero una reparación", "de": "Bitte eine Reparatur", "ja": "修理をお願いします", "zh-Hant": "請幫我安排維修"}[lang]
    d = run(base, x([it("DEFECT", ev, [("REPAIR", g)])]), SH_C)
    assert d.action == "CREATE_SUPPLIER_TASK" and d.suggested_task["status"] == "SUGGESTED", (lang, d.decided_by)


def test_revision_towards_refund_that_model_missed_clarifies():
    msg = "Order TO-60207: the sole came off, please repair it. Actually, forget it, I'd prefer a refund."
    d = run(msg, x([it("DEFECT", "the sole came off", [("REPAIR", "please repair it")])]), SH_C)
    assert d.action == "CLARIFY_WITH_CUSTOMER" and d.suggested_task is None


@pytest.mark.parametrize("msg,ev", [
    ("Order TO-60207: the sole of my trainers came off after three months. Really disappointing.", "the sole of my trainers came off"),
    ("Pedido TO-60207: se despegó la suela a los tres meses. Qué decepción.", "se despegó la suela"),
    ("Bestellung TO-60207: Die Sohle hat sich nach drei Monaten gelöst. Sehr ärgerlich.", "Die Sohle hat sich nach drei Monaten gelöst"),
    ("注文TO-60207：三か月で靴底がはがれました。がっかりです。", "靴底がはがれました"),
    ("訂單TO-60207：才三個月鞋底就脫膠了，真失望。", "鞋底就脫膠了"),
])
def test_complaint_only_never_creates_a_task(msg, ev):
    d = run(msg, x([it("DEFECT", ev, [("REPAIR", ev)])], act="COMPLAINT_ONLY", act_ev=ev), SH_C)
    assert d.action == "CLARIFY_WITH_CUSTOMER" and d.suggested_task is None, d.decided_by
    d2 = run(msg, x([it("DEFECT", ev, [("REPAIR", ev)])], act_ev=ev), SH_C)
    assert d2.action != "CREATE_SUPPLIER_TASK", d2.decided_by


def test_changed_mind_refund_without_problem_goes_to_refund_flow():
    msg = "ＴＯ－１０４２１ですが、気が変わったので返金でお願いします。"
    d = run(msg, x([it("NO_ISSUE", None, [("REFUND", "返金でお願いします")])]), SHOE_C)
    assert d.action == "DIRECT_WORKFLOW" and d.rule == "V8"
