# TradeOS at the PayPal AI Hackathon

TradeOS started as an entry to the PayPal AI Hackathon (8–19 Oct 2026). This page keeps the judge-facing material: the quick start, the build timeline, what the dashboard shows, the 3-minute demo flow and the illustrative cost model. The product overview is in the [README](../README.md).

**Live demo:** https://tradeos-s33z.onrender.com (PayPal Sandbox; no real money)

## Judge quick start — about 3 minutes

1. The service runs on Render's Starter plan and does not sleep; if a page is slow, the AI call or PayPal is usually the cause — wait a few seconds and refresh once.
2. Click **Run Case A — eligible return (refund)**. This creates a real PayPal Sandbox order and capture.
3. Click **Approve & refund**. The Refund API is not called before this human approval.
4. Read the four evidence cards: **PayPal refund**, **Signed PayPal notice**, **Checked against PayPal**, and the audit-chain badge.
5. For the contrast, run **Case B** (policy rejects, Refund API = 0) or the **Chinese (Traditional)** preset (exchange, no refund).

The dashboard keeps the complete path visible: **AI intent → Python policy → human approval → PayPal → webhook → reconciliation**.
The top ribbon and badges identify the environment: **Hackathon Demo · PayPal Sandbox · No real money**. The Starter service has no persistent disk (SQLite lives in `/tmp`), so data is ephemeral: a restart or deploy may reseed the shared demo cases.

The matching recording plan is in [`demo-video-script.md`](demo-video-script.md); it treats the UI guide and evidence cards as part of the judge story rather than as separate documentation.

## Built during the hackathon

First commit **8 Oct 2026**; every commit on `main` up to this tip is dated 8-19 Oct 2026. As of #71, 67 pull requests were merged, up to #71 (not merged: the experimental #9, the closed #33 and two dependabot PRs). Highlights:

| Date | What landed |
|---|---|
| 8 Oct | MVP loop: AI intent → policy → human approval → PayPal Sandbox refund; multilingual input; grounded notes; eval; first webhook |
| 10 Oct | Self-verified signed webhooks, refund pending/failed events, reconcile-by-GET, PayPal evidence timeline, hash-chained audit trail, web hardening; return-vs-exchange split; opt-in autonomy (experimental, off) |
| 11-12 Oct | Hardening: error classification, run serialisation, CI coverage gate + mypy + pip-audit, deploy-verify workflow, audit-head retention, ephemeral-persistence notice |
| 17 Oct | Judge guidance + Sandbox notice, "PayPal proves" panel, honest LLM-unavailable notice, 375px mobile fixes, rate-limit client key |
| 18 Oct | PayPal Disputes (read-only), seeded multilingual queue view, mixed orders with code-computed partial refunds, Postman collection, impact-proof doc, **Safety Gate**, downloadable evidence report, keyboard/accessibility pass |

Full list: [merged pull requests](https://github.com/Fu93/tradeos/pulls?q=is%3Apr+is%3Amerged).

## What a judge sees

The dashboard is one page: a **6-step pipeline** across the top (Customer request → AI intent → Policy → Supplier →
Approval → PayPal), lit green / amber / red / grey for the selected case, and a **big result card** above the fold.
The **case list** above it carries one chip per case, marking a finished case **AUTO** (the merchant's policy
approved it) or **HUMAN** (a person did), so a session's mix of the two reads at a glance; rejected and still-waiting
cases carry no prefix because no approval happened.

| Case B — rejected, no refund call | Refund API failure — failure shown, never success |
| --- | --- |
| ![Case B](case-b-rejected.png) | ![Refund failure](refund-api-failure.png) |

* **Success** shows `Refund COMPLETED`, confirmed by PayPal, with Order ID, Capture ID, Refund ID, amount and PayPal's timestamp
  (plus a second, independent confirmation from the signed PayPal webhook when configured).
* **Rejected** shows `Refund not executed`, the policy reason, `Refund API calls: 0` and `Refund ID: none`. A message with
  instruction-like text is shown as **Rejected: instruction-like text in the message** (never reaches approval); a request
  outside the two automated paths is shown as **Needs human review**. A message that reports a fault or harm on a
  mains / heating / gas / battery product, or any burn / injury / fire / shock / melting / smoke language (EN, ZH, ES, DE,
  JA, FR), is stopped earlier by the **Safety Gate** (deterministic code, independent of the LLM) and shown as
  **Needs human safety review**: no approve button, Refund API NOT CALLED, no supplier task, enforced server-side. A person can then **mark the case reviewed** with a required note (recorded on the hash chain; terminal
  state `SAFETY_REVIEWED`; no money moves and the case never re-enters the refund flow). See
  [docs/safety-gate.md](safety-gate.md) for the rules, false-positive handling and what is and is not proven.
  The other labels are display only: the decision stays REJECTED, there is no approve button and the Refund API is not called.
* **Mixed orders (Case M)**: the *PayPal evidence* panel lists every partial refund (one per batch) with its refund id,
  the computed amount, the amount PayPal reported and the signed-webhook slot (*waiting…* / *Verified ✓*); the webhook is
  matched to the batch by PayPal's refund id. The item table keeps each line's refunded amount after approval.
* **/api/docs** is Swagger UI served from `app/static/swagger` (swagger-ui-dist 5.33.3, Apache-2.0): no CDN and the
  Content-Security-Policy is unchanged.
* The three plan blocks are kept: **1 Pending action** (the result / approval card; the heading names the outcome — *Result: refund completed*, *Result: rejected (no refund)* … — once nothing is pending any more), **2 Case timeline** (plain English,
  raw JSON in a collapsible `raw` under every event, full JSON at `/api/cases/{id}`), **3 Case economics** (smaller,
  still labelled *Illustrative cost model — assumptions configurable.*), plus the return-vs-exchange table and the
  **MOCK supplier** label.


## Demo flow (≈3 minutes)

1. Problem and audience: small cross-border merchants without an ops team.
2. **Try it yourself → Spanish** (or English / Japanese) → Run → real sandbox order + capture → the AI panel shows
   the Spanish original and the English merchant summary (a return) → pipeline lights up to *Approval*.
3. **Approve & refund** → `Refund COMPLETED`, confirmed by PayPal, with Order / Capture / Refund IDs; the Spanish
   note travels with the refund as `note_to_payer`.
3b. **Chinese-language preset (exchange 42 → 43)** → MOCK supplier approves a replacement → **Approve exchange (no refund)** →
   `Exchange arranged — no refund`, Refund API calls 0.
3c. **The agent completes cases on its own** (start the app with `AUTO_ENABLED=1 AUTO_EXCHANGE_ENABLED=1`) → run the
   same return and the Chinese-language exchange → neither shows an Approve button, both finish (`Refund COMPLETED`,
   `Exchange arranged — no refund`), and the case list marks them **AUTO**. The timeline shows *"Autonomy: AUTO —
   within the merchant's limits"* followed by *"Auto-approved by the merchant's policy — no human involved"*. Then set
   `AUTO_REFUND_MAX_AMOUNT=10.00` and run the return again: it waits for a person, because $49.99 is outside the
   merchant's limit. That contrast — and the fact that the exchange still moves no money — is the point.
4. **Run Case B** (or the *Late request* preset) → policy REJECTED → `Refund not executed`, Refund API calls 0, Refund ID none.
5. **Failure & safety modes**: the prompt-injection preset is rejected and can't change the amount; forced PayPal refund failure is shown as a failure and
   retried; a double-clicked approve yields one refund.
6. Case economics block (illustrative).

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
