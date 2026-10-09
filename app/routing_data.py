"""MOCK data for the supplier-routing experiment (MVP 1). EVERYTHING IN THIS FILE IS MOCK.

Small, hand-written catalog / inventory / logistics / supplier-capability tables so the
routing gates (app/routing.py) have something real-shaped to check. None of it comes from
a real shop, warehouse, carrier or supplier, and the UI labels every value read from here
as MOCK. Dates are relative ("days_ago") so the dataset never goes stale.
"""

from __future__ import annotations

from datetime import date, timedelta

MOCK_LABEL = "MOCK data — fictional catalog / inventory / logistics / supplier table (experiment)"

# --------------------------------------------------------------------------------------------
# Catalog + supplier capability / responsibility table (one row per SKU)
#
# fulfilment            MERCHANT_WAREHOUSE (we hold stock and ship) or SUPPLIER_DROPSHIP
# confirms_stock        supplier is the source of truth for variant stock / exchange feasibility
# restocks_on_request   supplier can be asked to restock a variant we are out of
# reships               supplier ships replacements for shipments it fulfilled
# warranty_by/days      SUPPLIER (supplier warranty), MERCHANT (our own process) or NONE
# supplies_parts        supplier sells spare parts
# answers_compatibility supplier can confirm part compatibility for unknown part numbers
# part_prefix           part numbers of this product family start with this prefix
# --------------------------------------------------------------------------------------------
CATALOG: dict[str, dict] = {
    "TRAIL-RUNNER-42": {
        "name": "Trail Runner sneakers", "category": "footwear", "returnable": True,
        "variants": {str(n): [str(n)] for n in range(38, 47)}, "variant_kind": "size",
        "aliases": ["shoes", "shoe", "sneakers", "sneaker", "trainers", "鞋子", "球鞋", "鞋", "zapatillas",
                    "zapatos", "Schuhe", "Sneaker", "Laufschuhe", "スニーカー", "シューズ", "靴"],
        "supplier": "Stride Footwear Co. (MOCK supplier)", "fulfilment": "SUPPLIER_DROPSHIP",
        "confirms_stock": True, "restocks_on_request": False, "reships": True,
        "warranty_by": "SUPPLIER", "warranty_days": 180,
        "supplies_parts": False, "answers_compatibility": False, "part_prefix": "TR-",
    },
    "CITY-JACKET": {
        "name": "City rain jacket", "category": "apparel", "returnable": True,
        "variants": {"S": ["S"], "M": ["M"], "L": ["L"], "XL": ["XL"]}, "variant_kind": "size",
        "aliases": ["rain jacket", "jacket", "raincoat", "雨衣", "外套", "夾克", "chaqueta", "impermeable",
                    "Regenjacke", "Jacke", "ジャケット", "レインコート"],
        "supplier": "Northwind Apparel (MOCK supplier)", "fulfilment": "MERCHANT_WAREHOUSE",
        "confirms_stock": True, "restocks_on_request": True, "reships": False,
        "warranty_by": "NONE", "warranty_days": 0,
        "supplies_parts": False, "answers_compatibility": False, "part_prefix": "CJ-",
    },
    "BACKPACK-30L": {
        "name": "Daypack 30L", "category": "bags", "returnable": True,
        "variants": {"black": ["black", "negro", "negra", "schwarz", "schwarzen", "黑色", "黑", "ブラック", "黒"],
                     "green": ["green", "verde", "grün", "grüne", "grünen", "綠色", "綠", "グリーン", "緑"],
                     "navy": ["navy", "azul marino", "marineblau", "marineblaue", "海軍藍", "深藍", "ネイビー", "紺"]},
        "variant_kind": "colour",
        "aliases": ["backpack", "daypack", "bag", "背包", "mochila", "Rucksack", "リュック", "バックパック"],
        "supplier": "Peak Bags (MOCK supplier)", "fulfilment": "MERCHANT_WAREHOUSE",
        "confirms_stock": False, "restocks_on_request": False, "reships": False,
        "warranty_by": "MERCHANT", "warranty_days": 365,
        "supplies_parts": False, "answers_compatibility": False, "part_prefix": "BP-",
    },
    "BREW-KETTLE": {
        "name": "Electric kettle 1.7 L", "category": "appliance", "returnable": True,
        "variants": {"standard": []}, "variant_kind": "model",
        "aliases": ["kettle", "電熱水壺", "熱水壺", "快煮壺", "hervidor", "Wasserkocher", "電気ケトル", "ケトル"],
        "supplier": "Kettleworks Ltd. (MOCK supplier)", "fulfilment": "MERCHANT_WAREHOUSE",
        "confirms_stock": False, "restocks_on_request": False, "reships": False,
        "warranty_by": "SUPPLIER", "warranty_days": 365,
        "supplies_parts": True, "answers_compatibility": True, "part_prefix": "KL-170-",
    },
    "DESK-LAMP": {
        "name": "LED desk lamp", "category": "lighting", "returnable": True,
        "variants": {"white": ["white", "blanca", "blanco", "weiß", "weiss", "weiße", "白色", "白", "ホワイト"],
                     "black": ["black", "negra", "negro", "schwarz", "schwarze", "黑色", "黑", "ブラック", "黒"]},
        "variant_kind": "colour",
        "aliases": ["desk lamp", "lamp", "檯燈", "台燈", "lámpara", "lampara", "Schreibtischlampe", "Lampe",
                    "デスクライト", "ランプ", "ライト"],
        "supplier": "Lumina Lighting (MOCK supplier)", "fulfilment": "SUPPLIER_DROPSHIP",
        "confirms_stock": True, "restocks_on_request": False, "reships": True,
        "warranty_by": "SUPPLIER", "warranty_days": 730,
        "supplies_parts": True, "answers_compatibility": True, "part_prefix": "DL-",
    },
    "CAMP-STOVE": {
        "name": "Camping gas stove", "category": "outdoor", "returnable": True,
        "variants": {"standard": []}, "variant_kind": "model",
        "aliases": ["camping stove", "stove", "瓦斯爐", "爐子", "露營爐", "hornillo", "Gaskocher", "Campingkocher",
                    "Kocher", "コンロ", "バーナー"],
        "supplier": "Blaze Outdoor (MOCK supplier)", "fulfilment": "MERCHANT_WAREHOUSE",
        "confirms_stock": False, "restocks_on_request": False, "reships": False,
        "warranty_by": "SUPPLIER", "warranty_days": 365,
        "supplies_parts": False, "answers_compatibility": False, "part_prefix": "CS-",
    },
    "SALE-SOCKS": {
        "name": "Merino socks (final sale)", "category": "apparel", "returnable": False,
        "variants": {"S": ["S"], "M": ["M"], "L": ["L"]}, "variant_kind": "size",
        "aliases": ["socks", "襪子", "calcetines", "Socken", "靴下"],
        "supplier": "Northwind Apparel (MOCK supplier)", "fulfilment": "MERCHANT_WAREHOUSE",
        "confirms_stock": True, "restocks_on_request": True, "reships": False,
        "warranty_by": "NONE", "warranty_days": 0,
        "supplies_parts": False, "answers_compatibility": False, "part_prefix": "SK-",
    },
}

