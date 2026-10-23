# Run, configure and deploy

## Run locally

```bash
git clone https://github.com/Fu93/tradeos.git && cd tradeos
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.lock  # hash-pinned build (regenerate with:
                                      #   uv pip compile requirements-dev.txt -o requirements-dev.lock --generate-hashes --universal)
cp .env.example .env        # fill in PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET (Sandbox) and optionally LLM_API_KEY
uvicorn app.main:app --reload
# open http://localhost:8000 and click "Run Case A", approve it, then "Run Case B"
# experimental, local only: to see the opt-in auto-approval path, AUTO_ENABLED=1 uvicorn app.main:app --reload
```

No PayPal credentials yet? `PAYPAL_MOCK=1 uvicorn app.main:app` runs the whole loop offline with fake `MOCK-` IDs.
A red "MOCK mode" badge is shown; nothing in that mode is a real PayPal result.

An offline run **without `LLM_API_KEY`** uses the keyword extractor, which reads **English only**. The non-English
presets (Chinese / Spanish / German / Japanese) then come back as `UNKNOWN` and are rejected to a human — the intended
outcome for a request the extractor cannot read, but it means 4 of the 7 presets look blocked until you add a key.
The case page says so (`keyword-fallback`, "no LLM key set"), and the policy reason reads "not supported by the
automated workflow; route to a human".

With `TRADEOS_RESET_ON_START=1` every start archives the existing cases and seeds a fresh demo (on Render without a persistent disk
the filesystem is empty after a restart anyway). Refunds still `PENDING` or with an unknown outcome in a kept database are
reconciled against PayPal in the background at startup.

