"""Held-out v3 design grid (v3.1 round). Counterexample-heavy. Written AFTER the v3.1 fixes and BEFORE any v3 message
was generated, labelled or run. Fresh MOCK orders (TO-9xxxx) and customers.

Produces docs/eval/v3/heldout-v3-design.json and app/routing_data_v3.py (MOCK).
`designed_action` is the design intention (composition targets + a third label source); labels come from two LLM judges
(different families) + adjudication with labelling-guide-v3.1.md. Briefs describe the customer's situation only.
Normalisation traps: after generation, the order id in the text is rewritten with the recorded hyphen / width variant.
"""
import json
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
rng = random.Random(20261010)
LANGS = ["en", "zh-Hant", "es", "de", "ja"]
GENS = ["nvidia/nemotron-3-super-120b-a12b", "deepseek-ai/deepseek-v4.1-flash", "meta/muse-glimmer-30b",
        "google/gemma-4-31b-it"]
STYLES = ["short and to the point", "polite and a bit formal", "casual, with a typo or two", "annoyed but civil",
          "long-winded with some irrelevant detail and a sign-off", "very brief, like a phone message",
          "friendly and chatty", "mixes in one or two English words (if not writing in English)"]
FIRST = ["Akira", "Bea", "Chiara", "Diego", "Emma", "Fumiko", "Gonzalo", "Hanna", "Isamu", "Julia", "Kai", "Luis", "Mina",
         "Noah", "Oskar", "Paula", "Rin", "Sofia", "Taro", "Ulla", "Valeria", "Wen", "Yuki", "Zoe"]
orders, cells = [], []
_oid, _cust = [90000], [0]


def new_customer():
    _cust[0] += 1
    n = FIRST[_cust[0] % len(FIRST)]
    return f"{n.lower()}{_cust[0]:03d}@example.test", n


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

# ------------------------------------------------------------------ supplier-task positives (83)
for lg in langs(8):
    c, nm = new_customer(); s = rng.choice(range(39, 45)); d = rng.choice([4, 9, 14, 21])
    oid = new_order(c, d, [line("TRAIL-RUNNER-42", str(s))]); t = s + rng.choice([1, -1])
    cell("exch_shoe_size", lg, f"You are {nm}. You bought Trail Runner sneakers in EU size {s} {d} days ago; they are too "
         f"{'small' if t > s else 'big'}. Ask to exchange them for size {t}.", c, oid, T, slice_="normal_task")
for lg in langs(10):  # seller error, consistent with the record
    c, nm = new_customer(); s = rng.choice(range(39, 45)); d = rng.choice([3, 6, 11])
    oid = new_order(c, d, [line("TRAIL-RUNNER-42", str(s))]); got = s + rng.choice([1, -1, 2])
    cell("seller_wrong_size", lg, f"You are {nm}. You ordered Trail Runner sneakers in size {s}, but the shop sent size {got} "
         f"(state both sizes clearly). Ask for the size {s} you ordered.", c, oid, T, slice_="buyer_vs_seller", tags=["pair:seller"])
for lg in langs(6):
    c, nm = new_customer(); d = rng.choice([4, 8, 15]); v, o = rng.choice([("white", "black"), ("black", "white")])
    oid = new_order(c, d, [line("DESK-LAMP", v)])
    cell("seller_wrong_colour_lamp", lg, f"You are {nm}. You ordered the {v} LED desk lamp {d} days ago and the shop sent a {o} "
         f"one (state both colours). Ask for the {v} one you ordered.", c, oid, T, slice_="buyer_vs_seller", tags=["pair:seller"])
for lg in langs(5):
    c, nm = new_customer(); d = rng.choice([5, 10, 18]); oid = new_order(c, d, [line("CITY-JACKET", "M")])
    cell("exch_jacket_L", lg, f"You are {nm}. Your City rain jacket in size M (bought {d} days ago) is too tight. Ask to "
         "exchange it for size L.", c, oid, T, slice_="normal_task")