# Merchant warehouse stock per (sku, variant). A missing key means "no inventory record" (NOT zero).
INVENTORY: dict[tuple[str, str], int] = {
    ("CITY-JACKET", "S"): 3, ("CITY-JACKET", "M"): 5, ("CITY-JACKET", "L"): 0, ("CITY-JACKET", "XL"): 2,
    ("BACKPACK-30L", "black"): 4, ("BACKPACK-30L", "green"): 0,  # navy: no record on purpose
    ("SALE-SOCKS", "S"): 10, ("SALE-SOCKS", "M"): 10, ("SALE-SOCKS", "L"): 10,
    ("BREW-KETTLE", "standard"): 6, ("CAMP-STOVE", "standard"): 2,
}

# Spare parts: part number -> compatible SKU + merchant stock. Unknown part numbers are simply absent.
PARTS: dict[str, dict] = {
    "KL-170-FLT": {"name": "Limescale filter", "sku": "BREW-KETTLE", "stock": 12},
    "KL-170-LID": {"name": "Lid assembly", "sku": "BREW-KETTLE", "stock": 0},
    "KL-170-BASE": {"name": "Power base", "sku": "BREW-KETTLE", "stock": 0},
    "DL-LED-5W": {"name": "5 W LED module", "sku": "DESK-LAMP", "stock": 0},
    "DL-CLAMP-M": {"name": "Desk clamp (M)", "sku": "DESK-LAMP", "stock": 0},
    "CS-VALVE-2": {"name": "Gas valve", "sku": "CAMP-STOVE", "stock": 0},
    "BP-BUCKLE-25": {"name": "25 mm buckle", "sku": "BACKPACK-30L", "stock": 30},
}

# --------------------------------------------------------------------------------------------
# Orders (MOCK). Each line: sku, variant, qty. logistics per line: status + details.
# Logistics statuses: IN_TRANSIT, DELIVERED (all items), DELIVERED_PARTIAL (scan shows fewer
# items than ordered), LOST (carrier declared lost). No "logistics" key => no record.
# --------------------------------------------------------------------------------------------
def _o(order_id, customer, days_ago, lines):
    return {"order_id": order_id, "customer": customer, "days_ago": days_ago, "lines": lines}


