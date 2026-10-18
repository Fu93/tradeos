# PayPal Disputes — read-only (what is tested, what is live-proven, what is not covered)

TradeOS can **show** PayPal disputes. It cannot act on them. There is no code that calls a Disputes write
endpoint (provide evidence, accept claim, appeal, make offer, send message, settle); `tests/test_disputes.py`
has a static guard for that. A person acts in PayPal.

## What it does
- **Webhook**: `CUSTOMER.DISPUTE.CREATED / UPDATED / RESOLVED` on the existing `/webhooks/paypal` endpoint, through the
  *same* verification (self-verify first, PayPal's postback API as fallback; unchanged). Only a verified event is applied;
  a verified event id is applied once; future-dated or old-and-already-seen deliveries are rejected; an older
  `update_time` can never move a stored dispute backwards.
- **GET only**: `GET /v1/customer/disputes` and `GET /v1/customer/disputes/{id}` (`PayPalClient.list_disputes`,
  `get_dispute`). Needs the `https://uri.paypal.com/services/disputes/read-seller` scope.
- **Storage**: `disputes` table (a read-only mirror; informational, never changes a case, refund or status). A dispute is
  linked to a case when `disputed_transactions[].seller_transaction_id` equals a capture TradeOS recorded. A matched
  dispute writes audit entries to that case's hash chain (`stage: dispute`); an unmatched one has no case to chain under
  (its webhook delivery is still logged in `webhook_events`).
- **UI**: `/disputes` shows status, reason, amount, response deadline, linked case and a recommendation computed by
  `policy.recommend_dispute` (pure Python), labelled *"Recommendation only — no action is taken; evidence submission not
  implemented"*. "Fetch from PayPal" / "Refresh" buttons are GETs.
- **No scope**: PayPal's 401/403 (or no scope in the token) shows a clear message on the page; webhook-pushed disputes still
  record; nothing crashes.

## Evidence tiers
| Tier | What | Status |
|---|---|---|
| Unit / integration tests (mock PayPal, **not** PayPal proof) | webhook created / updated / resolved; duplicate; unsigned and tampered rejected; missing headers rejected outside mock; future-dated and replayed rejected; out-of-order update ignored; unmatched dispute; recommendation rules; scope-missing degradation; GET-only client; hash chain stays valid; demo reset keeps working; RSA self-verify path with a *test* certificate | `tests/test_disputes.py` (20 tests) |
| Live Sandbox, read-only GET (2026-10-18, UTC+1) | OAuth token for the Sandbox app lists `disputes/read-seller`; `GET /v1/customer/disputes?page_size=5` → HTTP 200, `items: []` (PayPal-Debug-Id `ca4c38bff9e52` via the app's client); `GET /v1/customer/disputes/{unknown}` → 404 `RESOURCE_NOT_FOUND` (`ca4c38c00ca10`) | proves the credentials have the read scope and the GET path/auth work |
| **Not covered** | parsing a *real* PayPal dispute object (the sandbox app has **no disputes**, so the fixtures are written from PayPal's documented shape); a real signed `CUSTOMER.DISPUTE.*` delivery (the live webhook is not subscribed to these events, and the Render service is not deployed with this code); evidence submission / any dispute action (deliberately not implemented); live (production) behaviour | open |

## How to get a real sandbox dispute (not done)
Per PayPal's docs, a sandbox dispute is created as the *buyer*: `POST /v1/customer/disputes` with a buyer
`PayPal-Auth-Assertion` and the `disputes/create` scope (PayPal enables it on the app on request), or from the sandbox
personal account's Resolution Center after a card-funded payment. That is a write call outside this feature's scope and
was not made. The app's token does list `disputes/create`, but TradeOS never uses it.

## To turn it on for the Sandbox webhook (a settings change — not done here)
Subscribe the webhook to the three `CUSTOMER.DISPUTE.*` events (PayPal dashboard, or extend `EVENTS` in
`scripts/register_webhook.py`). Until then the Disputes page is populated only by "Fetch from PayPal".

## Rollback
Revert the PR. The `disputes` table is created with `CREATE TABLE IF NOT EXISTS`; leaving it in a kept database is harmless.
