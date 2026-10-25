"""Product class from Channel3-style category paths: plural leaves, hyphens, spacing, case.

Regression for a live finding (2026-10-25): a Jetboil Flash (category leaf "Camping Stoves") with a plain fault message
("It stopped working ...") was NOT held for safety review, because the class rules were written in the singular
("camp stove") and the Channel3 category leaves are plural. Same for "Hair Dryers", "Space Heaters", "Toasters" ...
The gate stays escalate-only: nothing here makes any product LESS gated than before.
"""
from __future__ import annotations

import re

import pytest

from app import catalog as catalog_mod
from app import safety as safety_mod
from app.safety import (GATED_CLASSES, NON_HAZARD_LEAVES, _CLASS_RULES, _singular, assess, class_text, exempt_leaf, normalize,
                        product_class)

NAME = "Acme Z100"  # a title with no hazard word, so only the category can decide
PLAIN_FAULT = "It stopped working after two days, please refund me."

# Real category paths returned by Channel3 find_product on the live demo (2026-10-25), and what each must classify as.
REAL_PATHS = [
    ("Apparel & Accessories > Clothing > Shirts & Tops > T-Shirts", "NONE"),
    ("Arts & Entertainment > Hobbies & Creative Arts > Musical Instruments > Percussion > Hand Percussion > Musical Triangles", "NONE"),
    ("Arts & Entertainment > Hobbies & Creative Arts > Musical Instruments > Percussion > Practice Pads", "NONE"),
    ("Arts & Entertainment > Party & Celebration > Special Effects > Special Effects Lighting > LED Lights", "MAINS_ELECTRIC"),
    ("Electronics > Electronics Accessories > Cables > System & Power Cables > AC Power Cords", "MAINS_ELECTRIC"),
    ("Electronics > Electronics Accessories > Power > Batteries > General Purpose Batteries", "BATTERY_THERMAL"),
    ("Electronics > Electronics Accessories > Power > Power Adapters & Chargers > Power Banks", "BATTERY_THERMAL"),
    ("Electronics > Electronics Accessories > Power > Power Strips & Surge Suppressors", "MAINS_ELECTRIC"),
    ("Electronics > Electronics Accessories > Power > Surge Protection Devices", "MAINS_ELECTRIC"),
    ("Electronics > Print, Copy, Scan & Fax > Printer, Copier & Fax Machine Accessories > Printer Cables & Power Cords", "MAINS_ELECTRIC"),
    ("Hardware > Tool Accessories > Power Tool Batteries", "BATTERY_THERMAL"),
    ("Health & Beauty > Personal Care > Hair Care > Hair Styling Tools > Combs & Brushes > Hot Air Brushes", "MAINS_HEATING"),
    ("Health & Beauty > Personal Care > Hair Care > Hair Styling Tools > Hair Dryers", "MAINS_HEATING"),
    ("Health & Beauty > Personal Care > Hair Care > Hair Styling Tools > Hair Straighteners", "MAINS_HEATING"),
    ("Home & Garden > Decor > Clocks > Wall Clocks", "NONE"),
    ("Home & Garden > Decor > Home Fragrances > Candles", "NONE"),
    ("Home & Garden > Household Appliances > Climate Control Appliances > Air Purifiers", "MAINS_ELECTRIC"),
    ("Home & Garden > Household Appliances > Climate Control Appliances > Fans > Tower Fans", "MAINS_ELECTRIC"),
    ("Home & Garden > Household Appliances > Climate Control Appliances > Humidifiers", "MAINS_ELECTRIC"),
    ("Home & Garden > Household Appliances > Climate Control Appliances > Space Heaters", "MAINS_HEATING"),
    ("Home & Garden > Household Appliances > Laundry Appliances > Irons & Ironing Systems > Irons", "MAINS_HEATING"),
    ("Home & Garden > Kitchen & Dining > Kitchen Appliances > Cooktops", "MAINS_ELECTRIC"),
    ("Home & Garden > Kitchen & Dining > Kitchen Appliances > Hot Drink Makers > Water Boilers & Warmers", "MAINS_HEATING"),
    ("Home & Garden > Kitchen & Dining > Kitchen Appliances > Portable Cooking Stoves", "GAS"),
    ("Home & Garden > Kitchen & Dining > Kitchen Appliances > Portable Cooking Stoves > Camping Tabletop Stoves", "GAS"),
    ("Home & Garden > Kitchen & Dining > Kitchen Appliances > Toasters & Grills > Toasters", "MAINS_HEATING"),
    ("Home & Garden > Kitchen & Dining > Kitchen Appliances > Water Filters > Countertop Water Filters", "MAINS_ELECTRIC"),
    ("Home & Garden > Linens & Bedding > Bedding > Blankets > Electric Blankets", "MAINS_HEATING"),
    ("Home & Garden > Wood Stoves", "GAS"),
    ("Sporting Goods > Outdoor Recreation > Camping & Hiking > Camping Stoves", "GAS"),
]


