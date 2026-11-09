# TradeOS — Devpost submission (English, final paste)

**Verified hosted build (8 Nov 2026):** `49261e5f46dd2fb879fc9b24513ae65cb9328645` · **Demo:** https://tradeos-s33z.onrender.com  
**License:** MIT · **YouTube:** _TBD — placeholder; do not submit until a public video under 3:00 exists_

---

## Title

TradeOS — governed returns for agentic commerce

## Tagline

Buyer agents request. Merchants approve. PayPal confirms.

## Inspiration

*(Illustrative scenario — not a measured merchant case study.)* A small cross-border shop sells physical goods on
PayPal. Buyers' AI assistants can already find products and check out. When those same assistants ask for a return —
or get talked into “refund me $500” — the merchant still has to decide. Today that usually means one person reading
mail, looking up the capture, and clicking refund in PayPal. TradeOS explores a governed middle layer: AI for
language, deterministic rules for policy, a human for money, and PayPal for confirmation.

## What it does

TradeOS is a returns inbox for small cross-border physical-goods merchants.

- A customer message or a **buyer agent** request enters one queue.
- A language model extracts structured intent only (it never sets amounts or approvals).
- Deterministic Python policy checks PayPal's capture facts (amount, currency, window, product).
- Dangerous-product reports are held for a **human safety review** before any refund or supplier task.
- **Returns** and **size exchanges** take different paths (money vs supplier / no refund).
- **Agent-originated refunds always wait for a merchant's approval — even if a merchant turns on auto-approval.**
  (Auto-approval is an experimental opt-in for ordinary customer requests, capped by an amount limit; it is off on
  the hosted demo.)
- After approval, TradeOS calls PayPal Sandbox refunds; success is shown only when PayPal reports `COMPLETED`, then a
  **signed webhook** and an **independent PayPal GET** reconcile the result on a **tamper-evident** audit chain.

Buyer agents connect to **TradeOS's own restricted `/mcp` gateway** (not the official PayPal MCP). Tools: place a
Sandbox demo order, request a return/exchange, read status (+ optional read-only Channel3 `find_product`). There is
**no approve or refund tool**.

## How we built it

- **FastAPI** server-rendered merchant dashboard + JSON APIs.
- **Groq** `openai/gpt-oss-20b` for a limited semantic role (intent / summary); keyword fallback if the model is down.
- **Deterministic policy + Safety Gate** in pure Python (no LLM in the money decision).
- **Merchant approval** before any agent-requested refund; on the hosted demo every refund needs a person
  (opt-in auto-approval is off).
- **PayPal Sandbox:** Orders, Captures, Payments v2 refunds; self-verified signed webhooks; GET reconciliation.
- **SHA-256 hash-chained audit** (tamper-evident, not immutable).
- **AG Grid** Community for the returns inbox; **Channel3** for optional agent product discovery; **Render** for hosting.
- A toolkit-contrast script only **reads** PayPal agent-toolkit tool lists; it does not call PayPal MCP.

## Measured evidence (hosted `49261e5`; local checks labelled separately)

| Evidence | Result |
| --- | --- |
| Hosted `sandbox_verify` | 31/31 |
| AI end-to-end | 11/11 |
| Signed webhooks | 3/3 VERIFIED |
| GET reconciliation | 3/3 |
| Audits | 10/10 |
| Malformed Origin / Referer | 403 (58/58) |
| UI checks | 10/10 |
| Deterministic policy matrix | 582/582 (rules, not LLM requests) |
| pytest / coverage / lint | See [`submission-evidence.md`](submission-evidence.md) for the tip count (mock PayPal; not hosted refund evidence) |
| LLM intent eval (52 author-written messages) | exact 41/52 vs keyword 17/52; request-check 52/52 on this small set (not general accuracy) |

Sample refund IDs from the hosted `49261e5` run: `8J695063YN268980W`, `5T938247AP7025502`, `20907736BD190784X`.
`49261e5` differs from `1d5ab96` only in copy/templates. Historical runs (e.g. `1d5ab96`, published `dc2c6b5` 31/31;
local `9dafb70` Sandbox) remain labelled historical in [`submission-evidence.md`](submission-evidence.md).

## Why different

Agentic checkout helps a buyer spend. Returns need a different trust boundary: the buyer agent may speak, but the
merchant must control money. TradeOS encodes that boundary in tools and code rather than in prompts alone. We do
**not** claim to be first or unique — only that this build keeps request, approval and PayPal confirmation separate
and measurable.

## Challenges & what we learned

- A malformed `Origin` / `Referer` (`https://[`) used to 500; CSRF parsing now rejects with **403**.
- An unknown refund outcome is reconciled with PayPal (GET / webhook) instead of blindly retried.
- The LLM never sets refund amounts; amounts come from PayPal captures and merchant-approved policy maths.
- Shared ephemeral demos need clear UI hints: free text creates a **new** Sandbox order; IDs in the message are not
  looked up.

## Limits & next

- **Sandbox only** — no live money.
- Single-merchant **shared ephemeral** demo (resets on restart / deploy).
- Free-text intake creates **demo orders**; order IDs typed in text are not looked up.
- Supplier replies are **mocked**.
- Opt-in auto-approval (non-agent refunds up to a merchant limit; size exchanges) is experimental, unit-tested only,
  and **off** on the hosted demo. Agent requests still need a person even if it is turned on.
- Buyer identity is **unverified** (self-declared agent / on-behalf-of names).
- Not fraud-proof, not production-ready, not a claim of zero bugs or 100% accuracy.

## Built with

PayPal Sandbox · FastAPI · Groq (`openai/gpt-oss-20b`) · AG Grid Community · Channel3 · Render · SQLite · MCP (TradeOS gateway)

## Links

- Live demo (Sandbox): https://tradeos-s33z.onrender.com
- Source: https://github.com/Fu93/tradeos
- License: https://github.com/Fu93/tradeos/blob/main/LICENSE
- Evidence checklist: https://github.com/Fu93/tradeos/blob/main/docs/submission-evidence.md
- Video script: https://github.com/Fu93/tradeos/blob/main/docs/demo-video-script.md
- YouTube: _TBD — placeholder_