for lg in langs(8):
    c, nm = new_customer(); d = rng.choice([6, 9, 12])
    if rng.random() < .5:
        oid = new_order(c, d, [line("DESK-LAMP", "black", logistics="LOST")]); w = "The desk lamp never arrived."
    else:
        oid = new_order(c, d, [line("DESK-LAMP", "white", qty=2, logistics="DELIVERED_PARTIAL", delivered_qty=1)])
        w = "You ordered two white desk lamps but only one was in the parcel."
    cell("reship_lamp", lg, f"You are {nm}. {w} Ask them to send the missing lamp.", c, oid, T, slice_="normal_task")
for lg in langs(5):
    c, nm = new_customer(); d = rng.choice([7, 10, 13]); oid = new_order(c, d, [line("TRAIL-RUNNER-42", "42", logistics="LOST")])
    cell("reship_shoe", lg, f"You are {nm}. Your Trail Runner sneakers ordered {d} days ago never arrived; tracking hasn't "
         "moved for a week. Ask them to send them again.", c, oid, T, slice_="normal_task")
for lg in langs(10):
    c, nm = new_customer(); d = rng.choice([60, 95, 140, 200, 280, 330]); oid = new_order(c, d, [line("BREW-KETTLE", "standard")])
    cell("kettle_warranty", lg, f"You are {nm}. Your electric kettle, bought about {d // 30} months ago, {rng.choice(FK)}. "
         f"There is no smell, smoke or heat problem. Ask for {rng.choice(['a repair', 'a replacement kettle'])}.", c, oid, T,
         slice_="normal_task")
for lg in langs(9):
    c, nm = new_customer(); d = rng.choice([70, 150, 260, 400, 600]); oid = new_order(c, d, [line("DESK-LAMP", rng.choice(["white", "black"]))])
    cell("lamp_warranty", lg, f"You are {nm}. Your LED desk lamp, bought {d} days ago, {rng.choice(FL)}. Ask for "
         f"{rng.choice(['a repair', 'a replacement lamp'])}.", c, oid, T, slice_="normal_task")
for lg in langs(6):
    c, nm = new_customer(); d = rng.choice([45, 70, 100, 150]); oid = new_order(c, d, [line("TRAIL-RUNNER-42", str(rng.choice(range(39, 45))))])
    cell("shoe_warranty", lg, f"You are {nm}. Your Trail Runner sneakers, bought {d} days ago, "
         f"{rng.choice(['have a sole coming off', 'split at the seam', 'lost an eyelet and the upper tore'])}. Ask for a "
         "replacement pair.", c, oid, T, slice_="normal_task")
for lg in langs(5):
    c, nm = new_customer(); d = rng.choice([40, 120, 250]); oid = new_order(c, d, [line("BREW-KETTLE", "standard")])
    cell("part_kettle_lid", lg, f"You are {nm}. You lost the lid of your electric kettle when moving. Ask them to send a new "
         "lid, part number KL-170-LID.", c, oid, T, slice_="normal_task")
for lg in langs(4):
    c, nm = new_customer(); oid = new_order(c, rng.choice([30, 90, 200]), [line("DESK-LAMP", "white")])
    part, st = rng.choice([("DL-CLAMP-M", "you lost the desk clamp"), ("DL-LED-5W", "you want a spare 5 W LED module")])
    cell("part_lamp", lg, f"You are {nm}. For your LED desk lamp, {st}. Ask them to send part {part}.", c, oid, T, slice_="normal_task")
for lg in langs(3):
    c, nm = new_customer(); oid = new_order(c, 100, [line("DESK-LAMP", "white")])
    cell("part_unknown", lg, f"You are {nm}. You need part DL-ARM-2 for your LED desk lamp (a friend told you the number). "
         "Ask the shop to get one and send it.", c, oid, T, slice_="normal_task")
for lg in langs(4):
    c, nm = new_customer(); oid = new_order(c, 8, [line("DESK-LAMP", "black", logistics="LOST")])
    cell("linked_reship_lamp", lg, f"You are {nm}. Your desk lamp never arrived. Ask them to send it again.", c, oid, T,
         cite="none", linked=oid, slice_="normal_task")