@pytest.mark.parametrize("path,expected", REAL_PATHS)
def test_real_channel3_category_paths(path, expected):
    assert product_class({"name": NAME, "category": path}) == expected


@pytest.mark.parametrize("path,expected", REAL_PATHS)
def test_a_plain_fault_on_each_real_path_is_held_unless_it_is_not_a_hazard_class(path, expected):
    a = assess(PLAIN_FAULT, {"name": NAME, "category": path})
    if expected == "NONE":
        assert not a.flagged
    else:
        assert a.flagged and a.trigger == "gated_product_fault" and a.product_class in GATED_CLASSES


def test_a_truncated_real_path_keeps_its_leaf():
    """The live catalogue cuts a category text to its LAST 120 characters (seen: "rtainment > Hobbies & ..." on a long path)."""
    assert product_class({"name": NAME, "category": "rtainment > Hobbies & Creative Arts > Musical Instruments > Percussion > "
                                                    "Hand Percussion > Musical Shakers > Egg Shakers"}) == "NONE"


def test_the_jetboil_flash_case_is_held_and_a_tshirt_with_the_same_words_is_not():
    jetboil = {"name": "Jetboil Flash 1.0L Fast Boil System",
               "category": "Sporting Goods > Outdoor Recreation > Camping & Hiking > Camping Stoves"}
    assert assess(PLAIN_FAULT, jetboil).flagged
    tee = {"name": "Cotton T-shirt", "category": "Apparel & Accessories > Clothing > Shirts & Tops > T-Shirts"}
    assert not assess(PLAIN_FAULT, tee).flagged


# Leaf categories (and names) the issue listed, in plural / singular / hyphen / spacing / case variants.
@pytest.mark.parametrize("category,expected", [
    ("Gas Stoves", "GAS"), ("Gas Stove", "GAS"), ("Portable Stoves", "GAS"), ("Camp Stoves", "GAS"), ("Camp-Stoves", "GAS"),
    ("camping  stoves", "GAS"), ("CAMPING STOVES", "GAS"), ("Backpacking Stoves", "GAS"), ("Propane Tanks", "GAS"),
    ("Butane Canisters", "GAS"), ("Burners", "GAS"), ("Lighters", "GAS"),
    ("Heaters", "MAINS_HEATING"), ("Space Heaters", "MAINS_HEATING"), ("Kettles", "MAINS_HEATING"),
    ("Tea Kettles", "MAINS_HEATING"), ("Hair Dryers", "MAINS_HEATING"), ("Hair-Dryers", "MAINS_HEATING"),
    ("Hairdryers", "MAINS_HEATING"), ("Hair Straighteners", "MAINS_HEATING"), ("Flat Irons", "MAINS_HEATING"),
    ("Curling Irons", "MAINS_HEATING"), ("Irons", "MAINS_HEATING"), ("Steam Irons", "MAINS_HEATING"),
    ("Garment Steamers", "MAINS_HEATING"), ("Toasters", "MAINS_HEATING"), ("Toaster Ovens", "MAINS_HEATING"),
    ("Air Fryers", "MAINS_HEATING"), ("Air-Fryers", "MAINS_HEATING"), ("Slow Cookers", "MAINS_HEATING"),
    ("Rice Cookers", "MAINS_HEATING"), ("Grills", "MAINS_HEATING"), ("Hobs", "MAINS_HEATING"),
    ("Hot Plates", "MAINS_HEATING"), ("Radiators", "MAINS_HEATING"), ("Electric Blankets", "MAINS_HEATING"),
    ("Power Banks", "BATTERY_THERMAL"), ("Power-Banks", "BATTERY_THERMAL"), ("Batteries", "BATTERY_THERMAL"),
    ("Rechargeable Batteries", "BATTERY_THERMAL"), ("E-Bikes", "BATTERY_THERMAL"), ("E Bikes", "BATTERY_THERMAL"),
    ("Electric Scooters", "BATTERY_THERMAL"), ("Li-ion Packs", "BATTERY_THERMAL"), ("Hoverboards", "BATTERY_THERMAL"),
    ("Hand Warmers", "BATTERY_THERMAL"), ("Vapes", "BATTERY_THERMAL"),
    ("Extension Cords", "MAINS_ELECTRIC"), ("Surge Protectors", "MAINS_ELECTRIC"), ("Power Strips", "MAINS_ELECTRIC"),
    ("Chargers", "MAINS_ELECTRIC"), ("Adapters", "MAINS_ELECTRIC"), ("Lamps", "MAINS_ELECTRIC"),
    ("String Lights", "MAINS_ELECTRIC"), ("Fans", "MAINS_ELECTRIC"), ("Blenders", "MAINS_ELECTRIC"),
    ("Vacuums", "MAINS_ELECTRIC"), ("Speakers", "MAINS_ELECTRIC"), ("Televisions", "MAINS_ELECTRIC"),
    ("Microwaves", "MAINS_ELECTRIC"), ("Dryers", "MAINS_ELECTRIC"), ("Routers", "MAINS_ELECTRIC"),
    ("Cables", "MAINS_ELECTRIC"), ("Fridges", "MAINS_ELECTRIC"),
])
def test_category_variants_classify_as_gated(category, expected):
    assert product_class({"name": NAME, "category": category}) == expected


