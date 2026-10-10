"""Held-out v4 design grid (v3.2 round, SAFETY-HEAVY). Counterexample-heavy. Written AFTER the v3.1 fixes and BEFORE any v4 message
was generated, labelled or run. Fresh MOCK orders (TO-96xxx) and customers.

Produces docs/eval/v3/heldout-v4-design.json and app/routing_data_v4.py (MOCK).
`designed_action` is the design intention (composition targets + a third label source); labels come from two LLM judges
(different families) + adjudication with labelling-guide-v3.2.md. Briefs describe the customer's situation only.
Normalisation traps: after generation, the order id in the text is rewritten with the recorded hyphen / width variant.
"""
import json
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
rng = random.Random(20261011)
LANGS = ["en", "zh-Hant", "es", "de", "ja"]
GENS = ["nvidia/nemotron-3-super-120b-a12b", "meta/muse-glimmer-30b", "z-ai/glm-5.3", "deepseek-ai/deepseek-v4.1-flash"]
STYLES = ["short and to the point", "polite and a bit formal", "casual, with a typo or two", "annoyed but civil",
          "long-winded with some irrelevant detail and a sign-off", "very brief, like a phone message",
          "friendly and chatty", "mixes in one or two English words (if not writing in English)"]
FIRST = ["Akira", "Bea", "Chiara", "Diego", "Emma", "Fumiko", "Gonzalo", "Hanna", "Isamu", "Julia", "Kai", "Luis", "Mina",
         "Noah", "Oskar", "Paula", "Rin", "Sofia", "Taro", "Ulla", "Valeria", "Wen", "Yuki", "Zoe"]
orders, cells = [], []
_oid, _cust = [96000], [0]


def new_customer():
    _cust[0] += 1
    n = FIRST[_cust[0] % len(FIRST)]
    return f"{n.lower()}.v4{_cust[0]:03d}@example.test", n


def new_order(c, days, lines):
    _oid[0] += 1
    oid = f"TO-{_oid[0]}"
    orders.append({"order_id": oid, "customer": c, "days_ago": days, "lines": lines})
    return oid


def line(sku, variant, qty=1, logistics="DELIVERED", **lg):
    return {"sku": sku, "variant": variant, "qty": qty,
            "logistics": None if logistics is None else {"status": logistics, "carrier": "MockPost", **lg}}


P = {"TRAIL-RUNNER-42": "Trail Runner sneakers", "CITY-JACKET": "City rain jacket", "BACKPACK-30L": "Daypack 30L backpack",
     "BREW-KETTLE": "1.7 L electric kettle", "DESK-LAMP": "LED desk lamp", "CAMP-STOVE": "camping gas stove",
     "SALE-SOCKS": "merino socks (bought on final sale)"}


def langs(n):
    s = rng.randrange(5)
    return [LANGS[(s + i) % 5] for i in range(n)]


def cell(kind, lang, brief, c, oid, designed, cite="exact", linked=None, tags=(), slice_=None, other=None, variant=None):
    ref = {"exact": f"Mention your order number exactly as {oid}.",
           "none": "Do not mention any order number.",
           "malformed": f"You mistype your order number: write it exactly as {other} (never write it correctly).",
           "hedged_bad": f"You are not sure of your order number; say you think it is {other} (express the uncertainty naturally).",
           "other": f"State your order number confidently as {other}."}[cite]
    cells.append({"kind": kind, "lang": lang, "brief": brief, "ref": ref, "customer": c, "linked_order": linked,
                  "order": oid, "cited_mode": cite, "designed_action": designed, "tags": list(tags),
                  "slice": slice_ or "other", "id_variant": variant, "cited_other": other})


T, D, H, C = "CREATE_SUPPLIER_TASK", "DIRECT_WORKFLOW", "HUMAN_REVIEW", "CLARIFY_WITH_CUSTOMER"
FK = ["no longer heats the water", "the on/off switch won't stay down", "the lid hinge snapped", "switches itself off after a few seconds",
      "the water gauge cracked and drips"]
FL = ["flickers all the time", "won't turn on any more", "the arm joint snapped", "the dimmer button stopped responding"]


FK = ["no longer heats the water", "the on/off switch won't stay down", "switches itself off after a few seconds",
      "takes forever to boil now", "the light comes on but nothing happens"]
