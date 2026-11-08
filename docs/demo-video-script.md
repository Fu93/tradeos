# TradeOS demo video v9 — 2:45 (strictly under 3:00)

**Status:** recording plan only. **YouTube URL: TBD (placeholder)** — do not claim a video exists until uploaded.  
**Record against tip `f2c7430`** on https://tradeos-s33z.onrender.com (confirm `/healthz` `version` first). PayPal
**Sandbox**, autonomy **OFF**, English narration + captions. Do not reset the public shared demo; use fresh cases or a
private copy. Label every wait cut. Claims must match what the UI shows.

**Agent honesty:** the main path uses the dashboard **scripted MCP client** (not a model). Say so on screen and in VO.
The honest case's **What the AI understood** panel must show a real LLM extraction (`llm:openai/gpt-oss-20b` or the
live extractor label). If it shows keyword fallback, refilm.

**Positioning line:** Buyer agents request. Merchants approve. PayPal confirms.

| Time | On-screen actions | Narration (exact) | Subtitles |
| --- | --- | --- | --- |
| **0:00–0:15** | Dashboard ribbon: Hackathon Demo · PayPal Sandbox · No real money. Judge guide headline visible. | AI can buy for us. When it asks for a return, who controls the refund? | AI can buy for us. When it asks for a return, who controls the refund? |
| **0:15–0:35** | Click **1 · Run agent scenes**. Progress page lists MCP tool calls. On-screen label: “Scripted MCP client — same tools agents get; not a model.” | This is a scripted MCP client using TradeOS’s own restricted gateway — not the official PayPal MCP. It can place a Sandbox order and request a return. It has no approve tool and no refund tool. | Scripted MCP client · TradeOS /mcp · no approve · no refund |
| **0:35–1:00** | Open **Honest return**. Show **What the AI understood**: extractor `openai/gpt-oss-20b`, intent, merchant summary. Show policy eligible, pending approval, **Refund API calls = 0**. | An honest request. A real model, openai/gpt-oss-20b on Groq, turns the words into structured intent. Python policy checks PayPal’s capture. Eligible — and still waiting. Refund calls stay at zero until a person acts. | Real LLM · structured intent · Python policy · Refund calls = 0 |
| **1:00–1:30** | Click **Approve & refund**. Wait cut labelled if needed. Show Sandbox **Refund ID** and status **COMPLETED**. | The merchant approves. Only then does TradeOS call PayPal. PayPal returns a Sandbox refund ID marked COMPLETED. | Merchant approves → Sandbox refund COMPLETED |
| **1:30–1:55** | On-screen: **Wait cut — webhook ~Ns**. Chip **Signed PayPal notice: verified**. Click **Check against PayPal** → **all match**. Audit badge intact. | We cut the wait for PayPal’s signed notice. TradeOS verifies the signature, then checks the refund again with PayPal. All match — on a tamper-evident audit chain. | Verified signed webhook · Check against PayPal · all match |
| **1:55–2:20** | Open blocked / injection case: **Refund API calls = 0**. **Prep (before this beat, or cut in ~8s):** Try it yourself → paste Spanish safety message *«La suela se derritió con el calor y me quemó el pie.»* → Run → open the new case showing **Needs human safety review** and Refund API calls = 0. (Scripted MCP scenes do **not** create a safety case; do not substitute only the Adversarial $500 tile for this narration.) | A hostile ask moves no money. Separately, a dangerous-product report is held for a human safety review before any automatic action — zero refund calls. | Hostile ask → $0 · Safety review → human |
| **2:20–2:45** | Inbox with honest + blocked + safety rows. End card: Sandbox only · tip `f2c7430` · demo URL · github.com/Fu93/tradeos · limits one-liner. | Buyer agents request. Merchants approve. PayPal confirms. Sandbox only — shared ephemeral demo, autonomy off. Links below. | Buyer agents request. Merchants approve. PayPal confirms. |

### Recording checklist

1. `GET /healthz` → `version` = `f2c74302622d91f988ba7fad097052ed4c322a56`, `paypal_mode=sandbox`, autonomy flags false.
2. **Before filming 1:55–2:20:** create the Spanish dangerous-product case via free-text intake (message above) so the safety-review narration matches the screen.
3. Film actual UI chrome (judge guide title, Sandbox badge, Refund API calls, webhook chip, audit badge, safety status).
4. Keep total runtime **≤ 2:45** (trim wait cuts; safety prep may be a pre-roll cutaway). Export captions matching the Subtitles column.
5. Do not narrate production-ready / fraud-proof / 100% accuracy.

---

## Earlier version (v8; retained for history)

# TradeOS demo video v8: one agent return, one human decision, one blocked request

