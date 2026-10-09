"""Supplier coordination for the MVP: a generated draft plus a clearly labelled mock reply.

There is no live supplier channel. The reply is a mock and is always labelled as such.
"""

from __future__ import annotations

MOCK_LABEL = "MOCK supplier reply — simulated for the demo, not a real supplier"
REPLACEMENT_APPROVED = "REPLACEMENT_APPROVED"
REPLACEMENT_DECLINED = "REPLACEMENT_DECLINED"


def draft_supplier_message(case: dict, product: dict, intent: dict) -> str:
    sizes = ""
    assist = case.get("assist") or {}
    if isinstance(assist, dict) and (assist.get("current_size") or assist.get("requested_size")):
        sizes = f"{assist.get('current_size') or '?'} → {assist.get('requested_size') or '?'}"
    reason = intent.get("reason", "UNKNOWN").replace("_", " ").lower()
    return (
        f"To: {product['supplier']}\n"
        f"Subject: Replacement request — order {case.get('order_id') or case['id']} ({product['name']})\n\n"
        f"【草稿 · 尚未寄出 · 不是真的供應商】\n"
        f"訂單 {case.get('order_id') or case['id']}，商品 {product['name']}（SKU {product['sku']}）。\n"
        f"客人要換貨，原因：{reason}。尺寸：{sizes or '未標明'}。\n"
        f"請回覆能否補寄。只能回同意或拒絕。\n"
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