FL = ["flickers all the time", "won't turn on any more", "the dimmer button stopped responding", "goes dark after a few minutes"]
SH = lambda: str(rng.choice(range(39, 45)))
# ------------------------------------------------------------------ supplier-task positives (non-malfunction or low-risk malfunction)
for lg in langs(10):
    c, nm = new_customer(); s = rng.choice(range(39, 45)); d = rng.choice([4, 9, 14, 21])
    oid = new_order(c, d, [line("TRAIL-RUNNER-42", str(s))]); t = s + rng.choice([1, -1])
    cell("exch_shoe_size", lg, f"You are {nm}. Your Trail Runner sneakers in EU size {s} ({d} days old) don't fit. Ask to swap "
         f"them for size {t}.", c, oid, T, slice_="normal_task")
for lg in langs(10):
    c, nm = new_customer(); s = rng.choice(range(39, 45)); oid = new_order(c, rng.choice([3, 6, 11]), [line("TRAIL-RUNNER-42", str(s))])
    got = s + rng.choice([1, -1, 2])
    cell("seller_wrong_size", lg, f"You are {nm}. You ordered Trail Runner sneakers in size {s}; the box contained size {got} "
         f"(the shop's mistake; state both sizes). Ask for size {s}.", c, oid, T, slice_="buyer_vs_seller", tags=["pair:seller"])
for lg in langs(8):
    c, nm = new_customer(); v, o = rng.choice([("white", "black"), ("black", "white")]); oid = new_order(c, rng.choice([4, 8]), [line("DESK-LAMP", v)])
    cell("seller_wrong_colour_lamp", lg, f"You are {nm}. You ordered the {v} LED desk lamp; the shop sent a {o} one (state both "
         f"colours). The lamp works fine. Ask for the {v} one.", c, oid, T, slice_="buyer_vs_seller", tags=["pair:seller"])
for lg in langs(6):
    c, nm = new_customer(); oid = new_order(c, rng.choice([5, 10]), [line("CITY-JACKET", "M")])
    cell("exch_jacket_L", lg, f"You are {nm}. Your City rain jacket in M is too tight. Ask to exchange it for L.", c, oid, T, slice_="normal_task")
for lg in langs(8):
    c, nm = new_customer(); oid = new_order(c, rng.choice([7, 10]), [line("DESK-LAMP", "black", logistics="LOST")])
    cell("reship_lamp", lg, f"You are {nm}. The desk lamp you ordered never arrived; tracking stopped a week ago. Ask them to "
         "send it again.", c, oid, T, slice_="normal_task")
for lg in langs(5):
    c, nm = new_customer(); oid = new_order(c, rng.choice([8, 12]), [line("BREW-KETTLE", "standard", logistics="LOST")])
    cell("reship_kettle", lg, f"You are {nm}. The electric kettle you ordered never arrived (tracking frozen). Ask them to send "
         "another one.", c, oid, T, slice_="normal_task")
for lg in langs(6):
    c, nm = new_customer(); oid = new_order(c, rng.choice([7, 13]), [line("TRAIL-RUNNER-42", SH(), logistics="LOST")])
    cell("reship_shoe", lg, f"You are {nm}. Your sneakers never arrived; tracking has been stuck for ten days. Ask them to send "
         "them again.", c, oid, T, slice_="normal_task")
for lg in langs(10):
    c, nm = new_customer(); d = rng.choice([45, 70, 100, 150]); oid = new_order(c, d, [line("TRAIL-RUNNER-42", SH())])
    cell("shoe_warranty", lg, f"You are {nm}. Your Trail Runner sneakers ({d} days old) "
         f"{rng.choice(['have a sole peeling off', 'split along the seam', 'lost an eyelet and the upper tore'])}. Ask for a "
         f"{rng.choice(['replacement pair', 'repair'])}.", c, oid, T, slice_="low_risk_malfunction")
for lg in langs(4):
    c, nm = new_customer(); oid = new_order(c, 8, [line("DESK-LAMP", "black", logistics="LOST")])
    cell("linked_reship_lamp", lg, f"You are {nm}. Your desk lamp never arrived. Ask them to send it again.", c, oid, T,
         cite="none", linked=oid, slice_="normal_task")
for i, lg in enumerate(langs(4)):
    c, nm = new_customer(); s = rng.choice(range(39, 44)); oid = new_order(c, 6, [line("TRAIL-RUNNER-42", str(s))])
    cell("norm_valid_task", lg, f"You are {nm}. Your sneakers in size {s} are too small. Ask to exchange them for size {s + 1}.",
         c, oid, T, slice_="normalisation", variant=["\u2011", "\u2013", "fullwidth", "\u2212"][i])
