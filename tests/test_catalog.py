"""Channel3 product catalogue (app/catalog.py): agents find a real product, buy it in the Sandbox, and return it.

Channel3 is faked with httpx.MockTransport, shaped like its documented API (POST /v1/search, GET /v1/products/{id},
x-api-key). What is tested is TradeOS's side: the server looks a product up itself (the agent sets no price or name),
caps the price, records the product on the chain, and the Safety Gate sees the real category.
"""
from __future__ import annotations

import json
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient
from mcp import Client

from app.agent_gateway import build_mcp_server
from app.catalog import Channel3Catalog, normalize
from app.config import Settings
from app.intent import KeywordIntentExtractor
from app.main import create_app
from app.paypal_mock import MockPayPalClient
from app.workflow import Workflow
from app.db import Database


def offer(price, currency="USD", availability="InStock", key="price"):
    return {"url": "https://buy.example/x", "domain": "shop.example", "availability": availability,
            "price": {key: price, "currency": currency}}


PRODUCTS = {
    "SNK1": {"id": "SNK1", "title": "White Leather Sneakers", "brands": [{"id": "b1", "name": "Acme"}],
             "category": {"slug": "sneakers", "title": "Sneakers", "path": "Shoes > Sneakers"},
             "offers": [offer(89.95)]},
    "KTL1": {"id": "KTL1", "title": "Electric Kettle 1.7L", "brands": [],
             "category": {"slug": "kettles", "title": "Electric Kettles", "path": "Home > Kitchen > Electric Kettles"},
             "offers": [offer(39.99)]},
    "LUX1": {"id": "LUX1", "title": "Designer Sneakers", "offers": [offer(350)]},
    "OOS1": {"id": "OOS1", "title": "Sold-out Sneakers", "offers": [offer(50, availability="OutOfStock")]},
    "EUR1": {"id": "EUR1", "title": "Euro Sneakers", "offers": [offer(70, currency="EUR")]},
}


class FakeChannel3:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("x-api-key") != "c3-test-key":
            return httpx.Response(401, json={"detail": "attach an x-api-key with your request"})
        if request.method == "POST" and request.url.path == "/v1/search":
            return httpx.Response(200, json={"products": list(PRODUCTS.values()), "next_page_token": None})
        if request.method == "GET" and request.url.path.startswith("/v1/products/"):
            product = PRODUCTS.get(request.url.path.rsplit("/", 1)[1])
            return httpx.Response(200, json=product) if product else httpx.Response(404, json={"detail": "nope"})
        return httpx.Response(404)

    def catalog(self) -> Channel3Catalog:
        return Channel3Catalog("c3-test-key", transport=httpx.MockTransport(self.handler))


@pytest.fixture
def shop(tmp_path):
    def build(with_catalog: bool = True):
        settings = Settings(db_path=str(Path(tempfile.mkdtemp(dir=tmp_path)) / "c.db"), paypal_client_id="",
                            paypal_client_secret="")
        db = Database(settings.db_path)
        db.init(reset=True)
        paypal = MagicMock(wraps=MockPayPalClient(), is_mock=True)
        wf = Workflow(db, settings, KeywordIntentExtractor(), paypal=paypal)
        wf.seed_demo()
        fake = FakeChannel3()
        wf.catalog = fake.catalog() if with_catalog else None
        return wf, paypal, build_mcp_server(wf, settings), fake
    return build


def call(server, name: str, args: dict):
    async def go():
        async with Client(server) as client:
            return await client.call_tool(name, args)
    return anyio.run(go)


def tool_names(server) -> set[str]:
    async def go():
        async with Client(server) as client:
            return {t.name for t in (await client.list_tools()).tools}
    return anyio.run(go)


def test_normalize_reads_both_documented_price_shapes_and_skips_what_cannot_be_bought():
    assert normalize(PRODUCTS["SNK1"], "USD").price == "89.95"
    assert normalize({"id": "A", "title": "A", "offers": [offer(12.5, key="amount")]}, "USD").price == "12.50"
    assert normalize(PRODUCTS["OOS1"], "USD") is None and normalize(PRODUCTS["EUR1"], "USD") is None
    assert normalize({"id": "Z", "title": "Z", "offers": [offer("NaN")]}, "USD") is None
    assert normalize({"title": "no id"}, "USD") is None


def test_find_product_is_offered_only_with_a_catalogue_and_returns_buyable_products_under_the_cap(shop):
    _, _, without, _ = shop(with_catalog=False)
    assert "find_product" not in tool_names(without)
    wf, _, server, fake = shop()
    assert "find_product" in tool_names(server)
    found = call(server, "find_product", {"query": "white leather sneakers", "max_price": 120}).structured_content
    titles = [p["title"] for p in found["products"]]
    assert titles == ["White Leather Sneakers", "Electric Kettle 1.7L"]  # 350 USD, sold out and EUR-only are gone
    sent = json.loads(fake.requests[-1].content)
    assert sent["filters"]["price"] == {"max_price": 120.0} and sent["limit"] == 5
    capped = json.loads((call(server, "find_product", {"query": "sneakers", "max_price": 10_000}) and
                         fake.requests[-1]).content)
    assert capped["filters"]["price"] == {"max_price": 200.0}  # the merchant's cap wins over the agent's