# ------------------------------------------------------------------ buyer error (fix 2)
for lg in langs(12):
    c, nm = new_customer(); s = rng.choice(range(39, 45)); d = rng.choice([3, 6, 11])
    oid = new_order(c, d, [line("TRAIL-RUNNER-42", str(s))]); w = s + 1
    cell("buyer_wrong_size", lg, f"You are {nm}. You ordered Trail Runner sneakers in size {s} BY MISTAKE (your own error; you "
         f"wear {w}); the shop sent exactly what you ordered. Say it was your mistake and ask to exchange for size {w}.", c, oid,
         D, slice_="buyer_vs_seller", tags=["pair:buyer"])
for lg in langs(8):
    c, nm = new_customer(); v, o = rng.choice([("white", "black"), ("black", "white")])
    oid = new_order(c, rng.choice([4, 9]), [line("DESK-LAMP", v)])
    why = rng.choice(["you clicked the wrong colour by mistake", "you changed your mind about the colour"])
    cell("buyer_wrong_colour", lg, f"You are {nm}. You ordered the {v} LED desk lamp and received it, but {why}. Ask to "
         f"exchange it for {o}.", c, oid, D, slice_="buyer_vs_seller", tags=["pair:buyer"])
# ------------------------------------------------------------------ order-record conflicts (fix 1)
for lg in langs(10):
    c, nm = new_customer(); v, o = rng.choice([("white", "black"), ("black", "white")])
    oid = new_order(c, rng.choice([4, 9, 12]), [line("DESK-LAMP", v)])  # record: v; customer claims ordered o, received v
    cell("conflict_lamp_colour", lg, f"You are {nm}. You believe you ordered the {o} LED desk lamp, and you received a {v} one. "
         f"Say the shop sent the wrong colour and ask for the {o} one.", c, oid, H, slice_="order_conflict")
for lg in langs(8):
    c, nm = new_customer(); s = rng.choice(range(39, 45)); oid = new_order(c, rng.choice([3, 7]), [line("TRAIL-RUNNER-42", str(s))])
    cell("conflict_shoe_size", lg, f"You are {nm}. You believe you ordered Trail Runner sneakers in size {s - 1}, and the box "
         f"contained size {s}. Say the shop sent the wrong size and ask for size {s - 1}.", c, oid, H, slice_="order_conflict")
for lg in langs(6):
    c, nm = new_customer(); oid = new_order(c, 20, [line("BACKPACK-30L", "navy")])
    prod = rng.choice(["electric kettle", "Trail Runner sneakers", "City rain jacket"])
    cell("conflict_product_not_in_order", lg, f"You are {nm}. Your {prod} from this order is broken (describe it). Ask for a "
         "replacement.", c, oid, H, slice_="order_conflict")
for lg in langs(8):
    c, nm = new_customer(); oid = new_order(c, 14, [line("BREW-KETTLE", "standard"), line("SALE-SOCKS", "M")])
    a, b = rng.sample(["pillowcase", "cutlery set", "coffee mug", "bath towel", "picture frame", "phone case", "scarf"], 2)
    cell("multi_item_not_in_order", lg, f"You are {nm}. From this order, your {a} arrived damaged and your {b} is faulty. Ask "
         f"for a replacement {a} and a refund for the {b}.", c, oid, H, slice_="order_conflict", tags=["multi_item"])
for lg in langs(8):
    c, nm = new_customer(); oid = new_order(c, 200, [line("BREW-KETTLE", "standard"), line("DESK-LAMP", "white")])
    cell("multi_item_in_order", lg, f"You are {nm}. From this order (bought 200 days ago), the electric kettle stopped heating "
         "and the desk lamp flickers. Ask for the kettle to be repaired and a refund for the lamp.", c, oid, C,
         slice_="multi_item", tags=["multi_item"])
# ------------------------------------------------------------------ safety (fix 3)
for lg in langs(7):
    c, nm = new_customer(); d = rng.choice([60, 150, 250]); oid = new_order(c, d, [line("BREW-KETTLE", "standard")])
    cell("safety_burnt_plastic", lg, f"You are {nm}. Your electric kettle (bought {d} days ago) gives off a smell of burnt or "
         f"melting plastic when it boils. Ask for {rng.choice(['a repair', 'a replacement', 'a refund'])}.", c, oid, H, slice_="safety")
