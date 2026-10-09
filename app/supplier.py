"""Supplier coordination for the MVP: a generated draft plus a clearly labelled mock reply.

There is no live supplier channel. The reply is a mock and is always labelled as such.
"""

from __future__ import annotations

MOCK_LABEL = "MOCK supplier reply — simulated for the demo, not a real supplier"
REPLACEMENT_APPROVED = "REPLACEMENT_APPROVED"
REPLACEMENT_DECLINED = "REPLACEMENT_DECLINED"
SUPPLIER_REQUIRED = "SUPPLIER_REQUIRED"
HUMAN = "HUMAN"

# Offline table. The model does not choose this. Only a size mismatch asks the supplier.
def route_for_reason(reason: str | None) -> str:
    if reason == "SIZE_MISMATCH":
        return SUPPLIER_REQUIRED
    return HUMAN


def draft_supplier_message(case: dict, product: dict, intent: dict) -> str:
    sizes = ""
    assist = case.get("assist") or {}
    if isinstance(assist, dict) and assist.get("current_size") and assist.get("requested_size"):
        sizes = f"{assist['current_size']} → {assist['requested_size']}"
    if not sizes:
        import re
        found = re.findall(r"\b(\d{2})\b", case.get("customer_message") or "")
        if len(found) >= 2:
            sizes = f"{found[0]} → {found[1]}"
    reason = intent.get("reason", "UNKNOWN").replace("_", " ").lower()
    ask = f"請確認能否補寄此尺寸（{sizes}）。\n" if sizes else ""
    return (
        f"To: {product['supplier']}\n"
        f"Subject: Replacement request — order {case.get('order_id') or case['id']} ({product['name']})\n\n"
        f"【草稿 · 尚未寄出 · 不是真的供應商】\n"
        f"訂單 {case.get('order_id') or case['id']}，商品 {product['name']}（SKU {product['sku']}）。\n"
        f"客人要換貨，原因：{reason}。\n"
        f"{ask}"
        f"請只回覆同意或拒絕。\n"
        f"案件 {case['id']}\n\n"
        f"English copy of the same draft:\n"
        f"Customer {case['customer_name']} requested an exchange ({reason}).\n"
        f"Customer message: \"{case['customer_message']}\"\n"
        f"Please confirm a replacement. Reference: TradeOS case {case['id']}."
    )


def mock_supplier_reply(case: dict, decision: str = "approve") -> dict:
    approved = decision != "decline"
    return {
        "status": REPLACEMENT_APPROVED if approved else REPLACEMENT_DECLINED,
        "label": MOCK_LABEL,
        "is_mock": True,
        "decision": "approve" if approved else "decline",
        "message": (
            f"MOCK: replacement approved for case {case['id']}. Not a real supplier."
            if approved else
            f"MOCK: replacement declined for case {case['id']}. Not a real supplier."
        ),
    }
