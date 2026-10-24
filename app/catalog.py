"""Real products for agents to buy: Channel3's product catalogue (optional, CHANNEL3_API_KEY).

An agent that shops for a buyer finds a product first. With a Channel3 key, the MCP gateway offers find_product (a
read-only search of Channel3's catalogue) and place_demo_order accepts a product_id from it. The server looks the
product up again by id: its title, retailer, category and price come from Channel3, never from what the agent says.
The Sandbox order is placed at that price, so the whole loop runs on a real product: discover (Channel3), pay
(PayPal Sandbox), return (TradeOS). The category reaches the Safety Gate, which classes a product by its name and
category, so a kettle or a heater bought through an agent is gated like the dashboard's own products.

Docs: https://docs.trychannel3.com (POST /v1/search, GET /v1/products/{id}, header x-api-key). Without a key nothing
here is used and the demo sneakers stay the only product.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

CHANNEL3_BASE_URL = "https://api.trychannel3.com"
SEARCH_LIMIT = 5
QUERY_MAX = 120


class CatalogError(Exception):
    """The catalogue could not answer (network, HTTP error, unusable product). The message is safe to show."""


@dataclass(frozen=True)
class CatalogProduct:
    id: str
    title: str
    brand: str
    category: str
    price: str      # decimal string, e.g. "89.95": the price of the offer chosen below
    currency: str
    retailer: str   # the offer's domain

    @property
    def sku(self) -> str:
        return f"C3-{self.id}"[:64]

    def view(self) -> dict[str, Any]:
        return {"product_id": self.id, "title": self.title, "brand": self.brand or None,
                "category": self.category or None, "price": self.price, "currency": self.currency,
                "retailer": self.retailer}


def _price(raw: Any) -> Decimal | None:
    """Channel3's offer price object: the schema names it price.price, its guide shows price.amount."""
    if not isinstance(raw, dict):
        return None
    value = raw.get("price", raw.get("amount"))
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return price if price.is_finite() and price > 0 else None


def _category(raw: Any) -> str:
    """Channel3's CategorySummary: {slug, title, path: [{slug, title}, ...] (root first, last = this category)}.
    Titles only, and the leaf is kept when the text is cut (the Safety Gate reads the category's words)."""
    if not isinstance(raw, dict):
        return ""
    path = raw.get("path")
    if isinstance(path, str):
        parts = [path]
    else:
        parts = [str(c.get("title") if isinstance(c, dict) else c) for c in path or [] if c]
    if not parts and raw.get("title"):
        parts = [str(raw["title"])]
    return " > ".join(p for p in parts if p and p != "None")[-120:]


def normalize(raw: Any, currency: str) -> CatalogProduct | None:
    """One Channel3 product -> the fields TradeOS uses, priced from its first in-stock offer in our currency.
    None when the product has no such offer (it cannot be bought here)."""
    if not isinstance(raw, dict) or not raw.get("id") or not raw.get("title"):
        return None
    for offer in raw.get("offers") or []:
        if not isinstance(offer, dict) or offer.get("availability") not in (None, "InStock"):
            continue
        price_obj = offer.get("price") or {}
        price = _price(price_obj)
        if price is None or str(price_obj.get("currency") or "").upper() != currency:
            continue
        brands = raw.get("brands") or []
        brand = brands[0].get("name", "") if brands and isinstance(brands[0], dict) else ""
        cat = _category(raw.get("category"))
        try:
            cents = price.quantize(Decimal("0.01"))
        except InvalidOperation:  # absurdly large: unusable, like an unreadable price
            continue
        if cents <= 0:  # 0.001 rounds to 0.00
            continue
        return CatalogProduct(id=str(raw["id"])[:40], title=" ".join(str(raw["title"]).split())[:120],
                              brand=str(brand)[:60], category=cat,
                              price=str(cents), currency=currency,
                              retailer=str(offer.get("domain") or "")[:80])
    return None


class Channel3Catalog:
    name = "Channel3"

    def __init__(self, api_key: str, base_url: str = CHANNEL3_BASE_URL, currency: str = "USD", timeout: float = 8.0,
                 transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport,
                                    headers={"x-api-key": api_key, "accept": "application/json"})
        self.currency = currency

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            r = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise CatalogError(f"the product catalogue could not be reached ({type(exc).__name__})") from None
        if r.status_code == 404:
            raise CatalogError("no such product in the catalogue")
        if r.status_code >= 400:
            raise CatalogError(f"the product catalogue answered HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError:
            raise CatalogError("the product catalogue sent an unreadable answer") from None

    def search(self, query: str, max_price: Decimal | None = None) -> list[CatalogProduct]:
        query = " ".join((query or "").split())[:QUERY_MAX]
        if not query:
            raise CatalogError("describe the product to search for")
        filters: dict[str, Any] = {"availability": ["InStock"]}
        if max_price is not None:
            filters["price"] = {"max_price": float(max_price)}
        data = self._call("POST", "/v1/search", json={"query": query, "limit": SEARCH_LIMIT, "filters": filters})
        products = data.get("products") if isinstance(data, dict) else None
        found = [p for p in (normalize(raw, self.currency) for raw in products or []) if p is not None]
        return found[:SEARCH_LIMIT]

    def get(self, product_id: str) -> CatalogProduct:
        product_id = str(product_id or "").strip()
        if not product_id or len(product_id) > 64 or not all((c.isascii() and c.isalnum()) or c in "-_" for c in product_id):
            raise CatalogError("product_id must be an id returned by find_product")
        product = normalize(self._call("GET", f"/v1/products/{product_id}"), self.currency)
        if product is None:
            raise CatalogError(f"that product has no in-stock offer in {self.currency}")
        return product