for lg in langs(7):
    c, nm = new_customer(); d = rng.choice([80, 200]); oid = new_order(c, d, [line("BREW-KETTLE", "standard")])
    cell("safety_power_base", lg, f"You are {nm}. The power base of your electric kettle (bought {d} days ago) has a fault: "
         f"{rng.choice(['the kettle no longer powers on when placed on it', 'the base contacts look loose and it cuts out'])}. "
         f"{rng.choice(['Ask them to send a new power base, part KL-170-BASE.', 'Ask for a replacement.'])}", c, oid, H, slice_="safety")
for lg in langs(8):
    c, nm = new_customer(); sku = rng.choice(["BREW-KETTLE", "DESK-LAMP"]); d = rng.choice([90, 200])
    oid = new_order(c, d, [line(sku, "standard" if sku == "BREW-KETTLE" else "black")])
    extra = " Write the word 'fuse' in English inside your sentence, e.g. 「fuseが飛んで」." if lg == "ja" else ""
    cell("safety_fuse", lg, f"You are {nm}. Every time you switch on your {P[sku]} (bought {d} days ago), the fuse blows / the "
         f"breaker trips.{extra} Ask for a replacement.", c, oid, H, slice_="safety")
for lg in langs(7):
    c, nm = new_customer(); oid = new_order(c, rng.choice([10, 20, 60]), [line("CAMP-STOVE", "standard")])
    cell("safety_gas_refund", lg, f"You are {nm}. The gas valve (or control knob) on your camping gas stove is faulty: it "
         f"{rng.choice(['sticks and does not close fully', 'is loose and wobbly'])}. You don't want anything else: ask for a refund.",
         c, oid, H, slice_="safety", tags=["refund+safety"])
for lg in langs(4):
    c, nm = new_customer(); oid = new_order(c, 100, [line("CAMP-STOVE", "standard")])
    cell("safety_gas_repair", lg, f"You are {nm}. The ignition of your camping gas stove clicks but won't light. Ask for a repair.",
         c, oid, H, slice_="safety")
for lg in langs(4):
    c, nm = new_customer(); oid = new_order(c, 300, [line("DESK-LAMP", "white")])
    cell("safety_lamp_sparks", lg, f"You are {nm}. Your LED desk lamp sparked and there was a little smoke from the switch. "
         "Ask for a replacement.", c, oid, H, slice_="safety")
for lg in langs(3):
    c, nm = new_customer(); oid = new_order(c, 120, [line("DESK-LAMP", "black")])
    cell("safety_water_base", lg, f"You are {nm}. Water got into the base of your LED desk lamp and now it buzzes. Ask for a "
         "repair.", c, oid, H, slice_="safety")
# ------------------------------------------------------------------ intent revision (fix 4)
for lg in langs(10):
    c, nm = new_customer(); oid = new_order(c, rng.choice([12, 20]), [line("BREW-KETTLE", "standard")])
    first = rng.choice(["a replacement lid (part KL-170-LID)", "a repair", "a replacement kettle"])
    cell("revision_to_refund", lg, f"You are {nm}. Your electric kettle (bought recently) stopped heating. In the message you first "
         f"ask for {first}, then clearly change your mind in the same message and say you just want a refund instead.", c, oid, D,
         slice_="intent_revision")
for lg in langs(6):
    c, nm = new_customer(); oid = new_order(c, 200, [line("DESK-LAMP", "white")])
    cell("revision_ambiguous", lg, f"You are {nm}. Your LED desk lamp (200 days old) flickers. You start asking for a repair, then "
         "wonder about a refund instead, and end the message still undecided between the two.", c, oid, C, slice_="intent_revision")
# ------------------------------------------------------------------ complaint only (fix 4)
for lg in langs(16):
    c, nm = new_customer(); sku = rng.choice(["BREW-KETTLE", "DESK-LAMP", "TRAIL-RUNNER-42"]); d = rng.choice([60, 150])
    oid = new_order(c, d, [line(sku, {"BREW-KETTLE": "standard", "DESK-LAMP": "white", "TRAIL-RUNNER-42": "41"}[sku])])
    f = {"BREW-KETTLE": "stopped heating", "DESK-LAMP": "keeps flickering", "TRAIL-RUNNER-42": "the sole is coming off"}[sku]
    cell("complaint_only", lg, f"You are {nm}. Your {P[sku]} (bought {d} days ago) {f}. You are just venting your "
         "disappointment: do NOT ask for anything (no repair, no replacement, no refund, no question).", c, oid, C,
         slice_="complaint_only")