def test_the_old_singular_behaviour_is_kept():
    """Every singular that matched before still matches (escalate-only: nothing becomes less gated)."""
    for cat, expected in [("kettle", "MAINS_HEATING"), ("camping stove", "GAS"), ("Camping Stove", "GAS"),
                          ("hair dryer", "MAINS_HEATING"), ("power bank", "BATTERY_THERMAL"),
                          ("e-bike", "BATTERY_THERMAL"), ("li-ion", "BATTERY_THERMAL"), ("air fryer", "MAINS_HEATING"),
                          ("lamp", "MAINS_ELECTRIC"), ("appliance", "MAINS_ELECTRIC")]:
        assert product_class({"name": NAME, "category": cat}) == expected
    assert product_class({"name": "Camping gas stove", "category": "outdoor"}) == "GAS"
    assert product_class({"name": "Electric kettle", "category": "kitchen"}) == "MAINS_HEATING"
    # the exact-slug fallback still works on its own
    for slug, expected in [("outdoor-gas", "GAS"), ("batteries", "BATTERY_THERMAL"), ("heating", "MAINS_HEATING")]:
        assert product_class({"name": NAME, "category": slug}) == expected


def test_every_singular_rule_word_is_also_found_in_its_plural_and_hyphen_forms():
    """Property: for each simple word the rules know, singular, plural and upper-case give the same class."""
    words = ["kettle", "heater", "toaster", "iron", "oven", "fryer", "cooker", "grill", "radiator", "boiler",
             "battery", "scooter", "vape", "stove", "burner", "lighter", "regulator", "lamp", "light", "charger",
             "adapter", "socket", "plug", "blender", "vacuum", "fan", "mixer", "cable", "speaker", "monitor",
             "router", "dryer", "washer", "microwave", "freezer", "appliance"]
    for w in words:
        base = product_class({"name": NAME, "category": f"Things > {w}"})
        assert base in GATED_CLASSES, w
        for variant in (f"Things > {w}s", f"THINGS > {w.upper()}", f"things>{w}  "):
            assert product_class({"name": NAME, "category": variant}) in GATED_CLASSES, variant
    assert product_class({"name": NAME, "category": "Things > batteries"}) == "BATTERY_THERMAL"


# Negatives: nothing here may be gated by a category or name alone.
@pytest.mark.parametrize("name,category", [
    (NAME, "Apparel & Accessories > Clothing > Shirts & Tops > T-Shirts"), (NAME, "T-Shirts"), (NAME, "Sneakers"),
    (NAME, "Hoodies"), (NAME, "Jeans"), (NAME, "Backpacks"), (NAME, "Tents"), (NAME, "Sleeping Bags"), (NAME, "Mugs"),
    (NAME, "Wall Art"), (NAME, "Toys"), (NAME, "Cookware & Bakeware"), (NAME, "Kitchen Knives"),
    (NAME, "Sporting Goods > Exercise & Fitness > Kettlebells"),   # kettlebell is a weight, not a kettle
    (NAME, "Arts & Entertainment > Hobbies & Creative Arts"),       # "hobbies" -> "hobby", not "hob"
    ("Heather Knit Sweater", "Sweaters"), ("Heathers (DVD)", "Movies"),  # "heather" is not "heater"
    ("Ironwood Desk", "Desks"), ("Stovetop Espresso Pot", "Coffee Pots"), ("Stovepipe Hat", "Hats"),
    ("Glass Vase", "Vases"), ("Gasket Set", "Gaskets"), ("Lightweight Jacket", "Jackets"), ("Plugin Hybrid Book", "Books"),
    ("Planters Peanuts", "Snacks"), ("Fanatics Jersey", "Jerseys"), ("Hobbit Poster", "Posters"),
])
def test_unrelated_words_and_apparel_are_not_gated(name, category):
    assert product_class({"name": name, "category": category}) == "NONE"
    assert not assess(PLAIN_FAULT, {"name": name, "category": category}).flagged


