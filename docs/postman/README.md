# Postman collection: the PayPal calls TradeOS makes

**Dev-time tooling, not in the money path.** TradeOS never loads or runs this collection. It exists so a reviewer or
developer can reproduce, by hand and against the **PayPal Sandbox only**, the exact REST calls in `app/paypal_client.py`.
Nothing here is proof of anything on its own: it is a convenience, and a manual run you do is your own evidence.

## Files
- `tradeos-paypal-sandbox.postman_collection.json`: the requests (Postman collection v2.1).
- `tradeos-sandbox.postman_environment.template.json`: environment **template with no secrets**. Import it, then fill
  `client_id` and `client_secret` in *your* copy. Never commit a filled-in environment or an exported token.

## Calls covered
| # | Call | TradeOS function |
|---|---|---|
| 1 | `POST /v1/oauth2/token` (client credentials) | `_access_token` |
| 2 | `POST /v2/checkout/orders` (sandbox test card, intent CAPTURE) | `create_order_with_card` |
| 2 | `POST /v2/checkout/orders/{id}/capture` | `capture_order` |
| 3 | `GET /v2/payments/captures/{id}` | `get_capture` |
| 3 | `POST /v2/payments/captures/{id}/refund` (full: no amount) | `refund_capture` |
| 3 | same, **partial** (`amount`) | used by mixed-order batches (mixed-order batches, now on `main`) |
| 3 | `GET /v2/payments/refunds/{id}` | `get_refund` |
| 4 | `GET /v1/customer/disputes`, `GET /v1/customer/disputes/{id}` (read-only, needs `disputes/read-seller`) | `list_disputes`, `get_dispute` |
| 5 | `POST /v1/notifications/verify-webhook-signature` | `verify_webhook_signature` |
| 5 | `GET /v1/notifications/webhooks` | registration check |

Write-style calls carry `PayPal-Request-Id` (a fresh GUID per send, set by a pre-request script; set `request_id` in
the environment yourself to test an idempotent retry: same id + same body returns the original result) and
`Prefer: return=representation`, as TradeOS does. Test scripts store `order_id`, `capture_id`, `refund_id` and log the
`PayPal-Debug-Id` so you can look it up in the PayPal Developer Dashboard (Sandbox) logs.

## Quick run
1. Import both files; select the environment; set `client_id` / `client_secret` from a Sandbox REST app.
2. Run **1. Auth**, then **Create order**, **Get capture**, **Refund (partial)** with `refund_amount`, **Get refund**.
3. Keep `base_url` = `https://api-m.sandbox.paypal.com`. Do not use live credentials.

## Limits
Not covered: PayPal webhook delivery itself (PayPal calls TradeOS, not the other way round; the verify call needs a real
signed event and headers you copy from a delivery), the disputes write calls (TradeOS has none), and anything on live.
Currencies JPY/HUF/TWD take whole numbers only.