### Environment variables

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `PAYPAL_CLIENT_ID` | yes (for real Sandbox) | — | Sandbox app credentials from developer.paypal.com |
| `PAYPAL_CLIENT_SECRET` | yes (for real Sandbox) | — | never commit it |
| `PAYPAL_BASE_URL` | no | `https://api-m.sandbox.paypal.com` | |
| `PAYPAL_MOCK` | no | `0` | `1` = offline fake PayPal, clearly labelled |
| `PAYPAL_WEBHOOK_ID` | no | — | ID from `scripts/register_webhook.py`; empty ⇒ webhooks recorded as *not verified* |
| `LLM_API_KEY` | no | — | empty ⇒ keyword extractor |
| `LLM_BASE_URL` | no | `https://api.groq.com/openai/v1` | any OpenAI-compatible API |
| `LLM_MODEL` | no | `openai/gpt-oss-20b` | |
| `TRADEOS_DB_PATH` | no | `tradeos.db` | |
| `TRADEOS_RESET_ON_START` | no | `1` | archive old cases and reseed demo data at boot |
| `TRADEOS_ALLOW_LIVE` | no | `0` | the PayPal client refuses any base URL that is not the sandbox unless this is explicitly `1` |
| `PUBLIC_BASE_URL` | no | `RENDER_EXTERNAL_URL` or `http://localhost:8000` | PayPal return URL for the approval fallback |
| `RETURN_WINDOW_DAYS` | no | `30` | |
| `FREE_TEXT_MAX_CHARS` | no | `500` | free-text length cap |
| `RATE_LIMIT_PER_MINUTE`, `RATE_LIMIT_PER_HOUR`, `RATE_LIMIT_GLOBAL_PER_HOUR` | no | `5`, `30`, `200` | runs that create sandbox orders (per IP / global) |
| `RATE_LIMIT_MONEY_PER_MINUTE`, `RATE_LIMIT_MONEY_PER_HOUR`, `RATE_LIMIT_MONEY_GLOBAL_PER_HOUR` | no | `30`, `150`, `600` | separate, higher budget for the money actions (approve / decline / refund / capture) |
| `TRADEOS_TRUST_CF_CONNECTING_IP` | no | `0` | `1` where a Cloudflare edge is really in front (render.yaml sets it for Render); off by default so the rate-limit identity cannot be forged |
| `TRADEOS_TRUSTED_PROXY_HOPS` | no | `1` | which X-Forwarded-For entry (counted from the right) is the client address for rate limiting |
| `TRADEOS_WEBHOOK_MAX_AGE_S` | no | `600` | webhook replay window on the signed transmission time (see [how-it-works.md](how-it-works.md)) |
| `TRADEOS_WEBHOOK_MAX_FUTURE_SKEW_S` | no | `120` | allowed future clock skew of a webhook's transmission time |
| `TRADEOS_SAFETY_AI` | no | `0` | `1` = opt-in second-layer AI safety classifier (escalate-only, fail-safe; needs `LLM_API_KEY`). **Off by default and off on the hosted demo.** See [`safety-gate.md`](safety-gate.md) |
| `TRADEOS_SAFETY_AI_TIMEOUT_S` | no | `8` | timeout of that classifier; on timeout or error the keyword gate's result stands |
| `TRADEOS_SHIPPING_POLICY` | no | `WITHDRAWAL_FULL` | shipping refund policy for mixed orders: `WITHDRAWAL_FULL`, `MERCHANT_ERROR` or `NEVER` (unknown value fails closed to `NEVER`); see [`partial-refunds.md`](partial-refunds.md) |
| `TRADEOS_RECONCILE_IN_BACKGROUND` | no | `1` | background check of PENDING refunds only |
| `TRADEOS_RESET_COOLDOWN_PER_IP_S`, `TRADEOS_RESET_COOLDOWN_GLOBAL_S` | no | `60`, `15` | cooldown between two "Reset demo" clicks (per IP / whole app) |
| `TRADEOS_DISPUTES_SYNC_INTERVAL_S`, `TRADEOS_DISPUTES_REFRESH_INTERVAL_S` | no | `20`, `10` | minimum seconds between two read-only dispute fetches (whole app / same dispute) |
| `REFUND_FAILURE_MOCK_CODE` | no | `REFUND_FAILED_INSUFFICIENT_FUNDS` | PayPal negative-testing code for the failure demo |
| `MOCK_SUPPLIER_OUT_OF_STOCK` | no | `0` | `1` = the mock supplier reports the replacement out of stock, so an exchange needs a human |
| `AUTO_ENABLED` | no | `0` | `1` = the merchant's own policy may approve a policy-eligible refund without a person |
| `AUTO_REFUND_MAX_AMOUNT` | no | `50.00` | the limit above which a refund always goes to a person |
| `AUTO_EXCHANGE_ENABLED` | no | `0` | `1` = the merchant's own policy may approve a size exchange too (no money moves); needs `AUTO_ENABLED` |
| `COST_HUMAN_MINUTES`, `COST_HOURLY_RATE_USD`, `COST_AI_API_USD`, `COST_REVIEW_MINUTES` | no | `8`, `20`, `0.06`, `1` | illustrative cost model |

## Postman collection (dev-time tooling)

[docs/postman/](postman/README.md) has a Postman collection and a secret-free environment template for the exact
PayPal Sandbox calls TradeOS makes (OAuth, create order, capture, refund incl. partial, get refund, disputes GET,
webhook verify). It is manual tooling for reviewers and is **not** part of the money path.

## Deploy

`render.yaml` is a Render Blueprint (Starter plan, no disk, SQLite in `/tmp`, demo reseeded at boot, hash-pinned
`requirements.lock`, health check `/healthz`). **The hosted demo does not follow the Blueprint in two respects:** that
service's settings differ from the Blueprint: it installs `requirements.txt` (exact `==` pins, no hashes) and has
**no health check path** configured (checked through the Render API on 19 Oct 2026). Without a health check path, Render
only checks that the new instance accepts TCP connections on its port before switching traffic to it
([Render docs](https://render.com/docs/health-checks)); it does not check that `/healthz` answers. So after each deploy we
check `/healthz` and run `sandbox_verify.py` by hand.
Secrets are entered in the Render dashboard. For the webhook, run `scripts/register_webhook.py` once against the public
URL and set `PAYPAL_WEBHOOK_ID`. The service has no persistent disk, so `/tmp` is wiped on restart or deploy (Starter does not sleep); webhooks for cases from before a
restart are acknowledged and ignored.