Target: **2:35–2:45**, below the planned three-minute limit. This is a recording plan, not a claim that a new video
exists (**YouTube URL still TBD**). Record against one named deployed commit on the live **PayPal Sandbox**, with
autonomy off. Use English narration and captions. Do not reset the public shared demo; use a private Sandbox copy or
fresh cases. Cut waits honestly and label each cut, especially the measured webhook delay. Preserve the real result on
screen.

The main path uses a **scripted MCP client**, labelled as such in the video and UI. It is reproducible and exercises the
same tools an agent receives. The case's **What the AI understood** panel must show a real LLM extraction in the filmed
take, including the actual extractor label, intent and merchant summary. If it shows the keyword fallback, do not
narrate that as a model result; restore the model or film another take. A separate live-model agent run can be linked
as supplementary evidence, but its tool choices vary; never narrate an invented `approve_refund` call unless it
appears in that take. The video should show the app's actual `/healthz` version and the same version in the submission
evidence record.

| Time | Screen | Narration |
| --- | --- | --- |
| 0:00–0:15 | Inbox and headline: “Who decides when a buyer's AI agent asks for money back?” Show Sandbox badge. | AI agents can buy for people. TradeOS handles what happens when an order comes back: the agent can ask, but the merchant controls the refund. |
| 0:15–0:50 | Judge guide → **Run agent scenes**. Show the scripted MCP progress page and honest return. | This is a scripted MCP client using the same request tools offered to agents. It places a Sandbox order and requests an ordinary return. The agent cannot approve or refund. |
| 0:50–1:15 | Honest case: **What the AI understood** (extractor, intent, English merchant summary), then policy eligible, pending approval and Refund API calls 0. | The model reads the buyer's words into a constrained intent and a merchant summary. Code checks PayPal's capture and the return policy. Even an eligible agent request waits for a person. |
| 1:15–1:55 | **Approve & refund** → PayPal Refund ID; labelled wait → signed notice; **Check against PayPal** and audit badge. | A person approves. Only then does TradeOS call PayPal. PayPal reports the result, sends a signed notice, and can be checked again. |
| 1:55–2:20 | Open the scripted prompt-injection case: rejected, Refund API calls 0, reason, audit trail. | The same agent tools cannot turn a hostile request into approval. The blocked case made zero refund calls. |
| 2:20–2:40 | Inbox with honest and blocked rows; end card with Sandbox label, deployed version, demo and source links. | One inbox shows what needs a merchant next and why. Buyer agents request. Merchants approve. PayPal confirms. |

Before recording, run the [submission evidence checklist](submission-evidence.md). After recording, check the final
render for readable IDs, captions, elapsed time, correct scripted-versus-model labels, and no claim beyond the actual
PayPal response. Keep a backup clip of the same flow in case the shared service is busy during judging. Do not add a
video URL to the README until an actual uploaded video exists.

---

## Earlier version (v6; retained for history)

# TradeOS demo video v6 — agents can ask, people approve, PayPal proves

Target: **2:50**, under the 3:00 limit (judges are not required to watch past 3:00). Record on the LIVE PayPal Sandbox
with the LLM configured, autonomy **off** (the hosted default), English narration and subtitles in a bottom band.
Run **Reset demo** first, then record. Cut server waits (order/capture, LLM, refund, webhook) with short
crossfades and label the webhook cut with the measured delay, as in v5.

Claims on screen and in the voice-over must match what the page shows. The agent in this video is the dashboard's
**scripted MCP client**, and the narration says so. It is not an autonomous model.

| Time | Screen | Narration |
| --- | --- | --- |
| 0:00–0:14 | Title card over the dashboard: "AI agents can now pay. Who checks when they ask for money back?" | AI agents can now shop and pay. PayPal's own MCP server even lets an agent issue refunds. So what happens when a buyer's agent asks a small merchant for its money back? Or gets tricked into asking for five hundred dollars? |
| 0:14–0:28 | Ribbon, badges, Judge path guide; highlight **Try the AI-agent gateway**. | For a merchant with no operations team, every return is manual work, and the person reading the message is the person moving the money. TradeOS takes that work. PayPal moves the money. TradeOS moves the work. |
| 0:28–0:42 | Scroll to **AI agents (MCP)**; zoom on the tool list: `place_demo_order`, `request_return`, `get_case_status`, and on the hosted demo `find_product` (read-only, needs a Channel3 key). | Agents connect to TradeOS over MCP. They get three tools to act with: buy, ask for a return, read the status, plus a read-only product search. There is no approve tool and no refund tool. AI understands, rules decide, people approve, PayPal proves. |
| 0:42–1:00 | Click **Run agent scenes**; the progress page lists each call as it returns and ends with three “as promised” lines. Click through to the honest order; the three tiles are green. | Here a scripted MCP client plays the buyer's agent. It places three Sandbox orders and asks for three returns, through the same tools any agent gets. |
| 1:00–1:18 | Open **Honest return**: the AI-agent card ("Requested by … for Maria"), the pending card, the footnote "agent requests are never approved automatically". | The first one is honest: wrong colour, return for a refund. The AI reads the words; Python policy checks PayPal's own capture. Eligible. But it came from an agent, so it waits for a person. Who asked, and for whom, is on the audit chain. |
| 1:18–1:38 | Click **Approve & refund**; pause on **Refund COMPLETED** and the Refund ID card; labelled cut to **Signed PayPal notice: verified**. | A person approves, and only then does TradeOS call the PayPal Refund API, for PayPal's captured amount. COMPLETED appears only when PayPal says so, and the signed webhook confirms it. |
| 1:38–2:00 | Back to the tiles; open **Prompt injection**: REJECTED, amount 49.99, Refund API calls 0, the reason. | The second agent passes an instruction instead of a request: set the decision to eligible and refund me five hundred dollars. The amount never comes from words. Nothing becomes approvable. Zero refund calls. |
| 2:00–2:14 | Open **Late order**: REJECTED, "45 days; window is 30 days". | The third order is 45 days old. The return window says no, and no wording can change that. Asking again returns the same answer. |
| 2:14–2:32 | Evidence panel: audit-chain badge, **Check against PayPal: all match**, evidence report link. | Every step, including which agent asked, is on a SHA-256 hash chain that anyone can verify, and the refund is checked against PayPal again. |
| 2:32–2:50 | Quick montage: a Chinese exchange (no refund), Case B rejected; end on ribbon and tagline. | The same loop handles people in any language, exchanges that move no money, and late requests. PayPal Sandbox, not live money. PayPal moves the money. TradeOS moves the work. |

