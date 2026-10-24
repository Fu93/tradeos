# Agent gateway: AI agents can request a return, never approve one

PayPal's own MCP server lets an AI agent issue refunds directly. That is the right tool for a merchant's own agent,
and the wrong one for an agent that acts for a **buyer**: nothing between the agent and the Refund API checks the
merchant's return policy, notices a prompt injection, or asks a person.

TradeOS exposes a second door for that kind of agent. It is an MCP server at `/mcp` with three tools, and it has no
approve, decline or refund tool. A request from an agent runs through the same loop as a dashboard case. Every
agent-originated case then waits for a person at the merchant, even with `AUTO_ENABLED` on.

## What an agent can and cannot do

| Tool | What it does | Moves money? |
|---|---|---|
| `place_demo_order` | Sandbox demo only: buys the demo sneakers (49.99 USD) with a PayPal Sandbox test card, so the buyer has an order to return. `purchased_days_ago` seeds an older purchase date (labelled demo data). Off with `TRADEOS_AGENT_DEMO_ORDERS=0`. | A Sandbox capture, like the dashboard's Run buttons |
| `request_return` | Asks for a return (refund) or a size exchange on that order, with the buyer's words. One request per order. | No |
| `get_case_status` | Reads the outcome: policy decision and reasons, who approved, PayPal refund id and status, Refund API call count, audit-chain verification. | No |
| approve / decline / refund | **Not offered.** Only a person on the dashboard (or the merchant's own autonomy policy, for non-agent cases) approves. | — |

```mermaid
flowchart LR
  AG["Buyer's AI agent"] -- "request_return (MCP)" --> REQ["Agent request<br/>on the hash chain"]
  REQ --> AI["AI intent extraction<br/>language only"]
  AI --> SG{"Safety Gate<br/>(code)"}
  SG -- "harm" --> HS["Human safety review"]
  SG -- ok --> PP[("PayPal GET capture<br/>amount, status, date")]
  PP --> POL{"Policy engine<br/>(pure Python)"}
  POL -- REJECTED --> STOP["Stop: Refund API not called"]
  POL -- ELIGIBLE --> HUM{"A person approves<br/>(always, for agents)"}
  HUM --> G["Hard guard:<br/>ELIGIBLE + chained APPROVED"]
  G --> RF["PayPal Refund API"]
  AG -. "get_case_status" .-> AUD[("Outcome + audit trail")]
```

## What is guaranteed, and where it is tested

All of the following are asserted in [`tests/test_agent_gateway.py`](../tests/test_agent_gateway.py). The suite
was also mutation-checked: removing each defence below makes at least one test fail.

| Property | How |
|---|---|
| No tool can approve, decline or refund | The server registers exactly three tools; the test asserts the set and that no name contains approve, decline, refund or capture. |
| Every agent request waits for a person | `autonomy.decide_detailed(..., agent_originated=True)` returns HUMAN before any limit is read. Asserted with `AUTO_ENABLED=1` and the amount inside the limit, for refunds and exchanges. |
| The agent cannot set the amount | The refund is PayPal's whole capture (no `amount` sent), and the policy reads amount, currency, status and date from `GET /v2/payments/captures/{id}`. A message claiming "500 USD" changes nothing. |
| Prompt injection, a late order and a safety report end with Refund API calls = 0 | Same policy, injection heuristic and Safety Gate as the dashboard; `approve()` is refused afterwards too. |
| No re-rolls | Only an `AGENT_ORDERED` case is evaluated. A second `request_return` on the same order returns the first outcome without another LLM call or PayPal read. |
| An agent sees only gateway orders | Any other id, including a real dashboard case, is "not found". Archived orders too. |
| Who asked is on the hash chain | `audit:agent` entries record the agent name, the buyer it acts for, the message and `agent_can_approve: false`. The chain verifies. |

## Connecting an agent

Any MCP client that speaks Streamable HTTP can point at `https://<your-host>/mcp`. The endpoint is stateless and
answers JSON, so it works behind Render's proxy without sticky sessions.

For a client that launches a local process instead, the same tools are served over stdio against your local
database and `.env`:

```json
{
  "mcpServers": {
    "tradeos": {
      "command": "python",
      "args": ["-m", "app.agent_gateway"],
      "cwd": "/path/to/tradeos"
    }
  }
}
```

## Demo

[`scripts/agent_demo.py`](../scripts/agent_demo.py) plays the buyer's agent against a running instance over HTTP
and asserts four scenes: an honest return that waits for a person, a prompt injection, a late order, and a re-roll.
It prints the dashboard link where the merchant approves scene 1.

```bash
python scripts/agent_demo.py https://<your-host>                     # or http://localhost:8000
python scripts/agent_demo.py https://<your-host> --wait-approval 120 # then approve on the dashboard
```

Each scene creates a Sandbox order and runs the LLM, so the script shares the server's per-address run limit
(5 per minute by default). It waits and retries on HTTP 429, so a full run takes about a minute.

## Security

| Layer | Setting | Behaviour |
|---|---|---|
| Bearer token | `TRADEOS_MCP_TOKEN` | When set, every `/mcp` request needs `Authorization: Bearer <token>` (constant-time compare), else 401. |
| Host pinning | `PUBLIC_BASE_URL`, `TRADEOS_MCP_ALLOWED_HOSTS` | Requests whose `Host` is not the public host, localhost or a listed extra get 421. This stops DNS rebinding, which the app's Origin check cannot see because Origin and Host then agree. |
| Cross-site browsers | (always) | A browser POST with a foreign `Origin` is refused with 403 by the app's CSRF check. |
| Rate limit | `RATE_LIMIT_PER_MINUTE` and friends | `place_demo_order` and `request_return` share the dashboard's run budget per address, including inside JSON-RPC batches. Reads are not throttled. |
| Body cap | (fixed) | Bodies over 64 KB get 413 before the SDK sees them. |
| Off switch | `TRADEOS_MCP=0` | No `/mcp` route at all. |

## Limits (stated plainly)

- **The agent's name is a label, not an identity.** `agent_name` and `on_behalf_of` are recorded, not verified.
  The bearer token says a caller may use the gateway; it does not say which buyer they speak for. Verifying the
  buyer's intent (for example with signed AP2-style mandates) is not built.
- **Demo orders are Sandbox only.** In production, orders would come from the merchant's store, and the gateway
  would look up an order the buyer actually placed instead of offering `place_demo_order`.
- **One merchant, open demo.** Like the rest of TradeOS, there are no merchant accounts yet, and on Render the
  SQLite database is wiped on every restart or deploy.
- **The contrast with PayPal's own MCP refund tool is described, not measured here.** No test in this repository
  calls PayPal's MCP server.