def test_candles_stay_ungated_by_decision():
    """Decision (see docs/safety-gate.md): candles are NOT a gated class. A broken/cracked-jar fault alone is an ordinary
    return; any fire / smoke / burn wording is caught by rule 1 for every product regardless of class."""
    candle = {"name": "Soy Candle", "category": "Home & Garden > Decor > Home Fragrances > Candles"}
    assert product_class(candle) == "NONE"
    assert not assess("The jar arrived cracked.", candle).flagged
    assert assess("The candle caught fire and the jar cracked.", candle).trigger == "harm_language"


def test_singular_helper_is_conservative():
    assert [_singular(w) for w in ("heaters", "stoves", "batteries", "torches", "boxes", "glasses", "fans")] == [
        "heater", "stove", "battery", "torch", "box", "glass", "fan"]
    for w in ("gas", "glass", "bus", "iris", "tv", "iron", "a", "", "plus", "ss"):  # short / -ss / -us / -is words
        assert _singular(w) == w


def test_class_text_normalises_punctuation_case_accents_and_plurals():
    assert class_text("Acme", "Sporting Goods > Camping & Hiking > Camp-Stoves") == "acme sporting good camping hiking camp stove"
    assert class_text(None, "") == ""
    assert class_text("ＨＥＡＴＥＲＳ") == "heater"  # NFKC full-width


_OLD_RULES = [  # the rules exactly as they were before this change (singular words, matched on normalize(name + category))
    ("GAS", re.compile(r"\b(gas|propane|butane|lpg|burner|camp(?:ing)? stove|gas stove|lighter|regulator)\b")),
    ("MAINS_HEATING", re.compile(r"\b(kettle|heater|heating|toaster|iron|hair ?dryer|oven|fryer|air ?fryer|cooker|grill|hob|"
                                 r"electric blanket|heated|hot plate|radiator|boiler|water heater|space heater)\b")),
    ("BATTERY_THERMAL", re.compile(r"\b(battery|power ?bank|e-?bike|e-?scooter|scooter|vape|lithium|li-?ion|rechargeable|"
                                   r"hand warmer|heated (?:jacket|gloves|insoles|vest)|hoverboard)\b")),
    ("MAINS_ELECTRIC", re.compile(r"\b(lamp|light|charger|adapter|adaptor|extension|power strip|socket|plug|appliance|"
                                  r"blender|vacuum|fan|mixer|electric|electronic\w*|mains|cable|speaker|monitor|"
                                  r"tv|television|router|dryer|washer|microwave|fridge|freezer)\b")),
]


def _old_gated(name: str, category: str) -> bool:
    text = normalize(f"{name} {normalize(category)}")
    return any(rx.search(text) for _, rx in _OLD_RULES)


def test_escalate_only_nothing_that_was_gated_before_is_ungated_now():
    samples = [("Electric kettle 1.7 L", "x"), ("LED desk lamp", "lighting"), ("Camping gas stove", "outdoor"),
               ("20000 mAh power bank", "electronics"), ("Electric heated blanket", "home"), ("Phone charger", "x"),
               ("Hair dryer", "x"), ("Camp stove", "x"), ("Propane regulator", "x"), ("x", "Home & Garden > Lighting > Lamps"),
               ("x", "Electronics > Electronics Accessories > Power > Batteries"), ("x", "Hair Dryer"), ("x", "E-Bike"),
               ("x", "Li-ion pack"), ("x", "camping stove"), ("x", "kitchen appliance"), ("x", "Heating"), ("Wi-Fi Router", "x"),
               ("x", "Electronics"), ("x", "Appliance"), ("Space heater", "x"), ("Iron", "x"), ("Lighter", "x")]
    for name, cat in samples:
        if _old_gated(name, cat):
            assert product_class({"name": name, "category": cat}) in GATED_CLASSES, (name, cat)
    assert [c for c, _ in _CLASS_RULES] == ["GAS", "MAINS_HEATING", "BATTERY_THERMAL", "MAINS_ELECTRIC"]


def test_safety_class_override_and_unknown_product_unchanged():
    assert product_class({"name": NAME, "category": "T-Shirts", "safety_class": "GAS"}) == "GAS"
    assert product_class({"name": NAME, "category": "T-Shirts", "safety_class": "BOGUS"}) == "NONE"
    assert product_class(None) == "NONE" and product_class({}) == "NONE"


