# Devpost submission draft — TradeOS

**Status:** superseded for form paste by [`devpost-submission-final.md`](devpost-submission-final.md). Kept as a
working draft that mirrors the verified tip. Candidate / hosted tip: **`49261e5`**
(`49261e5f46dd2fb879fc9b24513ae65cb9328645`) at https://tradeos-s33z.onrender.com.

## Project title and one-line pitch

**TradeOS — governed returns for agentic commerce**

**Buyer agents request. Merchants approve. PayPal confirms.**

## What it does

A small cross-border physical-goods merchant receives a return request in a customer's words or through a buyer's AI
agent. TradeOS uses a language model only to extract intent and summarize the message. Deterministic code checks the
return policy against PayPal's captured amount, currency and date. Dangerous-product reports go to a human before any
refund or supplier task. Returns and size-exchanges are routed differently. Eligible agent-originated refunds always
wait for a person — even if auto-approval is on (that opt-in is for ordinary customer requests only; it is off on the
hosted demo). Rejected requests make zero Refund API calls. When a person approves, TradeOS calls PayPal's Sandbox Refund
API, records the refund ID, verifies PayPal's signed webhook, and reads the refund again from PayPal. The merchant sees
the request, next action and evidence in one returns inbox.

The agent connects through **TradeOS's own restricted `/mcp` gateway** (not the official PayPal MCP). It offers a
Sandbox demo purchase, a return request and a status read; there is no approve or refund tool. A read-only product
search is available when Channel3 is configured. A toolkit-contrast script only **reads** the published PayPal
agent-toolkit tool list for comparison. The repeatable demo uses a **scripted MCP client**. A separate live-model run
shows a model choosing its own tools; its choices vary.

## Why it is different

Agentic commerce helps a buyer find and purchase a product. Returns create a different trust boundary: the buyer's
agent can describe a problem, but the merchant controls whether money moves. TradeOS puts that boundary in code. The
model interprets language; it does not set refund amounts, decide eligibility or approve a payment. PayPal's capture
and refund responses provide the monetary source of truth. This is not a claim to be first or unique.

## Tools actually used

| Tool | Role in TradeOS |
| --- | --- |
| PayPal Developer Platform (Sandbox) | Orders / captures; capture lookup; Payments v2 refunds after approval; signed webhook + GET reconciliation. |
| Groq-hosted `openai/gpt-oss-20b` | Limited semantic role: intent, reason, action, English merchant summary. |
| AG Grid Community | Interactive returns inbox. |
| Channel3 | Optional read-only product discovery for agents. |
| Render | Hosts the working Sandbox demo. |

No APIMatic, Postman-run, or Render Workflows claims.

## Evidence (tip `49261e5`, hosted)

- Hosted `sandbox_verify` **31/31**; AI e2e **11/11**; signed webhooks **3/3 VERIFIED**; GET reconciliation **3/3**;
  audits **10/10**; UI **10/10**; policy matrix **582/582** (deterministic); malformed Origin/Referer → **403** (58/58).
  Differs from `1d5ab96` only in copy/templates. Pytest tip count in [`submission-evidence.md`](submission-evidence.md).
- LLM eval (52 author-written messages): exact **41/52** vs keyword **17/52**; request-check **52/52** on this small
  set (not general accuracy).
- Audit chain is **tamper-evident**, not immutable. Sandbox only; shared ephemeral demo; opt-in auto-approval off on
  hosted (agent refunds still need a merchant even if it is turned on).

**YouTube URL:** _TBD — placeholder._

## Links

- Demo: `https://tradeos-s33z.onrender.com`
- Source: `https://github.com/Fu93/tradeos` (MIT [`LICENSE`](../LICENSE))
- Final English paste: [`devpost-submission-final.md`](devpost-submission-final.md)