def _l(sku, variant, qty=1, logistics=None):
    return {"sku": sku, "variant": variant, "qty": qty, "logistics": logistics}


DEL = {"status": "DELIVERED", "carrier": "MockPost"}

ORDERS_RAW = [
    # exchange
    _o("TO-10421", "ana@example.test", 10, [_l("TRAIL-RUNNER-42", "42", logistics=DEL)]),
    _o("TO-10412", "ben@example.test", 12, [_l("TRAIL-RUNNER-42", "41", logistics=DEL)]),
    _o("TO-10431", "gus@example.test", 40, [_l("TRAIL-RUNNER-42", "44", logistics=DEL)]),
    _o("TO-20031", "chen@example.test", 8, [_l("CITY-JACKET", "M", logistics=DEL)]),
    _o("TO-20013", "dora@example.test", 50, [_l("CITY-JACKET", "L", logistics=DEL)]),
    _o("TO-30077", "eva@example.test", 5, [_l("BACKPACK-30L", "black", logistics=DEL)]),
    _o("TO-40005", "felix@example.test", 6, [_l("SALE-SOCKS", "M", logistics=DEL)]),
    _o("TO-40011", "ola@example.test", 9, [_l("DESK-LAMP", "white", logistics=DEL)]),
    _o("TO-10433", "cara@example.test", 15, [_l("TRAIL-RUNNER-42", "39", logistics=DEL)]),
    _o("TO-10434", "dan@example.test", 20, [_l("TRAIL-RUNNER-42", "45", logistics=DEL)]),
    _o("TO-10435", "emi@example.test", 2, [_l("TRAIL-RUNNER-42", "40", logistics=DEL)]),
    _o("TO-40012", "fay@example.test", 14, [_l("DESK-LAMP", "black", logistics=DEL)]),
    _o("TO-20032", "gil@example.test", 3, [_l("CITY-JACKET", "S", logistics=DEL)]),
    _o("TO-20033", "hal@example.test", 12, [_l("CITY-JACKET", "XL", logistics=DEL)]),
    # reship
    _o("TO-50101", "hana@example.test", 7,
       [_l("DESK-LAMP", "white", qty=2, logistics={"status": "DELIVERED_PARTIAL", "delivered_qty": 1,
                                                   "carrier": "MockPost"})]),
    _o("TO-50110", "ivan@example.test", 9, [_l("BREW-KETTLE", "standard", logistics={"status": "LOST",
                                                                                     "carrier": "MockPost"})]),
    _o("TO-50120", "jon@example.test", 3,
       [_l("TRAIL-RUNNER-42", "44", logistics={"status": "IN_TRANSIT", "eta_days": 3, "carrier": "MockPost",
                                               "tracking": "MP123456789"})]),
    _o("TO-50130", "kim@example.test", 6, [_l("BACKPACK-30L", "navy", logistics=DEL)]),
    _o("TO-50140", "lea@example.test", 8,
       [_l("BREW-KETTLE", "standard", logistics=DEL),
        _l("DESK-LAMP", "black", logistics={"status": "LOST", "carrier": "MockPost"})]),
    _o("TO-50150", "max@example.test", 10, [_l("CITY-JACKET", "S", logistics={"status": "LOST",
                                                                              "carrier": "MockPost"})]),
    _o("TO-50160", "noa@example.test", 4, [_l("BREW-KETTLE", "standard")]),  # no logistics record
    _o("TO-50170", "oli@example.test", 8, [_l("DESK-LAMP", "black", logistics={"status": "LOST",
                                                                               "carrier": "MockPost"})]),
    _o("TO-50180", "pat@example.test", 6,
       [_l("DESK-LAMP", "white", qty=3, logistics={"status": "DELIVERED_PARTIAL", "delivered_qty": 2,
                                                   "carrier": "MockPost"})]),
    _o("TO-50181", "ray@example.test", 9, [_l("TRAIL-RUNNER-42", "41", logistics={"status": "LOST",
                                                                                  "carrier": "MockPost"})]),
    _o("TO-50182", "sol@example.test", 5,
       [_l("TRAIL-RUNNER-42", "43", qty=2, logistics={"status": "DELIVERED_PARTIAL", "delivered_qty": 1,
                                                      "carrier": "MockPost"})]),
    _o("TO-50183", "ted@example.test", 11, [_l("DESK-LAMP", "black", logistics={"status": "LOST",
                                                                                "carrier": "MockPost"})]),
    _o("TO-50184", "una@example.test", 7, [_l("CITY-JACKET", "L", logistics={"status": "LOST",
                                                                             "carrier": "MockPost"})]),
    # defect
    _o("TO-60201", "pia@example.test", 10, [_l("BREW-KETTLE", "standard", logistics=DEL)]),
    _o("TO-60202", "quinn@example.test", 120, [_l("BREW-KETTLE", "standard", logistics=DEL)]),
    _o("TO-60203", "rui@example.test", 400, [_l("BREW-KETTLE", "standard", logistics=DEL)]),
    _o("TO-60204", "sara@example.test", 90, [_l("DESK-LAMP", "white", logistics=DEL)]),
    _o("TO-60205", "tim@example.test", 70, [_l("CITY-JACKET", "M", logistics=DEL)]),
    _o("TO-60206", "uma@example.test", 20, [_l("CAMP-STOVE", "standard", logistics=DEL)]),
    _o("TO-60207", "vic@example.test", 100, [_l("TRAIL-RUNNER-42", "43", logistics=DEL)]),
    _o("TO-60208", "zoe@example.test", 200, [_l("BACKPACK-30L", "green", logistics=DEL)]),
    _o("TO-60211", "amy@example.test", 200, [_l("BREW-KETTLE", "standard", logistics=DEL)]),
    _o("TO-60212", "bo@example.test", 400, [_l("DESK-LAMP", "black", logistics=DEL)]),
    _o("TO-60213", "cy@example.test", 60, [_l("TRAIL-RUNNER-42", "38", logistics=DEL)]),
    # part replacement
    _o("TO-70301", "wen@example.test", 200, [_l("BREW-KETTLE", "standard", logistics=DEL)]),
    _o("TO-70302", "xia@example.test", 150, [_l("DESK-LAMP", "white", logistics=DEL)]),
    _o("TO-70303", "yan@example.test", 100, [_l("CAMP-STOVE", "standard", logistics=DEL)]),
    _o("TO-70304", "zoe@example.test", 60, [_l("BACKPACK-30L", "black", logistics=DEL)]),
    _o("TO-70305", "abe@example.test", 80, [_l("TRAIL-RUNNER-42", "40", logistics=DEL)]),
    _o("TO-70306", "bea@example.test", 90, [_l("BREW-KETTLE", "standard", logistics=DEL)]),
    _o("TO-70307", "cal@example.test", 300, [_l("DESK-LAMP", "black", logistics=DEL)]),
    _o("TO-70308", "dee@example.test", 30, [_l("BREW-KETTLE", "standard", logistics=DEL)]),
    _o("TO-70309", "eli@example.test", 45, [_l("DESK-LAMP", "white", logistics=DEL)]),
    _o("TO-70310", "fin@example.test", 500, [_l("BREW-KETTLE", "standard", logistics=DEL)]),
    _o("TO-70311", "gia@example.test", 100, [_l("BACKPACK-30L", "black", logistics=DEL)]),
    _o("TO-70312", "hux@example.test", 50, [_l("CAMP-STOVE", "standard", logistics=DEL)]),
]
ORDERS: dict[str, dict] = {o["order_id"]: o for o in ORDERS_RAW}


