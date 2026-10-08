# TradeOS

> **PayPal moves the money. TradeOS moves the work.**
>
> Use AI where language is ambiguous. Use code where money is at stake.

TradeOS is an AI-powered operational bridge for cross-border commerce, built for the **PayPal AI Hackathon**.
It sits *after* payment: it turns an unstructured customer request into a completed merchant operation —
understand the request, check policy, coordinate the supplier, ask a human to approve, then execute
(or block) the PayPal action.

![TradeOS dashboard](docs/dashboard.png)

## The problem

Small cross-border merchants cannot staff a full operations or customer-service team. A simple
"can I swap size 42 for 43?" turns into minutes of manual work: read the message, look up the order,
check the return window, email the supplier, decide, and then go into PayPal to issue the refund.
That is slow, and it is risky, because the person doing it is also the person moving money.

TradeOS automates the *work* around the payment while keeping money movement deterministic,
human-approved and confirmed by PayPal.

TradeOS is **not** a storefront, a consumer shopping agent, or a chatbot that answers the customer.

## What the MVP proves

1. **AI can understand natural language** — customer message → structured intent.
2. **Rules control the AI** — the model cannot override policy. A blocked case never calls the Refund API.
3. **PayPal actually executes** — Order → Capture → real Refund ID. The UI shows success only after PayPal confirms `COMPLETED`.
4. **Automation can be cheaper than labour, with visible assumptions** — an illustrative cost model, not a claimed measured saving.

## The one workflow

| Step | Case A — eligible exchange | Case B — same request, rejected |
| --- | --- | --- |
| PayPal Sandbox order + capture | ✓ real Order ID + Capture ID | ✓ real Order ID + Capture ID |
| Customer: *"The shoes are too small. Can I exchange size 42 for size 43?"* | AI → `EXCHANGE_REQUEST / SIZE_MISMATCH / EXCHANGE` | same |
| Deterministic policy (fed by `GET /v2/payments/captures/{id}`) | ELIGIBLE | **REJECTED** — purchased 45 days ago, 30-day window |
| Supplier | Generated draft + **MOCK** reply `REPLACEMENT_APPROVED` | not contacted |
| Human | Approves in the dashboard | — |
| PayPal | `POST /v2/payments/captures/{id}/refund` → Refund ID, `COMPLETED` | **Refund API NOT CALLED**, Refund ID none |

Case B's purchase date is **seeded demo data** (and labelled as such on screen): sandbox captures are always
dated today, so the merchant's own order record simulates a purchase 45 days ago.

### Exchange vs refund

PayPal has no exchange API, so the layers are kept separate:

| Layer | Field | MVP value |
| --- | --- | --- |
| Customer intent | `EXCHANGE_REQUEST` | Size 42 → size 43 |
| Supplier resolution | `REPLACEMENT_APPROVED` | Mock, clearly labelled |
| Financial resolution | `ORIGINAL_PAYMENT_REFUNDED` | Real Sandbox refund |

> For the hackathon MVP, the financial side of an exchange is simplified to a refund of the original PayPal
> transaction. Replacement fulfilment is represented by the supplier confirmation.

## Architecture

```
Customer message
      │
      ▼
IntentExtractor (adapter) ──► {intent, reason, requested_action}   ← AI: language only, strict pydantic schema
      │                         (LLM via any OpenAI-compatible API; keyword fallback)
      ▼
Policy engine (pure Python) ◄── PayPal GET capture (status, amount, currency)
      │   checks: request supported · capture COMPLETED · return window · product eligible ·
      │           refundable amount · supplier confirmed            → ELIGIBLE / REJECTED + reasons
      ├── REJECTED ──► stop. Refund API is never called.
      ▼
Supplier draft + MOCK reply (REPLACEMENT_APPROVED)
      ▼
Human approval (dashboard)  ← required for every financial action
      ▼
PayPal Refund API (idempotent PayPal-Request-Id = tradeos-refund-<case id>)
      ▼
SQLite audit timeline + PayPal call log
```

* **Stack:** Python 3.12+, FastAPI, SQLite, Jinja2 + plain CSS + a few lines of vanilla JS, httpx.
* `app/intent.py` — `IntentExtractor` interface; `LLMIntentExtractor` (OpenAI-compatible `/chat/completions`,
  strict `json_schema` structured output with a `json_object` retry, then pydantic validation — anything off-schema
  becomes `UNKNOWN`); `KeywordIntentExtractor` deterministic fallback (no key needed, and used if the LLM call fails).
* `app/policy.py` — deterministic policy engine. The AI output can only add a NO, never remove one.
* `app/paypal_client.py` — OAuth2 client credentials, Orders v2, Payments v2.
* `app/workflow.py` — the loop, plus the hard guard: `execute_refund` refuses unless policy is `ELIGIBLE`
  **and** a human `APPROVED`. This is enforced in code (and tested), not just hidden in the UI.
* `app/db.py` — SQLite: cases, audit timeline (request, intent, policy, supplier, human, PayPal result with timestamps),
  and a log of every PayPal API call (which is how "Refund API: NOT CALLED" is proven).
* `app/templates/dashboard.html` — three blocks: **Pending action**, **Case timeline**, **Case economics**,
  plus the demo evidence panel and one-click **Run Case A / Run Case B** buttons.

### PayPal APIs used (Sandbox)

