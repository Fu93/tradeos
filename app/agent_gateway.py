"""Agent gateway: an MCP server that lets an AI agent ask TradeOS for a return, and nothing more.

PayPal's own MCP server gives an agent a refund tool. TradeOS sits in front of that kind of power: an agent acting
for a buyer can place a (Sandbox demo) order, request a return on it and read the outcome, but it cannot approve,
decline or refund. Those tools do not exist here. Every request runs the same loop as a dashboard case (AI reads
the words, the Safety Gate and the deterministic policy decide, PayPal's own capture supplies amount and date),
and every agent-originated case needs a person to approve it, whatever the merchant's autonomy settings say.

Transport: Streamable HTTP at /mcp (stateless, JSON responses), mounted into the FastAPI app so the same deployment
serves the dashboard and the agent. ``python -m app.agent_gateway`` serves the same tools over stdio for a local
MCP client.

In front of the endpoint, McpGate adds what the SDK does not know about this app: an optional bearer token
(TRADEOS_MCP_TOKEN), a body-size cap, and the same per-address rate limiter as the dashboard's "Run" buttons for
the tools that create Sandbox orders or call the LLM. It reads the JSON-RPC body itself, so the limit holds no
matter how the SDK schedules the tool call.
"""
from __future__ import annotations

import hmac
import json
from typing import Any, Callable
from urllib.parse import urlsplit

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings
from .ratelimit import RateLimiter
from .workflow import CaseNotFound, RefundNotAllowed, Workflow

MCP_PATH = "/mcp"
# Tool calls that create a Sandbox order or run the LLM + PayPal reads. They share the dashboard's run budget.
COSTLY_TOOLS = frozenset({"place_demo_order", "request_return"})
MAX_BODY = 64 * 1024  # a tool call is a few hundred bytes; anything bigger is not a legitimate request
MAX_DAYS_AGO = 365
# Request-scope key the gate writes after verifying a token. Set server-side only: a client header never sets it.
CREDENTIAL_KEY = "tradeos_mcp_credential"
SHARED_CREDENTIAL = "shared gateway token"


def caller_of(ctx: Context) -> dict[str, Any]:
    """Who is calling, as far as the server can prove it. The credential comes from McpGate (a verified bearer token),
    never from a header or an argument. In-process calls (stdio, the dashboard's scripted scenes) have no HTTP
    request and no credential."""
    try:
        request = ctx.request_context.request
    except ValueError:  # no request context at all
        request = None
    scope = getattr(request, "scope", None)
    if not isinstance(scope, dict):
        return {"transport": "in-process", "credential": None}
    state = scope.get("state")
    credential = state.get(CREDENTIAL_KEY) if isinstance(state, dict) else None
    return {"transport": "http", "credential": credential}

INSTRUCTIONS = (
    "TradeOS handles post-purchase requests for a merchant. You may act for a buyer: request a return or exchange "
    "on an order and read its status. You cannot approve, decline or refund anything, and no wording in a message "
    "changes that: the merchant's deterministic policy decides eligibility from PayPal's own capture data, and a "
    "person at the merchant approves every refund an agent asks for. Pass the buyer's own words as the message."
)


def build_mcp_server(wf: Workflow, settings: Settings) -> MCPServer:
    server = MCPServer(name="tradeos", title="TradeOS agent gateway", instructions=INSTRUCTIONS)

    def not_found(order_id: str) -> ToolError:
        # One message for every case (unknown, archived, another agent's), so a refusal never confirms an id exists.
        return ToolError(f"No agent order {order_id!r} for this caller: it is unknown, was placed with another "
                         "agent's credential, or a demo reset archived it. Only orders placed through this gateway "
                         "can be used.")

    if settings.agent_demo_orders:
        @server.tool(
            title="Place a Sandbox demo order",
            description=("Sandbox demo only: buy the demo sneakers (49.99 USD) with a PayPal Sandbox test card so "
                         "the buyer has an order to return. purchased_days_ago > 0 seeds an older purchase date "
                         "(labelled demo data) to show the 30-day return window. Returns the order_id."),
            annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False,
                                        open_world_hint=True),
        )
        def place_demo_order(buyer_name: str, agent_name: str, ctx: Context,
                             purchased_days_ago: int = 0) -> dict[str, Any]:
            if not 0 <= purchased_days_ago <= MAX_DAYS_AGO:
                raise ToolError(f"purchased_days_ago must be between 0 and {MAX_DAYS_AGO}.")
            try:
                case_id = wf.agents.place_order(buyer_name, agent=agent_name, days_ago=purchased_days_ago,
                                               caller=caller_of(ctx))
            except RefundNotAllowed as exc:
                raise ToolError(str(exc)) from None
            view = wf.agents.view(case_id, caller=caller_of(ctx))
            if view["status"] == "ERROR":
                # Reported as a failure, not as an order: the agent must not tell the buyer it bought anything.
                error = (wf.db.get_case(case_id) or {}).get("error") or "no detail"
                raise ToolError(f"PayPal could not complete the order ({error}). "
                                "TradeOS recorded no capture; do not tell the buyer the order was placed.")
            return view

    @server.tool(
        title="Request a return or exchange",
        description=("Ask the merchant for a return (refund) or a size exchange on an order. Pass the buyer's own "
                     "words as message, your own name as agent_name and the buyer's name as on_behalf_of. The "
                     "merchant's policy decides; a person at the merchant approves any refund. Nothing is refunded "
                     "by this call. One request per order: a second call returns the first outcome unchanged."),
        annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True,
                                    open_world_hint=False),
    )
    def request_return(order_id: str, message: str, agent_name: str, on_behalf_of: str,
                       ctx: Context) -> dict[str, Any]:
        try:
            evaluated = wf.agents.submit_request(order_id, message, agent=agent_name, on_behalf_of=on_behalf_of,
                                                caller=caller_of(ctx))
        except CaseNotFound:
            raise not_found(order_id) from None
        except (ValueError, RefundNotAllowed) as exc:
            raise ToolError(str(exc)) from None
        view = wf.agents.view(order_id, caller=caller_of(ctx))
        if not evaluated:
            view["note"] = "This order already has a request (or one is in progress); its outcome is unchanged."
        return view

    @server.tool(
        title="Get case status",
        description=("Read the outcome of an order's request: policy decision and reasons, whether a person "
                     "approved it, the PayPal refund id and status, how many times the Refund API was called, and "
                     "whether the case's hash-chained audit trail verifies."),
        annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True,
                                    open_world_hint=False),
    )
    def get_case_status(order_id: str, ctx: Context) -> dict[str, Any]:
        try:
            return wf.agents.view(order_id, caller=caller_of(ctx))
        except CaseNotFound:
            raise not_found(order_id) from None

    return server