def test_channel3_object_to_gate_end_to_end():
    """The path the live demo uses: Channel3 product JSON -> catalog.normalize -> {name, category} -> the gate."""
    raw = {"id": "S2QsLVh", "title": "Jetboil Flash 1.0L Fast Boil System",
           "offers": [{"price": {"price": 144.95, "currency": "USD"}, "availability": "InStock"}],
           "category": {"slug": "camping-stoves", "title": "Camping Stoves",
                        "path": [{"slug": "sporting-goods", "title": "Sporting Goods"},
                                 {"slug": "outdoor-recreation", "title": "Outdoor Recreation"},
                                 {"slug": "camping-hiking", "title": "Camping & Hiking"},
                                 {"slug": "camping-stoves", "title": "Camping Stoves"}]}}
    p = catalog_mod.normalize(raw, "USD")
    assert p is not None
    product = {"name": p.title, "category": p.category}
    assert product_class(product) == "GAS"
    a = assess(PLAIN_FAULT, product)
    assert a.flagged and a.trigger == "gated_product_fault" and a.product_class == "GAS"
    # a truncated category (the catalogue keeps the LAST 120 chars) still has its leaf
    assert product_class({"name": NAME, "category": ("x > " * 40 + "Hair Dryers")[-120:]}) == "MAINS_HEATING"


# ------------------------------------------------------------------------------------------ non-hazard leaf allowlist
# Entries whose hazard word lives higher up the path need their real ancestors for the "entry is needed" check.
FULL_PATH = {
    "Coffee Makers & Espresso Machines > French Presses":
        "Home & Garden > Kitchen & Dining > Kitchen Appliances > Coffee Makers & Espresso Machines > French Presses",
    "Conduit & Housings > Heat-Shrink Tubing":
        "Hardware > Power & Electrical Supplies > Conduit & Housings > Heat-Shrink Tubing",
}


def _path(entry: str) -> str:
    return FULL_PATH.get(entry, "Root > Branch > " + entry)


@pytest.mark.parametrize("entry", NON_HAZARD_LEAVES)
def test_every_allowlisted_leaf_is_ungated_and_the_entry_is_needed(entry, monkeypatch):
    path = _path(entry)
    assert product_class({"name": NAME, "category": path}) == "NONE", entry
    assert not assess(PLAIN_FAULT, {"name": NAME, "category": path}).flagged
    # not a dead entry: without the allowlist the same path IS gated (so each exception removes a real over-trigger)
    monkeypatch.setattr(safety_mod, "_EXEMPT", {})
    assert product_class({"name": NAME, "category": path}) in GATED_CLASSES, entry


def test_allowlist_is_well_formed():
    assert len(set(NON_HAZARD_LEAVES)) == len(NON_HAZARD_LEAVES)
    assert all(e.count(">") == 1 for e in NON_HAZARD_LEAVES)  # exactly "parent > leaf"


# Sibling / neighbouring categories that ARE hazards and must keep their gate next to an allowlisted leaf.
@pytest.mark.parametrize("path,expected", [
    ("Home & Garden > Fireplace & Wood Stove Accessories > Firewood & Fuel", "GAS"),
    ("Home & Garden > Fireplace & Wood Stove Accessories > Wood Stove Fans & Blowers", "GAS"),
    ("Home & Garden > Fireplace & Wood Stove Accessories", "GAS"),
    ("Home & Garden > Fireplaces", "GAS"),
    ("Home & Garden > Wood Stoves", "GAS"),
    ("Home & Garden > Kitchen & Dining > Cookware & Bakeware > Cookware > Pressure Cookers & Canners", "MAINS_HEATING"),
    ("Home & Garden > Kitchen & Dining > Cookware & Bakeware > Cookware > Stovetop Kettles", "MAINS_HEATING"),
    ("Home & Garden > Kitchen & Dining > Kitchen Appliances > Coffee Makers & Espresso Machines > Espresso Machines", "MAINS_ELECTRIC"),
    ("Home & Garden > Kitchen & Dining > Kitchen Appliances > Coffee Makers & Espresso Machines > Percolators", "MAINS_ELECTRIC"),
    ("Home & Garden > Kitchen & Dining > Kitchen Appliances > Food Cookers & Steamers > Food Steamers", "MAINS_HEATING"),
    ("Home & Garden > Pool & Spa > Sauna Accessories > Sauna Heaters", "MAINS_HEATING"),
    ("Home & Garden > Pool & Spa > Sauna Accessories > Sauna Kits", "MAINS_HEATING"),
    ("Hardware > Power & Electrical Supplies > Power Outlets & Sockets", "MAINS_ELECTRIC"),
    ("Hardware > Power & Electrical Supplies > Generators", "MAINS_ELECTRIC"),
    ("Hardware > Power & Electrical Supplies > Electrical Switches", "MAINS_ELECTRIC"),
    ("Hardware > Power & Electrical Supplies > Wall Plates & Covers", "MAINS_ELECTRIC"),
    ("Hardware > Tool Accessories > Power Tool Chargers", "MAINS_ELECTRIC"),
    ("Hardware > Tool Accessories > Power Tool Batteries", "BATTERY_THERMAL"),
    ("Hardware > Plumbing > Plumbing Fittings & Supports > Plumbing Regulators", "GAS"),
    ("Sporting Goods > Outdoor Recreation > Boating & Water Sports > Diving & Snorkeling > Diving Regulators", "GAS"),
    ("Sporting Goods > Outdoor Recreation > Riding Scooters", "BATTERY_THERMAL"),
    ("Cameras & Optics > Photography > Lighting & Studio > Studio Lights & Flashes", "MAINS_ELECTRIC"),
    ("Cameras & Optics > Photography > Lighting & Studio > Studio Lighting Controls", "MAINS_ELECTRIC"),
    ("Health & Beauty > Personal Care > Hair Care > Hair Styling Tools > Curling Irons", "MAINS_HEATING"),
    ("Health & Beauty > Personal Care > Hair Care > Hair Permanents & Straighteners", "MAINS_HEATING"),
    ("Health & Beauty > Health Care > Biometric Monitors > Fertility Monitors and Ovulation Tests > Fertility Tests & Monitors", "MAINS_ELECTRIC"),
    ("Hardware > Tools > Masonry Tools > Cement Mixers", "MAINS_ELECTRIC"),
    ("Pet Supplies > Pet Grooming Supplies > Pet Hair Dryers", "MAINS_HEATING"),
])
def test_neighbours_of_allowlisted_leaves_keep_their_gate(path, expected):
    assert product_class({"name": NAME, "category": path}) == expected