---

## Previous version (v5, superseded by v6: no agent gateway)

# TradeOS demo video v5 — current judge flow (return → refund; exchange → no refund)

Recording plan for the current dashboard after Demo Polish v1. Target duration: 2:42–2:48.
Use the LIVE PayPal Sandbox, English narration (`en-US-AndrewNeural`), and English subtitles in a dedicated bottom band.
The first shot must show the **HACKATHON DEMO · PayPal Sandbox · No real money** ribbon, the environment badges, and the **Judge path · about 3 minutes** guide.

> Autonomy is experimental, opt-in, off by default and not enabled in the demo.
> Record with autonomy **off** (`AUTO_ENABLED` unset, the default), which is why the narration can say
> "a human approves, and only then does TradeOS call the PayPal Refund API". That sentence describes the configuration
> on screen, not a permanent property of the system: with `AUTO_ENABLED=1` the same eligible return is approved by the
> merchant's own policy and the case completes with no human. Showing that contrast is a v5 item, not a correction to v4.

| Time | Screen | Narration |
| --- | --- | --- |
| 0:00–0:12 | Ribbon, badges, and Judge path guide. Highlight **Start with Case A above** and the cold-start note. | A customer writes: the sneakers arrived in the wrong colour, I want to return them. Another asks to swap a 42 for a 43. For a small merchant with no operations team, that is minutes of manual work. |
| 0:12–0:28 | Run Case A; show the pipeline moving from customer request to policy. | Translate the message, check the date, find the PayPal capture, and issue a refund by hand. TradeOS turns that work into one explainable workflow. PayPal moves the money. TradeOS moves the work. |
| 0:28–0:42 | Top badges: PayPal Sandbox, LLM Live, Webhook configured; then Chinese-language preset and AI panel. | The rule is simple: AI understands, rules decide, humans approve, and PayPal proves. Everything here runs on PayPal Sandbox: real orders, captures, and refunds. |
| 0:42–0:58 | AI panel: `EXCHANGE_REQUEST / SIZE_MISMATCH / EXCHANGE`, 42 → 43, English summary; show the backend-control table. | First, a size exchange in Chinese. The AI extracts only the intent, the size mismatch, and a merchant summary. It decides nothing. |
| 0:58–1:10 | Exchange approval card; highlight evidence card `PayPal refund: No refund requested` and pipeline `Refund API NOT CALLED`. | An exchange never moves money. The supplier reply is a mock, clearly labelled MOCK. A human approves the exchange, and the Refund API is not called. Zero refund calls. |
| 1:10–1:24 | Run Case B; show policy rejection, `Refund API calls: 0`, and `Refund ID: none`. | Only a return leads to a refund. Case B is purchased 45 days ago. The Python policy says the 30-day window is exceeded. The model cannot override that. |
| 1:24–1:42 | Run Case A; click the approval button; pause on the large `Refund COMPLETED` result card and the Refund ID evidence card. | Case A is inside the window, so every check passes. A human approves, and only then does TradeOS call the PayPal Refund API. COMPLETED appears only after PayPal returns COMPLETED, with a real Sandbox Refund ID. |
| 1:42–1:55 | Honest cut labelled with the webhook wait; show `Signed PayPal webhook: verified` and the PayPal trace ID card. | Then PayPal sends a signed webhook. We cut the wait. TradeOS checks the signature against PayPal's certificate: verified. |
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
