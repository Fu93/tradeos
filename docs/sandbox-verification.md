# PayPal depth (#10 → #11 → #12): pre-merge checklist and Sandbox verification

## Pre-merge checklist
- [ ] `pytest -q` is green on each branch: `feat/paypal-depth` 168, `feat/paypal-evidence` 177, `feat/paypal-reconcile` 199.
- [ ] Merge in order **#10 → #11 → #12**, retargeting each PR to `main` after the previous one merges. Use "Create a merge commit" or "Squash": the branches were merged upward, not rebased, in the last round.
- [ ] Before merging, confirm the Render env vars below exist (names only; values stay in Render).
- [ ] After the **last** merge (one redeploy is enough, but each merge redeploys), wait for the deploy, then run the Sandbox check below.
- [ ] If any check fails: revert the merge commit on `main` (redeploys the previous build) and reopen.

## Render environment variables used (no values here)
| Variable | Needed for | Notes |
|---|---|---|
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` | all PayPal calls | Sandbox REST app |
| `PAYPAL_BASE_URL` | all PayPal calls | `https://api-m.sandbox.paypal.com` |
| `PAYPAL_WEBHOOK_ID` | signed webhook verification | the existing registration; **no re-registration needed** |
| `PAYPAL_MOCK` | must be unset or `0` on Render | `1` switches to the mock (UI then says "MOCK PayPal") |
| `TRADEOS_DB_PATH`, `TRADEOS_RESET_ON_START` | SQLite, reset + reseed on start | unchanged |
| `TRADEOS_RECONCILE_IN_BACKGROUND` | optional, default on | background check of PENDING refunds only |
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | intent extraction | unchanged; the check below runs Case A/B (2 LLM calls) |

No new required variables. No database migration is needed (Render reseeds on start; kept databases get the new columns automatically).

## Sandbox check after deploy (about 2 minutes)
`python scripts/sandbox_verify.py https://<render-host>`. It needs no credentials and only uses the public demo endpoints. It creates one Case A (one Sandbox order + one full Sandbox refund of the demo amount) and one Case B. It checks:
1. `/healthz`: PayPal mode `sandbox`, webhook configured.
2. Case A: approved; refund COMPLETED (or PENDING); **exactly one** refund call; a **real** `PayPal-Debug-Id` (not `mock-…`); `PayPal-Request-Id` recorded; retry on the finished refund returns 409.
3. Signed webhook: `PAYMENT.CAPTURE.REFUNDED` verified within 90 s (earlier live runs: 16–18 s).
4. "Check against PayPal": result "Reconciled with PayPal — all match".
5. Case B: approve returns 409, the refund API is never called.

Manual steps:
- Open Case A in the browser. In the **PayPal evidence** panel, check the 4 summary lines and "Show details".
- Debug id lookup: in the PayPal Developer Dashboard (Sandbox), search the API call / event logs for the printed debug id.
- Also confirm the dashboard shows **no** "MOCK PayPal" tag and no "Pending refund (MOCK)" tile.

Expected on the local mock (dry run of the script, 2026-10-10): every check passes except the three that need real Sandbox (mode, real debug id, signed webhook).
