# PayPal depth (#10 → #11 → #12): pre-merge checklist and Sandbox verification

## Pre-merge checklist
- [ ] `pytest -q` is green on each branch: `feat/paypal-depth` 168, `feat/paypal-evidence` 177, `feat/paypal-reconcile` 198.
- [ ] Merge in order **#10 → #11 → #12**, retargeting each PR to `main` after the previous one merges. Use "Create a merge commit" or "Squash": the branches were merged upward, not rebased, in the last round.
- [ ] Before merging, confirm the Render env vars below exist (names only; values stay in Render).
- [ ] After the **last** merge (one redeploy is enough, but each merge redeploys), wait for the deploy, then run the Sandbox check below.
- [ ] If any check fails: revert the merge commit on `main` (redeploys the previous build) and reopen.

## Render environment variables used (no values here)
| Variable | Needed for | Notes |
|---|---|---|
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` | all PayPal calls | Sandbox REST app |
| `PAYPAL_BASE_URL` | all PayPal calls | `https://api-m.sandbox.paypal.com` |
| `PAYPAL_WEBHOOK_ID` | signed webhook verification | unchanged if `register_webhook.py --apply` reports `updated ... (unchanged)`; only a `created` result needs a new value |
| `PAYPAL_MOCK` | must be unset or `0` on Render | `1` switches to the mock (UI then says "MOCK PayPal") |
| `TRADEOS_DB_PATH`, `TRADEOS_RESET_ON_START` | SQLite, reset + reseed on start | unchanged |
| `TRADEOS_RECONCILE_IN_BACKGROUND` | optional, default on | background check of PENDING refunds only |
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | intent extraction | unchanged; the check below runs Case A/B (2 LLM calls) |

No new required variables. No database migration is needed (Render reseeds on start; kept databases get the new columns automatically).

## Sandbox check after deploy (about 2 minutes)
`python scripts/sandbox_verify.py https://<render-host>`. It needs no credentials and only uses the public demo endpoints. It creates one Case A (one Sandbox order + one full Sandbox refund of the demo amount), one Case B and one Case R (a forced 422 refund failure, then a retry that refunds). 22 checks:
1. `/healthz`: PayPal mode `sandbox`, webhook configured.
2. Case A: approved; refund COMPLETED (or PENDING); **exactly one** refund call; a **real** `PayPal-Debug-Id` (not `mock-…`); `PayPal-Request-Id` recorded; retry on the finished refund returns 409.
3. Signed webhook: `PAYMENT.CAPTURE.REFUNDED` verified within 90 s (earlier live runs: 16–18 s), and the method used (`self` expected; `postback` = fallback, still OK).
4. "Check against PayPal": result "Reconciled with PayPal — all match".
5. Case B: approve returns 409, the refund API is never called; audit trails intact; badge rendered.
6. Logic-review fixes: Case A's decision / human approval / status are on the hash chain (`chained_state` in `/cases/{id}/audit/verify`); Case A's `refund_request_id` and how COMPLETED was confirmed (`completed_via`); Case B's rejection on the chain with no approval; `GET /cases/{id}/paypal-return` changes nothing.
7. Case R: PayPal 422 shown as "refused, no money moved" (`REFUND_ERROR`), then Retry → COMPLETED with the same `PayPal-Request-Id` (2 refund calls).

Not provable live without breaking PayPal on purpose (covered by tests in `tests/test_logic_review.py`): a refund whose reply times out (`REFUND_OUTCOME_UNKNOWN` → recovery), a refund PayPal reports `FAILED` (new request id after a confirmed failure), a reset during an in-flight refund.

Manual steps:
- Open Case A in the browser. In the **PayPal evidence** panel, check the 4 summary lines and "Show details".
- Debug id lookup: in the PayPal Developer Dashboard (Sandbox), search the API call / event logs for the printed debug id.
- Also confirm the dashboard shows **no** "MOCK PayPal" tag and no "Pending refund (MOCK)" tile.

Expected on the local mock (dry run of the script, 2026-10-10): every check passes except the four that need real Sandbox (mode, real debug id, signed webhook + its method).

## After merging feat/paypal-hardening (webhook re-registration)
1. Dry run: `python scripts/register_webhook.py https://<render-host>/webhooks/paypal` (needs `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET`). Expect `would update webhook <id> in place (ID unchanged)`.
2. Apply: same command with `--apply`. Expect `updated PAYPAL_WEBHOOK_ID=<same id> (unchanged)` and five events: `PAYMENT.CAPTURE.REFUNDED`, `PAYMENT.REFUND.PENDING`, `PAYMENT.REFUND.FAILED`, `PAYMENT.CAPTURE.REVERSED`, `PAYMENT.CAPTURE.DECLINED`. If it says `created`, set the new ID as `PAYPAL_WEBHOOK_ID` on Render and redeploy.
3. Deploy (adds the `cryptography` dependency), then run `sandbox_verify.py`; it reports the verification method.
4. `PAYMENT.REFUND.PENDING` / `FAILED` cannot be forced on a Sandbox card refund (they complete instantly), so they are covered by tests, not by the live check. The Webhooks simulator can deliver them, but its events are signed for `WEBHOOK_ID` and will correctly show as *not verified*.