# ------------------------------------------------------------------ SAFETY (gated classes; ANY malfunction -> human safety review)
def safety(kind, n, sku, variant, days, brief, tags=()):
    for lg in langs(n):
        c, nm = new_customer(); d = rng.choice(days); oid = new_order(c, d, [line(sku, variant)])
        b = brief() if callable(brief) else brief
        cell(kind, lg, f"You are {nm}. Your {P[sku]} was bought {d} days ago. {b}", c, oid, H, slice_="safety", tags=["safety", *tags])
GOAL = lambda: rng.choice(["Ask for a repair.", "Ask for a replacement.", "Ask for a refund.", "Ask them to fix it."])
safety("safety_kettle_plain", 10, "BREW-KETTLE", "standard", [40, 90, 150, 220],
       lambda: f"It {rng.choice(FK)}. Describe it plainly (no mention of smell, smoke, sparks or heat). {GOAL()}", tags=["no_hazard_words"])
safety("safety_kettle_smell", 6, "BREW-KETTLE", "standard", [60, 180],
       lambda: f"It gives off a {rng.choice(['burnt plastic', 'hot electrical', 'melting'])} smell when it boils. {GOAL()}")
safety("safety_kettle_base", 6, "BREW-KETTLE", "standard", [80, 200],
       lambda: f"The power base is faulty: {rng.choice(['the kettle no longer powers on when placed on it', 'the base is cracked', 'the contacts wobble and it cuts out'])}. {GOAL()}")
safety("safety_kettle_cutout", 6, "BREW-KETTLE", "standard", [30, 120],
       lambda: f"It keeps cutting the power / tripping the breaker or the fuse when switched on. {GOAL()}")
safety("safety_water_ingress", 6, "DESK-LAMP", "black", [60, 150],
       lambda: f"Water got inside the lamp's foot/base and now it {rng.choice(['buzzes', 'flickers', 'does not switch on'])}. {GOAL()}")
safety("safety_lamp_plain", 10, "DESK-LAMP", "white", [50, 150, 300, 420],
       lambda: f"It {rng.choice(FL)}. Describe it plainly (no smoke, sparks, smell or heat). {GOAL()}", tags=["no_hazard_words"])
safety("safety_lamp_part", 4, "DESK-LAMP", "white", [100, 200],
       lambda: f"The {rng.choice(['LED module (part DL-LED-5W) died', 'switch broke off'])}. Ask them to send a replacement part.")
safety("safety_kettle_part", 4, "BREW-KETTLE", "standard", [100, 240],
       lambda: "The lid no longer locks shut so the kettle doesn't switch off by itself. Ask for a new lid, part KL-170-LID.")
safety("safety_gas_refund", 7, "CAMP-STOVE", "standard", [10, 20, 60],
       lambda: f"The gas valve or control knob {rng.choice(['sticks and does not close fully', 'is loose', 'turns without doing anything'])}. "
               "You only want a refund.", tags=["refund+safety"])
safety("safety_gas_repair", 5, "CAMP-STOVE", "standard", [40, 100],
       lambda: f"The {rng.choice(['ignition clicks but will not light', 'flame is very uneven', 'hose connector does not seal well'])}. {GOAL()}")
safety("safety_kettle_refund_new", 5, "BREW-KETTLE", "standard", [5, 12, 20],
       lambda: f"It {rng.choice(FK)}. Ask for a refund.", tags=["refund+safety", "no_hazard_words"])
for lg in ["ja", "ja", "ja"]:
    c, nm = new_customer(); oid = new_order(c, 90, [line("BREW-KETTLE", "standard")])
    cell("safety_fuse_ja", lg, f"You are {nm}. Every time you switch on your electric kettle, the fuse blows. Write the English word "
         "'fuse' inside your Japanese sentence. Ask for a replacement.", c, oid, H, slice_="safety", tags=["safety"])
for lg in langs(4):
    c, nm = new_customer(); oid = new_order(c, 150, [line("BREW-KETTLE", "standard")])
    cell("safety_complaint_only", lg, f"You are {nm}. Your electric kettle (150 days old) stopped heating. Just vent: do NOT ask "
         "for anything.", c, oid, H, slice_="safety", tags=["safety", "complaint_only"])
