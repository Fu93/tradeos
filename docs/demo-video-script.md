# TradeOS demo video v5 — current judge flow (return → refund; exchange → no refund)

Recording plan for the current dashboard after Demo Polish v1. Target duration: 2:42–2:48.
Use the LIVE PayPal Sandbox, English narration (`en-US-AndrewNeural`), and English subtitles in a dedicated bottom band.
The first shot must show the **HACKATHON DEMO · PayPal Sandbox · No real money** ribbon, the environment badges, and the **Judge path · about 3 minutes** guide.

> Record with autonomy **off** (`AUTO_ENABLED` unset, the default), which is why the narration can say
> "a human approves, and only then does TradeOS call the PayPal Refund API". That sentence describes the configuration
> on screen, not a permanent property of the system: with `AUTO_ENABLED=1` the same eligible return is approved by the
> merchant's own policy and the case completes with no human. Showing that contrast is a v5 item, not a correction to v4.

| Time | Screen | Narration |
| --- | --- | --- |
| 0:00–0:12 | Ribbon, badges, and Judge path guide. Highlight **Start with Case A above** and the cold-start note. | A customer writes: these sneakers are too small, I want to return them. Another asks to swap a 42 for a 43. For a small merchant with no operations team, that is minutes of manual work. |
| 0:12–0:28 | Run Case A; show the pipeline moving from customer request to policy. | Translate the message, check the date, find the PayPal capture, and issue a refund by hand. TradeOS turns that work into one explainable workflow. PayPal moves the money. TradeOS moves the work. |
| 0:28–0:42 | Top badges: PayPal Sandbox, LLM Live, Webhook configured; then Chinese-language preset and AI panel. | The rule is simple: AI understands, rules decide, humans approve, and PayPal proves. Everything here runs on PayPal Sandbox: real orders, captures, and refunds. |
| 0:42–0:58 | AI panel: `EXCHANGE_REQUEST / SIZE_MISMATCH / EXCHANGE`, 42 → 43, English summary; show the backend-control table. | First, a size exchange in Chinese. The AI extracts only the intent, the size mismatch, and a merchant summary. It decides nothing. |
| 0:58–1:10 | Exchange approval card; highlight evidence card `PayPal refund: No refund requested` and pipeline `Refund API NOT CALLED`. | An exchange never moves money. The supplier reply is a mock, clearly labelled MOCK. A human approves the exchange, and the Refund API is not called. Zero refund calls. |
| 1:10–1:24 | Run Case B; show policy rejection, `Refund API calls: 0`, and `Refund ID: none`. | Only a return leads to a refund. Case B is purchased 45 days ago. The Python policy says the 30-day window is exceeded. The model cannot override that. |
| 1:24–1:42 | Run Case A; click the approval button; pause on the large `Refund COMPLETED` result card and the Refund ID evidence card. | Case A is inside the window, so every check passes. A human approves, and only then does TradeOS call the PayPal Refund API. COMPLETED appears only after PayPal returns COMPLETED, with a real Sandbox Refund ID. |
| 1:42–1:55 | Honest cut labelled with the webhook wait; show `Signed PayPal notice: verified` and the PayPal trace ID card. | Then PayPal sends a signed webhook. We cut the wait. TradeOS checks the signature against PayPal's certificate: verified. |
| 1:55–2:10 | Click **Check against PayPal**; show `Checked against PayPal: all match` and the audit-chain badge. | PayPal's capture and refund are read again. All match. Every step is recorded in a SHA-256 hash-chained audit trail. |
| 2:10–2:30 | Failure & safety modes: Case R 422 → retry with same request ID; Case D double-click → one refund. | Failures stay honest. A forced refund failure never appears as success, and the retry reuses the same PayPal-Request-Id. A double click is refused. One refund. |
| 2:30–2:42 | Bottom evidence and top ribbon; end on tagline and links. | Basic web hardening is in. PayPal Sandbox, not live money; a Hackathon demo, not an audited production system. PayPal moves the money. TradeOS moves the work. |

---

## Previous version (v3, superseded: Case A was an exchange that ended in a refund)

# TradeOS demo video — v3 script (as recorded)