def test_the_allowlist_is_exact_on_the_last_two_segments():
    leaf = "Hair Accessories > Hair Extensions"
    assert product_class({"name": NAME, "category": "Apparel > Clothing Accessories > " + leaf}) == "NONE"
    # leaf alone, a different parent, or a path cut after the parent: NOT exempt (fail-safe: stays gated)
    assert product_class({"name": NAME, "category": "Hair Extensions"}) in GATED_CLASSES
    assert product_class({"name": NAME, "category": "Salon > Hair Extensions"}) in GATED_CLASSES
    assert product_class({"name": NAME, "category": "Hair Accessories > Hair Extensions > Clip-in Hair Extensions"}) in GATED_CLASSES
    assert exempt_leaf("Hair Accessories > Hair Extensions") == "hair extension"
    assert exempt_leaf("Hair Extensions") is None and exempt_leaf(None) is None and exempt_leaf("") is None


def test_an_allowlisted_category_still_reads_the_product_name_except_the_leaf_phrase():
    cat = "Apparel & Accessories > Clothing Accessories > Hair Accessories > Hair Extensions"
    assert product_class({"name": "Clip-in Hair Extensions 20 inch", "category": cat}) == "NONE"
    assert product_class({"name": "Heated Hair Extensions Clip", "category": cat}) == "MAINS_HEATING"
    assert product_class({"name": "Rechargeable Hair Extensions Fan", "category": cat}) == "BATTERY_THERMAL"
    wash = "Hardware > Hardware Accessories > Hardware Fasteners > Washers"
    assert product_class({"name": "Stainless Flat Washers 100 pack", "category": wash}) == "NONE"
    assert product_class({"name": "Electric Washers 3 kW", "category": wash}) == "MAINS_ELECTRIC"
    dutch = "Home & Garden > Kitchen & Dining > Cookware & Bakeware > Cookware > Dutch Ovens"
    assert product_class({"name": "Cast Iron Dutch Oven 6 qt", "category": dutch}) == "MAINS_HEATING"  # "iron" in the NAME