# ------------------------------------------------------------------ unmapped product + malfunction (rule 2)
for lg in langs(5):
    c, nm = new_customer()
    cell("unmapped_no_ref", lg, f"You are {nm}. Something you bought from the shop stopped working. Do not name the product and do "
         "not give an order number. Ask for a repair.", c, None, H, cite="none", slice_="unmapped", tags=["unmapped"])
for lg in langs(4):
    c, nm = new_customer()
    cell("unmapped_unknown_product", lg, f"You are {nm}. Your {rng.choice(['toaster', 'hair dryer', 'space heater', 'blender'])} "
         "from the shop stopped working. No order number. Ask for a replacement.", c, None, H, cite="none", slice_="unmapped", tags=["unmapped"])
# ------------------------------------------------------------------ low-risk malfunctions (must NOT be gated)
for lg in langs(6):
    c, nm = new_customer(); oid = new_order(c, 100, [line("BACKPACK-30L", "black")])
    cell("backpack_warranty", lg, f"You are {nm}. The {rng.choice(['zip', 'buckle', 'shoulder strap'])} of your Daypack 30L "
         "(100 days old) broke. Ask for a repair.", c, oid, D, slice_="low_risk_malfunction")
for lg in langs(6):
    c, nm = new_customer(); sku = rng.choice(["CITY-JACKET", "BACKPACK-30L"])
    oid = new_order(c, 12, [line(sku, {"CITY-JACKET": "M", "BACKPACK-30L": "navy"}[sku])])
    cell("lowrisk_refund", lg, f"You are {nm}. Your {P[sku]} has a {rng.choice(['torn seam', 'broken zip', 'leaking seam'])}. Ask for "
         "a refund (nothing else).", c, oid, D, slice_="low_risk_malfunction")
for lg in langs(5):
    c, nm = new_customer(); oid = new_order(c, 120, [line("TRAIL-RUNNER-42", SH())])
    cell("lowrisk_complaint_only", lg, f"You are {nm}. Your sneakers' sole started peeling after four months. Just vent: do NOT ask "
         "for anything.", c, oid, C, slice_="low_risk_malfunction", tags=["complaint_only"])
# ------------------------------------------------------------------ buyer vs seller, conflicts, typos
for lg in langs(10):
    c, nm = new_customer(); s = rng.choice(range(39, 45)); oid = new_order(c, rng.choice([3, 8]), [line("TRAIL-RUNNER-42", str(s))])
    cell("buyer_wrong_size", lg, f"You are {nm}. You ordered Trail Runner sneakers in size {s} by your own mistake (you wear "
         f"{s + 1}); the shop sent exactly that. Admit the mistake and ask to exchange for size {s + 1}.", c, oid, D,
         slice_="buyer_vs_seller", tags=["pair:buyer"])
for lg in langs(6):
    c, nm = new_customer(); v, o = rng.choice([("white", "black"), ("black", "white")]); oid = new_order(c, 5, [line("DESK-LAMP", v)])
    cell("buyer_wrong_colour", lg, f"You are {nm}. You ordered and received the {v} LED desk lamp, but you picked the wrong colour "
         f"yourself. Ask to exchange it for {o}.", c, oid, D, slice_="buyer_vs_seller", tags=["pair:buyer"])
for lg in langs(6):
    c, nm = new_customer(); v, o = rng.choice([("white", "black"), ("black", "white")]); oid = new_order(c, 6, [line("DESK-LAMP", v)])
    cell("conflict_lamp_colour", lg, f"You are {nm}. You believe you ordered the {o} LED desk lamp, and a {v} one arrived. Say the "
         f"shop sent the wrong colour and ask for the {o} one.", c, oid, H, slice_="order_conflict")
for lg in ["en", "es", "de", "en", "zh-Hant", "ja"]:
    c, nm = new_customer(); oid = new_order(c, 6, [line("DESK-LAMP", "black")])
    cell("conflict_typo", lg, f"You are {nm}. You believe you ordered the white LED desk lamp and a black one arrived. When you write "
         "the colour you ordered, misspell it once (e.g. 'whte', 'blnaca', 'weis'); write it correctly elsewhere if you like. Ask for "
         "the white one.", c, oid, H, slice_="order_conflict", tags=["typo"])