def order_with_dates(order_id: str, today: date) -> dict | None:
    """Return a copy of a MOCK order with a concrete order_date relative to `today`."""
    raw = ORDERS.get(order_id)
    if raw is None:
        return None
    o = {**raw, "lines": [dict(l) for l in raw["lines"]], "is_mock": True}
    o["order_date"] = (today - timedelta(days=raw["days_ago"])).isoformat()
    return o


def orders_for_customer(customer: str) -> list[str]:
    return [o["order_id"] for o in ORDERS_RAW if o["customer"] == customer]


# --------------------------------------------------------------------------------------------
# Taxonomy v3 additions (MOCK). Hazard class per SKU lives in the catalogue, never decided by the LLM.
#   GAS_APPLIANCE   any defect / part need / missing item -> human (D6)
#   MAINS_ELECTRIC  burn / scorch / melt / heat / sparks / water in power part, or power parts -> human (D5)
# --------------------------------------------------------------------------------------------
HAZARD_CLASS: dict[str, str] = {
    "CAMP-STOVE": "GAS_APPLIANCE", "BREW-KETTLE": "MAINS_ELECTRIC", "DESK-LAMP": "MAINS_ELECTRIC",
    "TRAIL-RUNNER-42": "NONE", "CITY-JACKET": "NONE", "BACKPACK-30L": "NONE", "SALE-SOCKS": "NONE",
}
POWER_PARTS = {"KL-170-BASE"}  # power base / cable / plug / battery parts (S4)

# Held-out v2 MOCK orders (fresh ids TO-8xxxx), generated by scripts/v3/heldout_v2_design.py before any v2 run.
from app.routing_data_v2 import ORDERS_V2_RAW  # noqa: E402

ORDERS_RAW.extend(_o(o["order_id"], o["customer"], o["days_ago"], o["lines"]) for o in ORDERS_V2_RAW)
ORDERS.update({o["order_id"]: o for o in ORDERS_RAW})