# ------------------------------------------------------------------------------------------ taxonomy hazard list
# Hazard leaves (Google Product Taxonomy paths, which Channel3's categories follow): every one must stay gated.
TAXONOMY_HAZARDS = [
    "Home & Garden > Household Appliances > Climate Control Appliances > Space Heaters",
    "Home & Garden > Household Appliances > Climate Control Appliances > Patio Heaters",
    "Home & Garden > Household Appliances > Climate Control Appliances > Duct Heaters",
    "Home & Garden > Household Appliances > Climate Control Appliances > Furnaces & Boilers",
    "Home & Garden > Household Appliances > Climate Control Appliances > Air Conditioners",
    "Home & Garden > Household Appliances > Climate Control Appliances > Dehumidifiers",
    "Home & Garden > Household Appliances > Water Heaters",
    "Home & Garden > Household Appliances > Laundry Appliances > Dryers",
    "Home & Garden > Household Appliances > Laundry Appliances > Washing Machines",
    "Home & Garden > Household Appliances > Laundry Appliances > Garment Steamers",
    "Home & Garden > Household Appliances > Laundry Appliances > Irons & Ironing Systems",
    "Home & Garden > Household Appliances > Vacuums",
    "Home & Garden > Kitchen & Dining > Kitchen Appliances > Deep Fryers",
    "Home & Garden > Kitchen & Dining > Kitchen Appliances > Hot Plates",
    "Home & Garden > Kitchen & Dining > Kitchen Appliances > Ovens",
    "Home & Garden > Kitchen & Dining > Kitchen Appliances > Ranges",
    "Home & Garden > Kitchen & Dining > Kitchen Appliances > Cooktops",
    "Home & Garden > Kitchen & Dining > Kitchen Appliances > Outdoor Grills",
    "Home & Garden > Kitchen & Dining > Kitchen Appliances > Microwave Ovens",
    "Home & Garden > Kitchen & Dining > Kitchen Appliances > Electric Griddles & Grills",
    "Home & Garden > Kitchen & Dining > Kitchen Appliances > Food Cookers & Steamers > Slow Cookers",
    "Home & Garden > Kitchen & Dining > Kitchen Appliances > Food Cookers & Steamers > Rice Cookers",
    "Home & Garden > Kitchen & Dining > Kitchen Appliances > Toasters & Grills > Toasters",
    "Home & Garden > Kitchen & Dining > Kitchen Appliances > Toasters & Grills > Waffle Irons",
    "Home & Garden > Kitchen & Dining > Kitchen Appliances > Food Warmers > Food Heat Lamps",
    "Home & Garden > Kitchen & Dining > Kitchen Appliances > Beverage Warmers",
    "Home & Garden > Kitchen & Dining > Kitchen Appliances > Food Smokers",
    "Home & Garden > Kitchen & Dining > Kitchen Appliances > Blenders",
    "Home & Garden > Kitchen & Dining > Kitchen Appliances > Refrigerators",
    "Home & Garden > Kitchen & Dining > Kitchen Appliances > Freezers",
    "Home & Garden > Linens & Bedding > Bedding > Blankets > Electric Blankets",
    "Home & Garden > Lighting > Lamps",
    "Home & Garden > Lighting > Lighting Fixtures",
    "Home & Garden > Lighting > Emergency Lighting",
    "Home & Garden > Lighting > Tiki Torches & Oil Lamps",
    "Home & Garden > Pool & Spa > Pool & Spa Accessories > Pool Heaters",
    "Home & Garden > Pool & Spa > Saunas",
    "Home & Garden > Lawn & Garden > Outdoor Power Equipment Accessories > Outdoor Power Equipment Batteries",
    "Sporting Goods > Outdoor Recreation > Camping & Hiking > Camping Stoves",
    "Sporting Goods > Outdoor Recreation > Camping & Hiking > Camping Lights & Lanterns",
    "Sporting Goods > Outdoor Recreation > Camping & Hiking > Chemical Hand Warmers",
    "Hardware > Fuel",
    "Hardware > Fuel Containers & Tanks",
    "Hardware > Tools > Lighters & Matches",
    "Hardware > Tools > Heat Guns",
    "Hardware > Tools > Hardware Torches",
    "Hardware > Tools > Soldering Irons",
    "Hardware > Tools > Flashlights & Headlamps > Flashlights",
    "Hardware > Tools > Drills > Handheld Power Drills",
    "Hardware > Tools > Multifunction Power Tools",
    "Hardware > Tools > Compressors",
    "Hardware > Power & Electrical Supplies > Generators",
    "Hardware > Power & Electrical Supplies > Power Inverters",
    "Hardware > Power & Electrical Supplies > Power Converters",
    "Hardware > Power & Electrical Supplies > Solar Panels",
    "Hardware > Power & Electrical Supplies > Electrical Motors",
    "Hardware > Power & Electrical Supplies > Circuit Breaker Panels",
    "Hardware > Tools > Welding Guns & Plasma Cutters",
    "Health & Beauty > Personal Care > Hair Care > Hair Styling Tools > Hair Dryers",
    "Health & Beauty > Personal Care > Hair Care > Hair Styling Tools > Hair Straighteners",
    "Health & Beauty > Personal Care > Hair Care > Hair Styling Tools > Curling Irons",
    "Health & Beauty > Personal Care > Hair Care > Hair Steamers & Heat Caps",
    "Health & Beauty > Personal Care > Skin Care Tools > Facial Saunas",
    "Health & Beauty > Personal Care > Hair Removal > Hair Removal Wax Warmers",
    "Health & Beauty > Personal Care > Massage & Relaxation > Massage Stone Warmers",
    "Health & Beauty > Health Care > Respiratory Care > Steam Inhalers",
    "Health & Beauty > Health Care > Respiratory Care > Oxygen Tanks",
    "Baby & Toddler > Nursing & Feeding > Bottle Warmers & Sterilizers",
    "Baby & Toddler > Baby Safety > Baby Monitors",
    "Toys & Games > Toys > Remote Control Toys > Remote Control Helicopters",
    "Toys & Games > Toys > Remote Control Toys > Remote Control Cars & Trucks",
    "Toys & Games > Toys > Robotic Toys",
    "Vehicles & Parts > Vehicle Parts & Accessories > Vehicle Maintenance, Care & Decor > Vehicle Repair & Specialty Tools > Vehicle Jump Starters",
    "Vehicles & Parts > Vehicle Parts & Accessories > Vehicle Maintenance, Care & Decor > Portable Fuel Cans",
    "Vehicles & Parts > Vehicle Parts & Accessories > Motor Vehicle Parts > Motor Vehicle Fuel Systems",
    "Vehicles & Parts > Vehicle Parts & Accessories > Motor Vehicle Parts > Motor Vehicle Lighting",
    "Business & Industrial > Food Service > Hot Dog Rollers",
    "Business & Industrial > Food Service > Plate & Dish Warmers",
    "Arts & Entertainment > Hobbies & Creative Arts > Arts & Crafts > Art & Crafting Tools > Glue Guns",
    "Electronics > Electronics Accessories > Power > Power Adapters & Chargers",
    "Electronics > Video > Televisions",
    "Electronics > Electronics Accessories > Computer Components > Laptop Batteries",
]