for lg in langs(6):
    c, nm = new_customer(); s = rng.choice(range(40, 45)); oid = new_order(c, 5, [line("TRAIL-RUNNER-42", str(s))])
    cell("conflict_shoe_size", lg, f"You are {nm}. You believe you ordered size {s - 1} sneakers; the box had size {s}. Say the shop "
         f"sent the wrong size and ask for {s - 1}.", c, oid, H, slice_="order_conflict")
for lg in langs(5):
    c, nm = new_customer(); oid = new_order(c, 20, [line("BACKPACK-30L", "navy")])
    cell("conflict_product_not_in_order", lg, f"You are {nm}. Your {rng.choice(['City rain jacket', 'Trail Runner sneakers'])} from "
         "this order is torn. Ask for a replacement.", c, oid, H, slice_="order_conflict")
for lg in langs(4):
    c, nm = new_customer(); c2, _ = new_customer(); oid = new_order(c2, 30, [line("TRAIL-RUNNER-42", "42")])
    cell("other_customer", lg, f"You are {nm}. Your sneakers are too small. Ask to exchange them for size 43.", c, oid, H, slice_="order_conflict")
# ------------------------------------------------------------------ intent revision / no explicit request
for lg in langs(8):
    c, nm = new_customer(); oid = new_order(c, 15, [line("TRAIL-RUNNER-42", SH())])
    cell("revision_to_refund", lg, f"You are {nm}. The sole of your new sneakers came loose. First ask for a replacement pair, then "
         "change your mind in the same message and say you just want a refund.", c, oid, D, slice_="intent_revision")
for lg in langs(5):
    c, nm = new_customer(); oid = new_order(c, 15, [line("CITY-JACKET", "M")])
    cell("revision_ambiguous", lg, f"You are {nm}. Your City rain jacket's zip broke. You start asking for a repair, wonder about a "
         "refund, and end the message undecided.", c, oid, C, slice_="intent_revision")
for lg in langs(5):
    c, nm = new_customer(); oid = new_order(c, 20, [line("BACKPACK-30L", "black")])
    cell("complaint_only_bag", lg, f"You are {nm}. Your backpack's strap ripped after three weeks. Just vent: do NOT ask for anything.",
         c, oid, C, slice_="complaint_only")
# ------------------------------------------------------------------ other negatives
for lg in langs(8):
    c, nm = new_customer(); oid = new_order(c, 150, [line("BREW-KETTLE", "standard")]) if rng.random() < .5 else None
    cell("availability_q", lg, f"You are {nm}. Ask only whether the shop sells the kettle limescale filter KL-170-FLT separately and "
         "if it is in stock. Do not ask them to send anything.", c, oid, H, cite="exact" if oid else "none")
for lg in langs(5):
    c, nm = new_customer()
    cell("policy_q", lg, f"You are {nm}. Ask how long the return window is. No order problem.", c, None, H, cite="none")
for lg in langs(5):
    c, nm = new_customer(); oid = new_order(c, 10, [line("TRAIL-RUNNER-42", "42")])
    cell("malformed_ref", lg, f"You are {nm}. Your Trail Runner sneakers in 42 are too small. Ask to exchange them for 43.", c, oid, C,
         cite="malformed", other=rng.choice([f"WO-{oid[3:]}", f"T0-{oid[3:]}", f"#A{oid[3:]}"]))
for lg in langs(5):
    c, nm = new_customer(); new_order(c, 10, [line("CITY-JACKET", "M")])
    cell("no_order_ref", lg, f"You are {nm}. Your City rain jacket in M is too small. Ask to exchange for L.", c, None, C, cite="none")
for lg in langs(5):
    c, nm = new_customer(); oid = new_order(c, 8, [line("CITY-JACKET", "S")])
    cell("jacket_in_stock", lg, f"You are {nm}. Your City rain jacket in S is too small. Ask to exchange for M.", c, oid, D)
for lg in langs(4):
    c, nm = new_customer(); oid = new_order(c, 6, [line("SALE-SOCKS", "M")])
    cell("socks_final_sale", lg, f"You are {nm}. Your merino socks (final sale) in M are too big. Ask to exchange for S.", c, oid, D)
for lg in langs(4):
    c, nm = new_customer(); oid = new_order(c, 3, [line("TRAIL-RUNNER-42", "44", logistics="IN_TRANSIT", tracking="MP99887766")])
    cell("in_transit", lg, f"You are {nm}. Your sneakers (ordered 3 days ago) haven't arrived. Ask them to send them again.", c, oid, D)