Recorded 2026-10-10 on the LIVE PayPal Sandbox site (https://tradeos-s33z.onrender.com, main `6fefb0d`) with Playwright (CDP screencast, 1280x624 CSS px at 1.5x = 1920x936), subtitles in a dedicated 144 px black band (1920x1080 total). Narration: edge-tts `en-US-AndrewNeural`, rate +5%. Server waits (order/capture creation, LLM call, refund call, webhook delivery) are cut with 0.4 s crossfades; the webhook cut is labelled on screen with the measured delay. Cases R and D were run on the live site just before recording (same session; demo reset before and after).
Total runtime: 162.0 s (under 3:00).

Principle: **AI understands, rules decide, humans approve, PayPal proves.** Tagline: **PayPal moves the money. TradeOS moves the work.** Claims match the Devpost draft; supplier routing is not part of the story.

## 0:00.00–0:21.08 · hook

**Screen:** Title cards over the live dashboard: the Spanish customer message, today's manual steps, the tagline.

**Voice:** A customer in Madrid writes: these sneakers are too small, can I swap a 42 for a 43? For a small merchant with no ops team, that's minutes of manual work: translate, check the date, find the PayPal capture, refund by hand. TradeOS turns it into one approval. PayPal moves the money. TradeOS moves the work.

## 0:21.08–0:33.81 · principle

**Screen:** Tagline + four principle chips; then the live dashboard, 'PayPal: Sandbox (live API)' chip highlighted.

**Voice:** The rule is simple. AI understands, rules decide, humans approve, PayPal proves. Everything you'll see runs live on PayPal Sandbox: real orders, captures and refunds.

## 0:33.81–0:52.30 · multi

**Screen:** Try it yourself → Chinese-language preset preset → Run (real Sandbox order + capture; server wait cut) → 'What the AI understood' (zh-Hant, EXCHANGE_REQUEST / SIZE_MISMATCH / EXCHANGE, 42 → 43, English summary), DRAFT note.

**Voice:** Here's a message in Chinese. TradeOS creates a sandbox order and capture, and the AI extracts only the intent: an exchange, a size mismatch, 42 to 43, plus an English summary for the merchant. It decides nothing, and the customer reply stays a draft.

## 0:52.30–1:08.20 · caseb

**Screen:** Run Case B (wait cut) → pipeline Policy ✕ / PayPal 'Refund API NOT CALLED · 0 calls' → policy reason, Refund API calls 0, Refund ID none.

**Voice:** Case B is the same request, bought 45 days ago. The Python policy says the 30-day window is exceeded. Refund not executed: the Refund API is not called. Zero calls, no Refund ID. The model cannot override that.

## 1:08.20–1:23.21 · casea

**Screen:** Run Case A (wait cut) → Awaiting human approval → click 'Approve & refund $49.99' (wait cut) → Refund COMPLETED card, real Sandbox Refund ID highlighted.

**Voice:** Case A is inside the window, so every check passes. A human approves, and only then does TradeOS call the PayPal Refund API. The screen says COMPLETED only after PayPal returns COMPLETED, with a real sandbox Refund ID.

## 1:23.21–1:38.22 · webhook

**Screen:** Chip 'Signed PayPal webhook: waiting…' → honest cut with an on-screen label giving the measured delay (16 s after the refund in this take) → 'verified ✓' → evidence summary (refund, PayPal debug ID, signed notice).

**Voice:** Next, PayPal sends a signed webhook. We cut the wait. TradeOS checked the signature itself, against PayPal's certificate: verified. The evidence panel shows the refund, PayPal's debug ID for support, and the signed notice.

## 1:38.22–1:56.37 · reconcile

**Screen:** Click 'Check against PayPal' → 'all match' → 'Audit trail intact: N entries, head …' badge with the honest-limit caption.

**Voice:** Check against PayPal re-reads the capture and refund straight from PayPal. All match. Every step is also in a SHA-256 hash-chained audit trail, and it's intact. That detects edits to stored records; it can't stop someone with database access from rewriting the whole chain.

## 1:56.37–2:16.36 · fail

**Screen:** Pre-run case R (same session, real Sandbox): HTTP 422 REFUND_FAILED_INSUFFICIENT_FUNDS with debug_id → retry COMPLETED. Pre-run case D: double-click evidence (2nd click refused; 2 calls, same Refund ID; one refund).

**Voice:** Failures stay honest. A forced PayPal refund failure shows as failed, never as success, and the retry reuses the same PayPal-Request-Id. A double click: TradeOS refuses the second click, and a replay to PayPal with the same request ID gets the same Refund ID back. One refund.

## 2:16.36–2:31.91 · limits

**Screen:** Card: basic hardening (CSP, Origin check on state-changing POSTs, rate limits); PayPal Sandbox, not live money; hackathon demo, not audited production.

**Voice:** The app also has basic web hardening: a content security policy, cross-site request checks and rate limits. To be clear, this is PayPal Sandbox, not live money, and a hackathon demo, not an audited production system.

## 2:31.91–2:41.96 · close

**Screen:** Card: tagline, principle, live demo + GitHub links.

**Voice:** PayPal moves the money. TradeOS moves the work. The live demo and source code are linked below.
