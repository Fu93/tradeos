# PayPal depth (#10 → #11 → #12): pre-merge checklist and Sandbox verification

## Current hosted tip — `f2c7430` (8 Nov 2026)

https://tradeos-s33z.onrender.com serves `f2c74302622d91f988ba7fad097052ed4c322a56` (`/healthz` matches). Measured on
this hosted tip: submission preflight **9/9**, `sandbox_verify` **31/31**, AI e2e **11/11**, deterministic policy
matrix **582/582**, offline pytest **1841** / coverage **95.08%** / ruff+mypy clean (docs/UI follow-up tip: **1842**),
malformed Origin/Referer → **403** (58/58). See [`submission-evidence.md`](submission-evidence.md).

## Historical — local Sandbox + LLM eval on `9dafb70` (8 Nov 2026)

Tip `9dafb70` was exercised in a **local Sandbox run** on an isolated verification machine: **62 pass /
0 fail / 6 webhook SKIP** (no public webhook receiver / `PAYPAL_WEBHOOK_ID` path for localhost), UNKNOWN recovery
**2/2**, ERROR-retry **4/4**, over-refund **422**, and AI e2e **11/11**. That local run is historical evidence for
`9dafb70`, not a substitute for the current hosted tip.

Same day, a full offline LLM eval on tip `9dafb70` with Groq **`openai/gpt-oss-20b`** (52 author-written messages,
one run, **all HTTP 200**): exact **41/52**, lenient **47/52**, policy request-check **52/52** on this small set
(not general accuracy), keyword **17/52**. Committed in [`docs/eval/`](eval/).

## Historical — published demo technical recheck — 7 Nov 2026

The published `dc2c6b5` build passed the default live Sandbox verification
and the separate two-batch partial-refund verification. Exact case, refund,
Debug-ID, amount and audit-chain results are in
[`docs/evidence/sandbox-verify-dc2c6b5-2026-11-07.md`](evidence/sandbox-verify-dc2c6b5-2026-11-07.md).
This is historical evidence for `dc2c6b5` only.

## Published demo recheck — 5 Nov 2026

At 23:19 GMT, the public demo's `/healthz` reported commit
`dc2c6b5cd40e19c2f859d54a71f06b593c350864`, PayPal mode `sandbox`, LLM and webhook configured, and autonomy off.
Running `python scripts/sandbox_verify.py https://tradeos-s33z.onrender.com` against that published build returned
**31/31 PASS**: human approval before refund, one completed Sandbox refund, a self-verified signed webhook, a
matching PayPal reconciliation, a rejected Case B with zero refund calls, an exchange with zero refund calls, and a
refused-then-retried Case R. The complete output is preserved in
[`docs/evidence/sandbox-verify-dc2c6b5-2026-11-05.log`](evidence/sandbox-verify-dc2c6b5-2026-11-05.log).
The verifier was run from this working tree; its uncommitted change adds optional Basic Auth for private deployments,
while the default checks are unchanged from the committed script. This recheck proves the **published commit**, not
the other uncommitted changes in this workspace or any future deployment. The PayPal Developer Dashboard debug-ID
lookup remains a manual step and is not included in the 31 checks.

## Pre-merge checklist