for lg in langs(5):
    c, nm = new_customer(); oid = new_order(c, 9, [line("DESK-LAMP", "white")])
    cell("delivered_claims_missing", lg, f"You are {nm}. Your desk lamp never arrived. Ask them to send it again.", c, oid, H)
for lg in langs(8):
    c, nm = new_customer(); sku = rng.choice(["TRAIL-RUNNER-42", "CITY-JACKET"])
    oid = new_order(c, 12, [line(sku, {"TRAIL-RUNNER-42": "42", "CITY-JACKET": "M"}[sku])])
    cell("refund_changed_mind", lg, f"You are {nm}. You simply changed your mind about the {P[sku]}. Ask for a refund.", c, oid, D)
for i, lg in enumerate(langs(4)):
    c, nm = new_customer(); oid = new_order(c, 10, [line("CITY-JACKET", "M")])
    cell("norm_valid_refund", lg, f"You are {nm}. Your rain jacket's seam is torn. Ask for a refund.", c, oid, D, slice_="normalisation",
         variant=["\u2010", "fullwidth", "\u2011", "\u2013"][i])
for lg in langs(6):  # gated-class product, NO malfunction: proceeds normally (scope check)
    c, nm = new_customer(); sku = rng.choice(["BREW-KETTLE", "DESK-LAMP"]); oid = new_order(c, 9, [line(sku, "standard" if sku == "BREW-KETTLE" else "white")])
    cell("gated_class_changed_mind_refund", lg, f"You are {nm}. Your {P[sku]} works perfectly, you just changed your mind. Ask for a "
         "refund.", c, oid, D, slice_="gated_no_malfunction")
for lg in langs(4):
    c, nm = new_customer(); d = rng.choice([60, 120]); oid = new_order(c, d, [line("TRAIL-RUNNER-42", SH())])
    cell("shoe_warranty_b", lg, f"You are {nm}. The insole of your Trail Runner sneakers ({d} days old) came apart and the heel "
         "lining ripped. Ask for a replacement pair.", c, oid, T, slice_="low_risk_malfunction")
for lg in langs(4):
    c, nm = new_customer(); s = rng.choice(range(39, 45)); oid = new_order(c, 7, [line("TRAIL-RUNNER-42", str(s))])
    cell("exch_shoe_size_b", lg, f"You are {nm}. Your sneakers in size {s} are a bit big. Ask to exchange them for size {s - 1}.", c,
         oid, T, slice_="normal_task")
for lg in langs(4):
    c, nm = new_customer(); oid = new_order(c, 4, [line("CITY-JACKET", "M")])
    cell("buyer_wrong_jacket", lg, f"You are {nm}. You ordered the City rain jacket in M but meant to order S (your mistake). "
         "Ask to exchange for S.", c, oid, D, slice_="buyer_vs_seller", tags=["pair:buyer"])
for lg in langs(3):
    c, nm = new_customer()
    cell("thanks_other", lg, f"You are {nm}. Short thank-you note: fast delivery, love the kettle.", c, None, H, cite="none")

for i, c in enumerate(cells):
    c["id"] = f"X{i + 1:03d}"
    c["generator"] = GENS[i % 4]
    c["style"] = rng.choice(STYLES)
(ROOT / "docs/eval/v3/heldout-v4-design.json").write_text(json.dumps({"note": __doc__, "seed": 20261011, "cells": cells},
                                                                     ensure_ascii=False, indent=1))
src = ['"""MOCK orders for held-out v4 (v3.2 round). EVERYTHING HERE IS MOCK.', "",
       "Generated by scripts/v3/heldout_v3_design.py BEFORE any v4 message was generated / labelled / run. Fresh ids TO-96xxx.\"\"\"", "",
       "ORDERS_V4_RAW = " + json.dumps(orders, indent=1, ensure_ascii=False).replace("null", "None").replace("true", "True").replace("false", "False"), ""]
(ROOT / "app/routing_data_v4.py").write_text("\n".join(src))
ca = Counter(c["designed_action"] for c in cells)
print("cells", len(cells), dict(ca), "non-supplier", len(cells) - ca[T])
print("safety", sum("safety" in c["tags"] for c in cells), "low-risk malf", sum(c["slice"]=="low_risk_malfunction" for c in cells))
print("slices", dict(Counter(c["slice"] for c in cells)))
print("langs", dict(Counter(c["lang"] for c in cells)), "gens", dict(Counter(c["generator"] for c in cells)), "orders", len(orders))
