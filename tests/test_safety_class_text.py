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
from app.safety import GATED_CLASSES, _CLASS_RULES, _singular, assess, class_text, normalize, product_class

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