| API | Purpose |
| --- | --- |
| `POST /v1/oauth2/token` | Client-credentials access token (cached) |
| `POST /v2/checkout/orders` | Create a USD 49.99 order, `intent: CAPTURE`, paid with a PayPal **sandbox test card** (`payment_source.card`) so it captures without a buyer login |
| `POST /v2/checkout/orders/{id}/capture` | Capture (fallback path when card capture is unavailable: the dashboard shows the buyer approve link, PayPal redirects back, TradeOS captures) |
| `GET /v2/payments/captures/{id}` | Real capture status / amount / currency → policy engine input |
| `POST /v2/payments/captures/{id}/refund` | Full refund (empty body) with an idempotent `PayPal-Request-Id` derived from the case ID |
| `GET /v2/payments/refunds/{id}` | Refresh a `PENDING` refund (pending is never shown as success) |

PayPal errors (HTTP status, name, message, `debug_id`) are stored on the case and shown in the UI.

### LLM provider

The model sits behind an adapter and is not part of the product. The default is **Groq's OpenAI-compatible endpoint**
(`https://api.groq.com/openai/v1`, model `openai/gpt-oss-20b`); any other OpenAI-compatible endpoint works by
changing `LLM_BASE_URL` / `LLM_MODEL`. Without `LLM_API_KEY` the deterministic keyword extractor is used, so the
demo always runs.

## Run locally

```bash
git clone https://github.com/Fu93/tradeos.git && cd tradeos
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET (Sandbox) and optionally LLM_API_KEY
uvicorn app.main:app --reload
# open http://localhost:8000 and click "Run Case A", approve it, then "Run Case B"
```

No PayPal credentials yet? `PAYPAL_MOCK=1 uvicorn app.main:app` runs the whole loop offline with fake `MOCK-` IDs.
A red "MOCK mode" badge is shown; nothing in that mode is a real PayPal result.

The demo database is wiped and reseeded on every start (`TRADEOS_RESET_ON_START=1`), which also suits Render's
ephemeral free-tier disk.

### Environment variables

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `PAYPAL_CLIENT_ID` | yes (for real Sandbox) | — | Sandbox app credentials from developer.paypal.com |
| `PAYPAL_CLIENT_SECRET` | yes (for real Sandbox) | — | never commit it |
| `PAYPAL_BASE_URL` | no | `https://api-m.sandbox.paypal.com` | |
| `PAYPAL_MOCK` | no | `0` | `1` = offline fake PayPal, clearly labelled |
| `LLM_API_KEY` | no | — | empty ⇒ keyword extractor |
| `LLM_BASE_URL` | no | `https://api.groq.com/openai/v1` | any OpenAI-compatible API |
| `LLM_MODEL` | no | `openai/gpt-oss-20b` | |
| `TRADEOS_DB_PATH` | no | `tradeos.db` | |
| `TRADEOS_RESET_ON_START` | no | `1` | reseed demo data at boot |
| `PUBLIC_BASE_URL` | no | `RENDER_EXTERNAL_URL` or `http://localhost:8000` | PayPal return URL for the approval fallback |
| `RETURN_WINDOW_DAYS` | no | `30` | |
| `COST_HUMAN_MINUTES`, `COST_HOURLY_RATE_USD`, `COST_AI_API_USD`, `COST_REVIEW_MINUTES` | no | `8`, `20`, `0.06`, `1` | illustrative cost model |

## Tests

```bash
pytest
```

The suite never calls real PayPal or a real LLM (PayPal is replaced by an in-memory mock wrapped in `MagicMock`,
HTTP is replaced by `httpx.MockTransport`). It covers the policy engine (window boundaries, capture status,
amount/currency, product, supplier, "no AI output can override a NO"), the PayPal client (token caching, card
order payload, empty-body refund with `PayPal-Request-Id`, structured errors), the LLM adapter (strict schema,
off-schema → `UNKNOWN`, structured-output retry, fallback on errors), and the workflow/HTTP layer — including
**Case B: `refund_capture` is asserted never to be called**, even with a forged human approval or a lying extractor.

## Demo flow (≈3 minutes)

1. Problem and audience: small cross-border merchants without an ops team.
2. **Run Case A** → PayPal Sandbox order + capture → AI intent → policy ELIGIBLE → supplier draft + MOCK approval →
   pending action → **Approve & refund** → real Refund ID, status `COMPLETED` (shown only after PayPal confirms).
3. **Run Case B** → same request understood → policy REJECTED (45 days vs 30-day window, seeded demo date) →
   **Refund API: NOT CALLED**, Refund ID none.
4. Case economics block (illustrative).

## Case economics

| Item | Amount |
| --- | --- |
| Order / refund | $49.99 USD |
| Human labour estimate | 8 min × $20/hour = $2.67 |
| AI / API cost | $0.06 |
| Human review | 1 min = $0.33 |
| TradeOS estimated cost | $0.39 |
| Estimated saving | $2.28 |

**Illustrative cost model — assumptions configurable.** These are assumptions (see the `COST_*` env vars),
not a measured or verified saving.

## Deploy

`render.yaml` is a Render Blueprint for a one-click deploy (free plan, SQLite in `/tmp`, demo reseeded at boot).
Secrets are entered in the Render dashboard.

## Scope

Out of scope for this MVP: product sourcing, scraping, multichannel commerce, live supplier chat, logistics/customs/
invoicing, autonomous financial decisions, partial refunds, real fulfilment.

## License

[MIT](LICENSE)