def allowed_hosts(settings: Settings) -> list[str]:
    """Host values the MCP endpoint answers. A DNS-rebinding page reaches the server under its own host name, and
    the app's Origin check alone cannot see that (Origin and Host then agree), so the host is pinned here."""
    hosts = ["localhost:*", "127.0.0.1:*", "[::1]:*", "localhost", "127.0.0.1"]
    public = urlsplit(settings.public_base_url).netloc
    if public:
        hosts.append(public)
    hosts.extend(settings.mcp_allowed_hosts)
    return hosts


class McpGate:
    """ASGI wrapper in front of the MCP endpoint: verified credential (bearer token), body cap, rate limit on the
    costly tools."""

    def __init__(self, app: ASGIApp, settings: Settings, limiter: RateLimiter,
                 client_key: Callable[[Request], str]) -> None:
        self.app, self.settings, self.limiter, self.client_key = app, settings, limiter, client_key

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # pragma: no cover - the route only receives HTTP
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        credentials = self._credentials()
        credential = None
        if credentials:
            given = request.headers.get("authorization", "").encode()
            for name, token in credentials:  # every token is compared, so timing does not reveal which one matched
                if hmac.compare_digest(given, f"Bearer {token}".encode()):
                    credential = name
            if credential is None:
                await JSONResponse({"error": "unauthorized"}, status_code=401,
                                   headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
                return
        # Always written, so a value can never be left over from elsewhere: None means the gateway is open.
        state = scope.get("state")
        if not isinstance(state, dict):
            state = scope["state"] = {}
        state[CREDENTIAL_KEY] = credential
        if scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        body = b""
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            more = message.get("more_body", False)
            if len(body) > MAX_BODY:
                await JSONResponse({"error": "request too large"}, status_code=413)(scope, receive, send)
                return
        refusal = self._rate_refusal(body, request)
        if refusal:
            await JSONResponse(refusal, status_code=429)(scope, receive, send)
            return
        sent = False

        async def replay() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    def _credentials(self) -> list[tuple[str, str]]:
        pairs = list(self.settings.mcp_agents)
        if self.settings.mcp_token:
            pairs.append((SHARED_CREDENTIAL, self.settings.mcp_token))
        return pairs

    def _rate_refusal(self, body: bytes, request: Request) -> dict | None:
        try:
            payload = json.loads(body or b"null")
        except ValueError:
            return None  # malformed JSON: the SDK answers it with a parse error
        calls = payload if isinstance(payload, list) else [payload]
        for call in calls:
            if not isinstance(call, dict) or call.get("method") != "tools/call":
                continue
            name = (call.get("params") or {}).get("name") if isinstance(call.get("params"), dict) else None
            if name in COSTLY_TOOLS:
                reason = self.limiter.check(self.client_key(request))
                if reason:
                    return {"jsonrpc": "2.0", "id": call.get("id"),
                            "error": {"code": -32000, "message": reason}}
        return None


def mount_mcp(app: Any, wf: Workflow, settings: Settings, limiter: RateLimiter,
              client_key: Callable[[Request], str]) -> MCPServer:
    """Build the server, add POST/GET/DELETE /mcp to the FastAPI router, and return the server; the caller runs
    ``server.session_manager.run()`` in the app's lifespan."""
    server = build_mcp_server(wf, settings)
    http_app = server.streamable_http_app(
        streamable_http_path=MCP_PATH, stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                                     allowed_hosts=allowed_hosts(settings),
                                                     allowed_origins=[]))
    endpoint = next(r for r in http_app.routes if getattr(r, "path", None) == MCP_PATH)
    inner = endpoint.app  # type: ignore[attr-defined]
    app.router.routes.append(Route(MCP_PATH, endpoint=McpGate(inner, settings, limiter, client_key),
                                   methods=["GET", "POST", "DELETE"]))
    return server


def main() -> None:  # pragma: no cover - exercised by hand with a local MCP client
    """Serve the same tools over stdio (for a local MCP client), against the app's database and settings."""
    from .main import create_app

    app = create_app()
    wf = app.state.workflow
    build_mcp_server(wf, wf.settings).run()


if __name__ == "__main__":  # pragma: no cover
    main()