# ------------------------------------------------------------------ normalisation traps (fix 3)
VARIANTS = ["\u2011", "\u2010", "\u2013", "\u2212", "fullwidth"]
for i, lg in enumerate(langs(6)):
    c, nm = new_customer(); oid = new_order(c, 15, [line("BREW-KETTLE", "standard")]); other = f"TO-{_oid[0] + 500}"
    cell("norm_hedged_bad_refund", lg, f"You are {nm}. Your kettle arrived with a dent. Ask for a refund.", c, oid, C,
         cite="hedged_bad", other=other, slice_="normalisation", variant=VARIANTS[i % 5])
for i, lg in enumerate(langs(6)):
    c, nm = new_customer(); oid = new_order(c, 15, [line("BREW-KETTLE", "standard")])
    cell("norm_valid_refund", lg, f"You are {nm}. Your kettle arrived with a dented body and you want a refund.", c, oid, D,
         slice_="normalisation", variant=VARIANTS[(i + 2) % 5])
for i, lg in enumerate(langs(4)):
    c, nm = new_customer(); oid = new_order(c, 150, [line("DESK-LAMP", "black")])
    cell("norm_valid_task", lg, f"You are {nm}. Your LED desk lamp (150 days old) won't turn on. Ask for a repair.", c, oid, T,
         slice_="normalisation", variant=VARIANTS[(i + 1) % 5])
# ------------------------------------------------------------------ other negatives
for lg in langs(12):
    c, nm = new_customer(); sku = rng.choice(["TRAIL-RUNNER-42", "CITY-JACKET", "BACKPACK-30L"])
    oid = new_order(c, 12, [line(sku, {"TRAIL-RUNNER-42": "42", "CITY-JACKET": "M", "BACKPACK-30L": "black"}[sku])])
    cell("refund_only", lg, f"You are {nm}. Your {P[sku]} has a {rng.choice(['torn seam', 'broken zip', 'stain that will not wash out'])}. "
         "Ask for a refund (nothing else).", c, oid, D)
for lg in langs(10):
    c, nm = new_customer(); oid = new_order(c, 150, [line("BREW-KETTLE", "standard")]) if rng.random() < .5 else None
    cell("availability_q", lg, f"You are {nm}. Ask only whether the shop sells the kettle limescale filter KL-170-FLT / lid "
         "separately and whether it is in stock. Do not ask them to send anything.", c, oid, H, cite="exact" if oid else "none")
for lg in langs(6):
    c, nm = new_customer()
    cell("policy_q", lg, f"You are {nm}. Ask how long the return window is and who pays return shipping. No order problem.", c,
         None, H, cite="none")
for lg in langs(6):
    c, nm = new_customer(); oid = new_order(c, 150, [line("DESK-LAMP", "white")])
    bad = rng.choice([f"WO-{oid[3:]}", f"T0-{oid[3:]}", f"#A{oid[3:]}"])
    cell("malformed_ref", lg, f"You are {nm}. Your LED desk lamp (150 days old) won't turn on. Ask for a repair.", c, oid, C,
         cite="malformed", other=bad)
for lg in langs(6):
    c, nm = new_customer(); new_order(c, 150, [line("DESK-LAMP", "white")])
    cell("no_order_ref", lg, f"You are {nm}. Your LED desk lamp (about 5 months old) won't turn on. Ask for a repair.", c, None, C,
         cite="none")
for lg in langs(6):
    c, nm = new_customer(); oid = new_order(c, 200, [line("BREW-KETTLE", "standard")])
    cell("undecided", lg, f"You are {nm}. Your kettle (200 days old) stopped heating. Say you can't decide between a repair and "
         "a refund and ask which they'd suggest.", c, oid, C)
for lg in langs(6):
    c, nm = new_customer(); oid = new_order(c, rng.choice([5, 12, 20]), [line("BREW-KETTLE", "standard")])
    cell("kettle_within_30", lg, f"You are {nm}. Your kettle, bought a couple of weeks ago, {rng.choice(FK)}. Ask for a replacement.",
         c, oid, D)
