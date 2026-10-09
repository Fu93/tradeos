"""Supplier coordination for the MVP: a generated draft plus ONE clearly labelled mock reply.

There is no live supplier channel in the MVP (plan §8). The reply below is a
mock and is always labelled as such in the UI and the audit timeline.
"""

from __future__ import annotations

MOCK_LABEL = "MOCK supplier reply — simulated for the demo, not a real supplier"
REPLACEMENT_APPROVED = "REPLACEMENT_APPROVED"


def draft_supplier_message(case: dict, product: dict, intent: dict) -> str:
    return (
        f"To: {product['supplier']}\n"
        f"Subject: Replacement request — order {case.get('order_id') or case['id']} ({product['name']})\n\n"
        f"Hello,\n\n"
        f"Our customer {case['customer_name']} has requested an exchange "
        f"(reason: {intent.get('reason', 'UNKNOWN').replace('_', ' ').lower()}).\n"
        f"Customer message: \"{case['customer_message']}\"\n\n"
        f"Product: {product['name']} (SKU {product['sku']})\n"
        f"Please confirm you can ship a replacement in the requested size.\n\n"
        f"Reference: TradeOS case {case['id']}\n"
        f"Thank you."
    )


def mock_supplier_reply(case: dict) -> dict:
    return {
        "status": REPLACEMENT_APPROVED,
        "label": MOCK_LABEL,
        "is_mock": True,
        "message": f"Replacement approved for case {case['id']}. New size will ship within 3 business days.",
    }