*(All done 2026-10-10 — #10, #11 and #12 are merged; kept for the record.)*

- [x] `pytest -q` is green on each branch: `feat/paypal-depth` 168, `feat/paypal-evidence` 177, `feat/paypal-reconcile` 198.
- [x] Merge in order **#10 → #11 → #12**, retargeting each PR to `main` after the previous one merges. Use "Create a merge commit" or "Squash": the branches were merged upward, not rebased, in the last round.
- [x] Before merging, confirm the Render env vars below exist (names only; values stay in Render).
- [x] After the **last** merge (one redeploy is enough, but each merge redeploys), wait for the deploy, then run the Sandbox check below.
- [x] If any check fails: revert the merge commit on `main` (redeploys the previous build) and reopen. *(Not needed — all checks passed.)*

## Render environment variables used (no values here)
| Variable | Needed for | Notes |
|---|---|---|
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` | all PayPal calls | Sandbox REST app |
| `PAYPAL_BASE_URL` | all PayPal calls | `https://api-m.sandbox.paypal.com` |
| `PAYPAL_WEBHOOK_ID` | signed webhook verification | unchanged if `register_webhook.py --apply` reports `updated ... (unchanged)`; only a `created` result needs a new value |
| `PAYPAL_MOCK` | must be unset or `0` on Render | `1` switches to the mock (UI then says "MOCK PayPal") |
| `TRADEOS_DB_PATH`, `TRADEOS_RESET_ON_START` | SQLite, reset + reseed on start | unchanged |
| `TRADEOS_RECONCILE_IN_BACKGROUND` | optional, default on | background check of PENDING refunds only |
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | intent extraction (and optional note translation / safety AI) | unchanged. The default sandbox_verify path creates Case A, Case B, one free-text exchange, and Case R — each intake that uses the LLM extractor makes at least one `/chat/completions` call (more if HTTP 400 falls back to `json_object`, or if safety AI / non-English notes are enabled). Hosted demo model: `openai/gpt-oss-20b` (cases show `llm:openai/gpt-oss-20b`). For a single measured free-text path, use `--ai-e2e-only`. |

No new required variables. No database migration is needed (Render reseeds on start; kept databases get the new columns automatically).

## Sandbox check after deploy (about 2 minutes)
`python scripts/sandbox_verify.py https://<render-host>`. It needs no credentials and only uses the public demo endpoints. It creates one Case A (one Sandbox order + one full Sandbox refund of the demo amount), one Case B, one exchange (size 42 → 43, no refund) and one Case R (a forced 422 refund failure, then a retry that refunds). **31 checks** (matches the default path in `scripts/sandbox_verify.py`):
1. `/healthz`: PayPal mode `sandbox`, webhook configured, `auto_exchange_enabled` reported.
2. Case A: approved; refund COMPLETED (or PENDING); **exactly one** refund call; a **real** `PayPal-Debug-Id` (not `mock-…`); `PayPal-Request-Id` recorded; retry on the finished refund returns 409.
3. Signed webhook: `PAYMENT.CAPTURE.REFUNDED` verified within 90 s (earlier live runs: 16–18 s), and the method used (`self` expected; `postback` = fallback, still OK). When `PAYPAL_WEBHOOK_ID` is unset or the target has no public webhook receiver (e.g. localhost), these print `SKIP … (reason)` instead of failing after a 90 s wait; against the hosted demo after redeploy they run fully.
4. "Check against PayPal": result "Reconciled with PayPal — all match".
5. Case B: approve returns 409, the refund API is never called; audit trails intact; badge rendered.
6. Logic-review fixes: Case A's decision / human approval / status are on the hash chain (`chained_state` in `/cases/{id}/audit/verify`); Case A's `refund_request_id` and how COMPLETED was confirmed (`completed_via`); Case B's rejection on the chain with no approval; `GET /cases/{id}/paypal-return` changes nothing.
7. Exchange: awaiting approval of the exchange → approve → `EXCHANGE_ARRANGED` with **0** refund calls; refund endpoint 409; audit chain intact. Case A's intent is a return (`REFUND`).
8. Case R: PayPal 422 shown as "refused, no money moved" (`REFUND_ERROR`), then Retry → COMPLETED with the same `PayPal-Request-Id` inside Payments v2's 6-hour window (2 refund calls).

Not provable live without breaking PayPal on purpose (covered by `tests/test_refund_faults.py` and
`tests/test_mixed_orders.py` and `tests/test_refund_lookup.py`): a refund whose reply times out
(`REFUND_OUTCOME_UNKNOWN` remains UNKNOWN in real Sandbox until a matching Refund ID is verified by GET, with no
replay), a refund PayPal reports `FAILED` (new request id after a confirmed failure), and a
reset during an in-flight refund. Mock mode separately tests same-request-ID recovery.

Manual steps:
- Open Case A in the browser. In the **PayPal evidence** panel, check the 4 summary lines and "Show details".
- Debug id lookup: in the PayPal Developer Dashboard (Sandbox), search the API call / event logs for the printed debug id.
- Also confirm the dashboard shows **no** "MOCK PayPal" tag and no "Pending refund (MOCK)" tile.

Expected on the local mock (dry run of the script, 2026-10-10): every check passes except those that need real Sandbox (mode, real debug id). Signed-webhook checks print `SKIP` with an explicit reason when `PAYPAL_WEBHOOK_ID` is unset or the target is not publicly reachable; they are not ambiguous failures.

## After merging feat/paypal-hardening (webhook re-registration)
1. Dry run: `python scripts/register_webhook.py https://<render-host>/webhooks/paypal` (needs `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET`). Expect `would update webhook <id> in place (ID unchanged)`.
2. Apply: same command with `--apply`. Expect `updated PAYPAL_WEBHOOK_ID=<same id> (unchanged)` and five events: `PAYMENT.CAPTURE.REFUNDED`, `PAYMENT.REFUND.PENDING`, `PAYMENT.REFUND.FAILED`, `PAYMENT.CAPTURE.REVERSED`, `PAYMENT.CAPTURE.DECLINED`. If it says `created`, set the new ID as `PAYPAL_WEBHOOK_ID` on Render and redeploy.
3. Deploy (adds the `cryptography` dependency), then run `sandbox_verify.py`; it reports the verification method.
4. `PAYMENT.REFUND.PENDING` / `FAILED` cannot be forced on a Sandbox card refund (they complete instantly), so they are covered by tests, not by the live check. The Webhooks simulator can deliver them, but its events are signed for `WEBHOOK_ID` and will correctly show as *not verified*.


## Optional live checks (not part of the default 31)

* `--mixed-only`: Case M, one real partial refund (see `docs/partial-refunds.md`).
* `--multi-batch-only` (or `--multi-batch` on a full run): **Case M2**, two partial refunds on one capture. The seeded message leaves two lines
  with a person; resolving one creates batch 2 on the same capture. Asserts: no refund before approval, two different refund ids and Debug-Ids,
  PayPal-reported = computed per batch, cumulative <= capture, third attempts refused with no new refund call, one verified signed webhook per refund id.
* `--paypal-overrefund-probe` (with the above): one direct Sandbox refund call above the remaining capture using the env credentials. It is a probe of PayPal, outside the app.
* Earlier run: main tip `1acae45` (the deployed commit then, `/healthz` `version` 1acae45…), 2026-10-19 15:38–15:40 BST: default 31/31 PASS
  (webhook verification method `self`), `--mixed-only` 16/16 PASS (partial refund 161.69 of 191.21 USD), `--multi-batch-only`
  21/21 PASS (55.74 + 85.32 USD on one capture, two refund ids, one verified signed webhook each; the over-refund probe was
  not run this time). Logs are kept outside the repo. App code for money/safety is unchanged since `5325db7` (#69 docs,
  #70 tax-inclusive tests, #71 CPSC eval recall only).
* Earlier same day: main `5325db7`, 2026-10-19 09:12–09:23 BST: default 31/31, `--mixed-only` 16/16, `--multi-batch-only` 21/21
  (a first multi-batch attempt hit a PayPal Sandbox `ReadTimeout` on order creation — no capture, no money moved — then
  passed on retry).
* Previous day: main `3ad67b3`, 2026-10-18: default 31/31 PASS, `--mixed-only` PASS, `--multi-batch-only --paypal-overrefund-probe` 23/23 PASS.
* `--ai-e2e-only`: one fixed English free-text return through the target's live LLM extractor → human approve → Sandbox
  refund. Prints `AI e2e LLM chat completions: N` where **N** is the measured intake count from
  `case.extraction.llm_chat_completions` (intent extract, plus any 400 json_schema→json_object retry, plus optional
  safety-AI / note-translation calls — English template notes usually add none). Requires `/healthz`
  `llm_configured=true` (LLM env on the **target**, not in the script). Not part of the default 31.
* The `Deploy verify` GitHub workflow does **not** run these checks for this repository: the `TRADEOS_DEPLOY_URL` secret
  is not set, so its verify job is skipped. The runs above were started by hand.