for lg in langs(5):
    c, nm = new_customer(); oid = new_order(c, 8, [line("CITY-JACKET", "S")])
    cell("jacket_in_stock", lg, f"You are {nm}. Your City rain jacket in size S is too small. Ask to exchange it for M.", c, oid, D)
for lg in langs(4):
    c, nm = new_customer(); oid = new_order(c, 60, [line("TRAIL-RUNNER-42", "41")])
    cell("size_old", lg, f"You are {nm}. You bought Trail Runner sneakers in 41 two months ago and only now tried them: too small. "
         "Ask to exchange for 42.", c, oid, D)
for lg in langs(4):
    c, nm = new_customer(); oid = new_order(c, 6, [line("SALE-SOCKS", "M")])
    cell("socks_final_sale", lg, f"You are {nm}. Your merino socks (bought on final sale) in M are too big. Ask to exchange for S.",
         c, oid, D)
for lg in langs(4):
    c, nm = new_customer(); oid = new_order(c, 3, [line("TRAIL-RUNNER-42", "44", logistics="IN_TRANSIT", tracking="MP99887766")])
    cell("in_transit", lg, f"You are {nm}. You ordered sneakers 3 days ago and they haven't arrived. Ask them to send them again.",
         c, oid, D)
for lg in langs(7):
    c, nm = new_customer(); oid = new_order(c, 9, [line("DESK-LAMP", "white")])
    cell("delivered_claims_missing", lg, f"You are {nm}. Your desk lamp never arrived. Ask them to send it again.", c, oid, H)
for lg in langs(5):
    c, nm = new_customer(); oid = new_order(c, 200, [line("BREW-KETTLE", "standard")])
    cell("part_in_stock", lg, f"You are {nm}. Your kettle's limescale filter is used up. Ask them to send a new one, part "
         "KL-170-FLT.", c, oid, D)
for lg in langs(4):
    c, nm = new_customer(); oid = new_order(c, 100, [line("BACKPACK-30L", "black")])
    cell("backpack_warranty", lg, f"You are {nm}. The zip of your Daypack 30L (100 days old) broke. Ask for a repair.", c, oid, D)
for lg in langs(4):
    c, nm = new_customer(); c2, _ = new_customer(); oid = new_order(c2, 100, [line("DESK-LAMP", "white")])
    cell("other_customer", lg, f"You are {nm}. Your LED desk lamp flickers. Ask for a repair.", c, oid, H)
for lg in langs(4):
    c, nm = new_customer(); oid = new_order(c, 500, [line("BREW-KETTLE", "standard")])
    cell("out_of_warranty", lg, f"You are {nm}. Your kettle bought 500 days ago stopped heating. Ask for a repair.", c, oid, H)
for lg in langs(3):
    c, nm = new_customer()
    cell("thanks_other", lg, f"You are {nm}. Write a short thank-you note: the delivery was fast and you love the lamp.", c, None,
         H, cite="none")

for i, c in enumerate(cells):
    c["id"] = f"W{i + 1:03d}"
    c["generator"] = GENS[i % 4]
    c["style"] = rng.choice(STYLES)
(ROOT / "docs/eval/v3/heldout-v3-design.json").write_text(json.dumps({"note": __doc__, "seed": 20261010, "cells": cells},
                                                                     ensure_ascii=False, indent=1))
src = ['"""MOCK orders for held-out v3 (v3.1 round). EVERYTHING HERE IS MOCK.', "",
       "Generated by scripts/v3/heldout_v3_design.py BEFORE any v3 message was generated / labelled / run. Fresh ids TO-9xxxx.\"\"\"", "",
       "ORDERS_V3_RAW = " + json.dumps(orders, indent=1, ensure_ascii=False).replace("null", "None").replace("true", "True").replace("false", "False"), ""]
(ROOT / "app/routing_data_v3.py").write_text("\n".join(src))
ca = Counter(c["designed_action"] for c in cells)
print("cells", len(cells), dict(ca), "non-supplier", len(cells) - ca[T])
print("slices", dict(Counter(c["slice"] for c in cells)))
print("langs", dict(Counter(c["lang"] for c in cells)), "gens", dict(Counter(c["generator"] for c in cells)), "orders", len(orders))
