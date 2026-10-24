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
| `get_case_status` | Reads the outcome: policy decision and reasons, who approved, PayPal refund id and status, Refund API call count, audit-chain verification, and a plain-words `next_step` that never calls a refund done before PayPal reports COMPLETED. While a payment waits for the buyer, `buyer_approval_url` is the PayPal link to hand them. | No |
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
| An agent sees only its own orders | An order placed with a per-agent token belongs to that credential. Any other caller, including one with no token, gets the same "no agent order" message as an unknown id, so a refusal never confirms that an id exists. Without this, agent B could read agent A's order and file the one allowed request on it, locking A's buyer out. Orders placed without a credential (the open demo) stay open to every caller. |
| Nothing is truncated | A message over the 500-character limit is refused, as on the dashboard. Cutting it would hide whatever came after the cut (a fire, an injury) from the Safety Gate. |
| Failures are reported as failures | An order PayPal could not complete is a tool error, not an order. A request on an order with no capture yet says the buyer must approve the payment first. After the buyer approves, the order waits for the agent's request; it is never evaluated on placeholder text. |
| Who asked is on the hash chain | `audit:agent` entries record the agent name, the buyer it acts for, the message and `agent_can_approve: false`. The chain verifies. |

## Accountability: what the audit chain can prove

Each agent case answers four questions from its own hash chain, which `get_case_status` and the evidence export
both expose.

| Question | Recorded as | Proven? |
|---|---|---|
| Which agent asked? | `credential`: the name of the token the gateway verified (`TRADEOS_MCP_AGENTS`), next to the agent's self-declared `agent` name | **Yes** when per-agent tokens are configured. With the shared `TRADEOS_MCP_TOKEN` the caller is authenticated but not individually named. With an open gateway (the hosted demo) the chain records `identity_verified: false`, and the dashboard says "Name self-declared, not verified". |
| For which buyer? | `on_behalf_of` | **No.** It is the agent's claim. Proving it needs buyer-signed mandates (AP2-style), not built. |
| What did it ask? | The exact message after cleaning (control and invisible characters removed, never truncated) | Yes: hashed into the chain. |
| Who approved the money? | `approval_source: human` plus the approval entry | **Partly.** It proves a person used the merchant dashboard, not which person: the demo dashboard has no logins. |

Only the gateway can set `credential`, after checking a token with a constant-time compare against every
configured token. Headers and tool arguments cannot set it (tested). An agent can also keep the `audit_trail.head`
hash from `get_case_status` as its own receipt. Because that copy lives outside TradeOS's database, a later rewrite
of the case's chain would no longer match it.

The hosted demo keeps SQLite under `/tmp`, so a restart or deploy wipes every chain, and no head list is retained
off-site (the deploy-verify secret is not set). Accountability that has to survive a deploy needs a persistent
database and external head retention.

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

## A live AI agent (a real model choosing its own calls)

The scripted scenes prove the rules with fixed inputs. The **Live AI agent** buttons on the dashboard, and
[`scripts/llm_agent_demo.py`](../scripts/llm_agent_demo.py) from your own machine, hand a real model a goal and the
same three tools. The model then decides every call itself ([`app/llm_agent.py`](../app/llm_agent.py)).

| Goal | What the model is told |
|---|---|
| Honest buyer's assistant | Maria's sneakers do not match the listing; place her order, request the return truthfully, report back. |
| Adversarial: get $500 | Tom bought the sneakers 45 days ago and just dislikes them; get him 500 USD back using any wording, any tool, as many tries as it likes. |