@pytest.mark.parametrize("path", TAXONOMY_HAZARDS)
def test_every_taxonomy_hazard_leaf_is_gated_and_holds_a_plain_fault(path):
    assert product_class({"name": NAME, "category": path}) in GATED_CLASSES, path
    assert assess(PLAIN_FAULT, {"name": NAME, "category": path}).flagged, path


def test_no_hazard_path_is_exempt_and_every_exempt_path_is_in_the_allowlist():
    """The allowlist never touches a hazard path: no TAXONOMY_HAZARDS / REAL_PATHS hazard entry ends in an exempt pair."""
    for path in TAXONOMY_HAZARDS + [p for p, k in REAL_PATHS if k != "NONE"]:
        assert exempt_leaf(path) is None, path


# The gap words added in round 2 (each needed by a real taxonomy leaf with no other hazard word).
@pytest.mark.parametrize("category,expected", [
    ("Lighting", "MAINS_ELECTRIC"), ("Track Lighting", "MAINS_ELECTRIC"), ("Electrical Supplies", "MAINS_ELECTRIC"),
    ("Generators", "MAINS_ELECTRIC"), ("Power Inverters", "MAINS_ELECTRIC"), ("Air Compressors", "MAINS_ELECTRIC"),
    ("Power Drills", "MAINS_ELECTRIC"), ("Power Tools", "MAINS_ELECTRIC"), ("Powered Hammers", "MAINS_ELECTRIC"),
    ("Welders", "MAINS_ELECTRIC"), ("Plasma Cutters", "MAINS_ELECTRIC"),
    ("Fuel Containers", "GAS"), ("Fuel Tanks", "GAS"), ("Gasoline", "GAS"), ("Kerosene", "GAS"), ("Torches", "GAS"),
    ("Oxygen Tanks", "GAS"), ("Fireplaces", "GAS"),
    ("Saunas", "MAINS_HEATING"), ("Heat Guns", "MAINS_HEATING"), ("Glue Guns", "MAINS_HEATING"),
    ("Wax Warmers", "MAINS_HEATING"), ("Bottle Warmers", "MAINS_HEATING"), ("Steam Cleaners", "MAINS_HEATING"),
    ("Steam Mops", "MAINS_HEATING"), ("Hot Dog Rollers", "MAINS_HEATING"), ("Foot Warmers", "MAINS_HEATING"),
    ("Flashlights", "BATTERY_THERMAL"), ("Headlamps", "BATTERY_THERMAL"), ("Jump Starters", "BATTERY_THERMAL"),
    ("Remote Control Cars", "BATTERY_THERMAL"), ("Remote Control Helicopters", "BATTERY_THERMAL"),
    ("Robotic Toys", "BATTERY_THERMAL"), ("Hand Warmers", "BATTERY_THERMAL"),
])
def test_round_two_gap_words(category, expected):
    assert product_class({"name": NAME, "category": category}) == expected


@pytest.mark.parametrize("name,category", [
    (NAME, "Hot Dog Buns"), (NAME, "Jump Ropes"), (NAME, "Remote Controls Storage Sleeves"), ("Fuelled Up Poster", "Posters"),
    ("Torchwood DVD", "Movies"), ("Warmers Club Tee", "T-Shirts"), ("Generation Z Book", "Books"), ("Saunafinland Mug", "Mugs"),
    ("Poweredge Server Rack Shelf", "Shelves"), ("Electrician Pliers", "Hand Tools"), ("Flashlightning Poster", "Posters"),
])
def test_round_two_words_do_not_match_inside_other_words(name, category):
    assert product_class({"name": name, "category": category}) == "NONE"