def test_a_catalogue_order_is_priced_and_named_by_the_server_not_the_agent(shop):
    wf, paypal, server, _ = shop()
    placed = call(server, "place_demo_order", {"buyer_name": "Maria", "agent_name": "Shop assistant",
                                               "product_id": "SNK1"}).structured_content
    case = wf.db.get_case(placed["order_id"])
    assert case["amount"] == "89.95" and case["product_sku"] == "C3-SNK1" and case["capture_id"]
    assert paypal.create_order_with_card.call_args.args[0] == "89.95"  # PayPal charged the catalogue price
    product = wf.db.get_product("C3-SNK1")
    assert product["name"] == "White Leather Sneakers" and product["category"] == "Shoes > Sneakers"
    chained = next(e["detail"] for e in wf.db.timeline(case["id"]) if e["title"].startswith("Order placed"))
    assert chained["product"]["price"] == "89.95" and "looked up by the server" in chained["product"]["source"]
    assert wf.db.verify_chain(case["id"])["ok"]


def test_refusals_cost_nothing(shop):
    wf, paypal, server, _ = shop()
    for product_id, words in (("LUX1", "limited to 200"), ("NOPE", "no such product"), ("../x", "must be an id"),
                              ("OOS1", "no in-stock offer")):
        result = call(server, "place_demo_order", {"buyer_name": "M", "agent_name": "a", "product_id": product_id})
        assert result.is_error and words in result.content[0].text, (product_id, result.content[0].text)
    assert paypal.create_order_with_card.call_count == 0
    _, pp2, without, _ = shop(with_catalog=False)
    refused = call(without, "place_demo_order", {"buyer_name": "M", "agent_name": "a", "product_id": "SNK1"})
    assert refused.is_error and "no product catalogue" in refused.content[0].text
    assert pp2.create_order_with_card.call_count == 0


def test_the_return_is_judged_on_the_real_product(shop):
    """The same words, two products: a kettle that stopped working is a possible hazard and goes to a person's
    safety review; sneakers that stopped working do not."""
    wf, paypal, server, _ = shop()
    outcomes = {}
    for product_id in ("KTL1", "SNK1"):
        order = call(server, "place_demo_order", {"buyer_name": "Maria", "agent_name": "a",
                                                  "product_id": product_id}).structured_content["order_id"]
        view = call(server, "request_return", {"order_id": order, "agent_name": "a", "on_behalf_of": "Maria",
                                               "message": "It stopped working after two days, I want a refund."})
        outcomes[product_id] = view.structured_content["status"]
    assert outcomes["KTL1"] == "NEEDS_HUMAN_SAFETY_REVIEW" and outcomes["SNK1"] != "NEEDS_HUMAN_SAFETY_REVIEW"
    assert paypal.refund_capture.call_count == 0


def test_an_eligible_catalogue_return_refunds_the_catalogue_price_after_a_person_approves(shop):
    wf, paypal, server, _ = shop()
    order = call(server, "place_demo_order", {"buyer_name": "Maria", "agent_name": "a",
                                              "product_id": "SNK1"}).structured_content["order_id"]
    view = call(server, "request_return", {"order_id": order, "agent_name": "a", "on_behalf_of": "Maria",
                                           "message": "The colour does not match the listing, I want a refund."})
    assert view.structured_content["status"] == "PENDING_APPROVAL"
    wf.approve(order)
    case = wf.db.get_case(order)
    assert case["status"] == "REFUND_COMPLETED" and Decimal(case["refund"]["amount"]["value"]) == Decimal("89.95")


def test_dashboard_and_inbox_show_the_catalogue(tmp_path):
    fake = FakeChannel3()
    settings = Settings(db_path=str(tmp_path / "d.db"), paypal_client_id="", paypal_client_secret="")
    app = create_app(settings, paypal=MagicMock(wraps=MockPayPalClient(), is_mock=True),
                     extractor=KeywordIntentExtractor(), catalog=fake.catalog(), agent_llm=MagicMock(model="m"))
    with TestClient(app) as client:
        wf = app.state.workflow
        page = client.get("/").text
        assert "<code>find_product</code>" in page and 'value="shop"' in page and "(Channel3)" in page
        assert "c3-test-key" not in page + client.get("/healthz").text  # the key is never rendered
        order = wf.agents.place_order("Maria", agent="a", product=fake.catalog().get("SNK1"))
        wf.agents.submit_request(order, "The colour does not match the listing, I want a refund.", agent="a",
                                 on_behalf_of="Maria")
        row = next(r for r in client.get("/api/inbox").json()["rows"] if r["id"] == order)
        assert row["item"] == "White Leather Sneakers" and row["amount"] == "89.95 USD"
        assert "White Leather Sneakers" in client.get("/inbox").text
    plain = create_app(Settings(db_path=str(tmp_path / "p.db"), paypal_client_id="", paypal_client_secret=""),
                       paypal=MagicMock(wraps=MockPayPalClient(), is_mock=True), extractor=KeywordIntentExtractor(),
                       agent_llm=MagicMock(model="m"))
    with TestClient(plain) as client:
        page = client.get("/").text
        assert "find_product" not in page and 'value="shop"' not in page
        assert client.post("/demo/live-agent", data={"goal": "shop"}).status_code == 404


