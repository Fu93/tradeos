# Devpost submission draft — TradeOS

**Status:** local draft only. Do not submit this text until the video URL, deployed commit and every claim have been
checked against the final build. Candidate tip: PR #100 head (see `git rev-parse HEAD` on
`cursor/pre-submission-hardening-fixes-e206`). The public demo may still serve an older commit (`dc2c6b5`) until an
authorized redeploy — treat hosted verify as **pending**.

## Project title and one-line pitch

**TradeOS — the returns layer for agentic commerce**

Buyer's AI agents can request a return. They cannot approve a merchant's refund. TradeOS reads the request, applies
the merchant's rules, asks a person to approve money, and records what PayPal actually did.

## What it does

A small merchant can receive a return request in a customer's own words or through a buyer's AI agent. TradeOS uses
a language model to extract the intent and summarize the message. Deterministic code checks the return policy against
PayPal's captured amount, currency and date. Eligible agent-originated refunds always wait for a person, even if the
merchant has enabled automation for other cases. Rejected requests make zero Refund API calls. When a person approves,
TradeOS calls PayPal's Sandbox Refund API, records the refund ID, verifies PayPal's signed webhook, and reads the
refund again from PayPal. The merchant sees the request, next action and evidence in one returns inbox.

The agent connects through an MCP gateway that offers a Sandbox demo purchase, a return request and a status read;
there is no approve or refund tool. A read-only product search is available when the Channel3 catalogue is configured.
The repeatable demo uses a **scripted MCP client**. A separate live-model run shows a model choosing its own tools;
its choices vary, and the two demonstrations must not be described as the same thing.

## Why it is different

Agentic commerce helps a buyer find and purchase a product. Returns create a different trust boundary: the buyer's
agent can describe a problem, but the merchant controls whether money moves. TradeOS puts that boundary in code.
The model interprets language; it does not set refund amounts, decide eligibility or approve a payment. PayPal's
capture and refund responses provide the monetary source of truth.

## Tools and how they are used

| Tool | Role in TradeOS |
| --- | --- |
| PayPal Developer Platform (Sandbox) | Orders and captures for the demo; capture lookup for policy facts; Refund API after approval; signed webhook and a later GET to confirm the outcome. |
| Groq-hosted `openai/gpt-oss-20b` (current demo's OpenAI-compatible LLM) | Extracts intent, reason, requested action and an English merchant summary from free text; a separate optional live agent chooses MCP calls. Recheck the provider and model on the final deployment. |
| AG Grid Community | Interactive returns inbox with triage filters, sorting, live refresh and CSV export. |
| Channel3 | Optional read-only product discovery; the server fetches product details again by ID before a Sandbox purchase. |
| Render | Hosts the working PayPal Sandbox demo. |

## Evidence and honest limits

The public demo runs on PayPal **Sandbox**, so no real money moves. On 5 Nov 2026, the published commit
`dc2c6b5cd40e19c2f859d54a71f06b593c350864` passed all 31 default checks in `scripts/sandbox_verify.py`, including
a completed refund after human approval, a verified signed webhook, a matching PayPal re-read and zero refund calls
for a rejected case. A **local Sandbox run** of tip `e1c510b` (8 Nov 2026, isolated verification machine) reported 62 pass / 0 fail /
6 webhook SKIP (no public receiver), ERROR-retry 4/4 and UNKNOWN recovery 2/2 — that is not a hosted-demo claim.
**Replace this paragraph with hosted evidence for the final deployed commit** after redeploy.

This is a one-merchant prototype. The public demo uses Sandbox orders created by the agent or merchant before the
return request. A separate private profile can verify and import a pre-existing PayPal Sandbox capture, but it does
not verify a store order, product or buyer and is not evidence that arbitrary merchant orders are supported.
Supplier replies are mock data, disputes are read-only, and the
illustrative labour saving is an assumption rather than a measured merchant outcome. Link any independent user-study
results only after they exist. Optional `scripts/sandbox_verify.py --ai-e2e-only` exercises the live LLM intent path
(one English free-text return; prints the measured `llm_chat_completions` count) when the target has `LLM_API_KEY` /
`LLM_BASE_URL` / `LLM_MODEL`.

## Links to complete before submitting

- Public YouTube video under three minutes: **MISSING — do not submit with this placeholder**.
- Final live demo URL: `https://tradeos-s33z.onrender.com` (verify it serves the final commit — **pending redeploy**).
- Public source and setup instructions: `https://github.com/Fu93/tradeos` (verify its main branch matches the demo).
- Final commit SHA and dated Sandbox verification output: **replace after the final authorized deployment**.
- Exact deployed AI provider/model and any sponsor tools actually enabled: the current demo case displays `llm:openai/gpt-oss-20b` and `/healthz` reports a product catalogue; **reverify the final deployment**.

The [official rules](https://paypalaihackathon.devpost.com/rules) require English submission materials, a functioning
demo accessible to judges through the judging period, a public open-source repository with a visible license, and a
public YouTube video shorter than three minutes. The final submission should keep its text, video and live build on
the same version.