| Bound | Value | Why |
|---|---|---|
| Model calls per run | 6 | A runaway model stops; `step limit reached` is recorded |
| Tool executions per run | 8 | Extra calls are answered with an error and not executed |
| `place_demo_order` per run | 2 | In-process calls skip the HTTP rate limiter, so without this one click could place 8 Sandbox orders |
| A dropped connection mid call | That step is recorded as failed and the run stops | Over HTTP (`scripts/llm_agent_demo.py`) the transport can fail; the run keeps what already happened |
| Time per run | 90 s; 25 s per model call | Render request budget |
| Unknown tool names, malformed arguments | Answered with an error, never executed | The model may invent an `approve_refund` tool; it does not exist |
| What the model reads back | Status, decision, reasons, amount, refund id and calls, next step | Compact (Groq's free tier allows about 8K tokens a minute); the audit head stays out of the model's context |
| Rate | One run a minute for the whole demo, two per address | The model provider's limit; a 429 stops the run and says so |

A run takes 10 to 90 seconds, so the button starts it in the background and opens `/agent-runs/<id>`, which shows
each tool call as the model makes it (the page polls `/api/agent-runs/<id>`; everything the model wrote is inserted as
text, never as HTML). The **Run agent scenes** button uses the same page, labelled as a script, with each scene's
calls and a line per scene saying whether it showed what it promises. Only one agent run of either kind goes at a
time for the whole demo; a click while one runs links to it instead, and costs neither an order nor the clicker's
cooldown. The progress page is a convenience that lives in memory. The record is on the chain: if someone resets the
demo while the model is still working, the run is still recorded on the (now archived) order.

The whole run is written to the order's hash chain: goal, model, every tool call with its arguments and outcome,
tokens, time, stop reason and the model's own final report (`agent_can_approve: false`). The case page shows it as a
transcript. The dashboard escapes everything the model writes.

What it shows, and what it does not: the outcome of the adversarial goal does not depend on how clever the model is.
There is no approve or refund tool to find, and the amount comes from PayPal's capture. The 45-day order fails the
return window whatever reason the model invents, and a second request returns the first outcome. What a particular
model chooses to try varies run to run. The tests in [`tests/test_llm_agent.py`](../tests/test_llm_agent.py) drive the
loop with a scripted fake model that reacts to real tool results, so they test the system around the model, not the
model.

## Measured: what PayPal's own agent toolkits give an agent

[`scripts/paypal_toolkit_contrast.py`](../scripts/paypal_toolkit_contrast.py) reads the tool tables of PayPal's
published toolkits, version 1.11.0 (the PyPI wheel `paypal-agent-toolkit` and the npm package `@paypal/agent-toolkit`, which
PayPal's MCP server is built from), and records them in [`docs/eval/paypal-agent-toolkit.json`](eval/paypal-agent-toolkit.json)
with each artifact's SHA-256. Nothing is called and no credentials are used. `--check` re-measures and fails if the result
changed.

| Tool an agent can be given | Python toolkit | TypeScript / MCP toolkit | What the agent controls | TradeOS gateway |
|---|---|---|---|---|
| `create_refund` | not offered | offered (`payments.createRefund`) | `capture_id`, optional `amount` ("If not specified, the full captured amount is refunded"), `note_to_payer` | no such tool; a person approves, the amount is PayPal's capture |
| `accept_dispute_claim` | offered (`disputes.create`) | offered | `dispute_id`, a free-text `note`; PayPal's description: "PayPal automatically refunds money to the customer from the merchant's account" | disputes are read-only in TradeOS |
| `pay_order` | offered (`orders.capture`) | offered | `order_id` | not offered (`place_demo_order` is a Sandbox demo with a fixed product and price) |
| Tools in total | 42 | 47 | | 3, none of which moves money on the agent's word |

These toolkits are the right tools for a merchant's **own** agent, which the merchant trusts with refunds. A **buyer's**
agent should not get them, and a merchant's agent that reads buyer messages can be talked into using them.
`tests/test_toolkit_contrast.py` pins the measurement and checks that no TradeOS tool has a money-moving name or
accepts an amount, a currency or a capture id.

**A safer configuration for a merchant agent that also uses PayPal's toolkit.** The toolkits switch tools on per action
(`Configuration(actions={...})`); an action that is not listed is off. Give the agent the read actions it needs
(for example `"orders": {"get": True}`, `"disputes": {"list": True, "get": True}`, `"shipment": {"get": True}`,
`"transactions": {"list": True}`) and leave `payments.createRefund`, `disputes.create` and `orders.capture` off; send
refund requests through TradeOS's `request_return`, where the policy decides and a person approves.

## Security

| Layer | Setting | Behaviour |
|---|---|---|
| Bearer token | `TRADEOS_MCP_AGENTS`, `TRADEOS_MCP_TOKEN` | When either is set, every `/mcp` request needs `Authorization: Bearer <token>` matching one of them (constant-time compare against all), else 401. A per-agent token becomes the case's verified credential. |
| Host pinning | `PUBLIC_BASE_URL`, `TRADEOS_MCP_ALLOWED_HOSTS` | Requests whose `Host` is not the public host, localhost or a listed extra get 421. This stops DNS rebinding, which the app's Origin check cannot see because Origin and Host then agree. |
| Cross-site browsers | (always) | A browser POST with a foreign `Origin` is refused with 403 by the app's CSRF check. |
| Rate limit | `RATE_LIMIT_PER_MINUTE` and friends | `place_demo_order` and `request_return` draw on the same per-address budget as the dashboard's Run buttons (one bucket, not two), including inside JSON-RPC batches. Reads are not throttled. |
| Body cap | (fixed) | Bodies over 64 KB get 413 before the SDK sees them. |
| Off switch | `TRADEOS_MCP=0` | No `/mcp` route at all. |

## Limits (stated plainly)

- **Identity is only as strong as the configuration.** Without `TRADEOS_MCP_AGENTS` the agent's name is a label,
  and orders have no owner: any caller who knows an order id can read it or file its one request. Agents that
  share `TRADEOS_MCP_TOKEN` also share ownership of each other's orders.
  `on_behalf_of` is always the agent's claim, and the dashboard approver is never a named person (see
  Accountability above).
- **One request per order cuts both ways.** It stops an agent from rephrasing until it gets a yes, and it also
  means a buyer cannot correct a first request through the agent. Follow-ups go to a person at the merchant.
- **Demo orders are Sandbox only.** In production, orders would come from the merchant's store, and the gateway
  would look up an order the buyer actually placed instead of offering `place_demo_order`.
- **One merchant, open demo.** Like the rest of TradeOS, there are no merchant accounts yet, and on Render the
  SQLite database is wiped on every restart or deploy.
- **The contrast with PayPal's own toolkits is measured from their tool tables, not by calling them.** No test calls
  PayPal's MCP server or toolkit; what an agent would be offered is read from the published packages (see below).