def test_settings_read_the_catalogue_from_the_environment(monkeypatch):
    monkeypatch.setenv("CHANNEL3_API_KEY", "k")
    monkeypatch.setenv("TRADEOS_CATALOG_MAX_PRICE", "75.50")
    s = Settings.from_env()
    assert s.channel3_api_key == "k" and s.catalog_max_price == Decimal("75.50")


def test_catalogue_failures_are_reported_safely():
    def down(request):
        raise httpx.ConnectError("boom")
    catalog = Channel3Catalog("k", transport=httpx.MockTransport(down))
    with pytest.raises(Exception) as exc:
        catalog.search("sneakers")
    assert "could not be reached" in str(exc.value) and "boom" not in str(exc.value)
    unauthorised = Channel3Catalog("wrong", transport=httpx.MockTransport(FakeChannel3().handler))
    with pytest.raises(Exception, match="HTTP 401"):
        unauthorised.search("sneakers")
    with pytest.raises(Exception, match="describe the product"):
        unauthorised.search("   ")


def test_a_live_model_can_shop_buy_and_return_a_real_product(shop):
    """The 'shop' goal through the real agent loop: the (scripted fake) model searches, buys by product_id, asks for
    the return, and the order is the catalogue product at its catalogue price."""
    from app.llm_agent import GOALS, run_agent
    from tests.test_llm_agent import FakeModel, call as model_call, say

    wf, paypal, server, _ = shop()

    def shopper(messages, turn):
        tool = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        if turn == 0:
            return model_call("find_product", {"query": "white leather sneakers", "max_price": 120})
        if turn == 1:
            return model_call("place_demo_order", {"buyer_name": "Maria", "agent_name": "TradeOS live demo agent",
                                                   "product_id": tool[0]["products"][0]["product_id"]})
        if turn == 2:
            return model_call("request_return", {"order_id": tool[1]["order_id"], "agent_name": "x",
                                                 "on_behalf_of": "Maria",
                                                 "message": "They arrived too small; I would like a refund."})
        return say("Bought the Acme sneakers; the return now waits for a person at the shop.")
    run = anyio.run(run_agent, server, FakeModel(shopper).llm(), GOALS["shop"])
    assert [s["tool"] for s in run.steps] == ["find_product", "place_demo_order", "request_return"]
    case = wf.db.get_case(run.order_id)
    assert case["product_sku"] == "C3-SNK1" and case["amount"] == "89.95" and paypal.refund_capture.call_count == 0
    assert run.steps[0]["result"]["found"][0] == "White Leather Sneakers · 89.95 USD"  # what the transcript shows


def test_the_run_page_shows_what_the_search_found_escaped(tmp_path):
    from tests.test_llm_agent import FakeModel, call as model_call, say
    PRODUCTS["XSS1"] = {"id": "XSS1", "title": "White <b>Sneakers</b>", "offers": [offer(20)]}
    try:
        def searcher(messages, turn):
            return model_call("find_product", {"query": "sneakers"}) if turn == 0 else say("done")
        fake = FakeChannel3()
        app = create_app(Settings(db_path=str(tmp_path / "r.db"), paypal_client_id="", paypal_client_secret=""),
                         paypal=MagicMock(wraps=MockPayPalClient(), is_mock=True), extractor=KeywordIntentExtractor(),
                         catalog=fake.catalog(), agent_llm=FakeModel(searcher).llm())
        with TestClient(app) as client:
            r = client.post("/demo/live-agent", data={"goal": "shop"}, follow_redirects=False)
            run_id = r.headers["location"].rsplit("/", 1)[1]
            app.state.agent_runs.join(run_id, 20)
            page = client.get(f"/agent-runs/{run_id}").text
        assert "found 3: White Leather Sneakers · 89.95 USD" in page  # 350 USD, sold-out and EUR-only are filtered
        assert "White &lt;b&gt;Sneakers&lt;/b&gt; · 20.00 USD" in page and "<b>Sneakers</b>" not in page
    finally:
        PRODUCTS.pop("XSS1", None)
