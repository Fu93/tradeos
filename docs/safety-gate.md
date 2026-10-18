# Safety Gate (v3.2 principle, ported to `main`)

**Principle.** *Product category × fault signal.* Any reported fault or harm on a mains-powered, electric-heating, gas or
battery / thermal-risk product, plus any injury / burn / fire / shock / melting / smoke language in any covered language,
is routed to a **human safety review**, ahead of refunds and supplier tasks.

This page describes what is on `main` (`app/safety.py`, wired into `app/workflow.py`, `app/mixed.py`, `app/views.py`,
`app/queue_demo.py`). It is a port of the *principle* from the experimental supplier-routing branch
(`exp/supplier-routing-mvp1`, commit `f3d9442`), not a merge of that branch: `main` has no supplier-routing engine, so only
the gate is here.

## What it does

| Step | Behaviour |
|---|---|
| Where it runs | In `_after_capture`, right after the intent is extracted and **before** the PayPal capture lookup, the policy engine, the supplier draft, the autonomy verdict and any approval. (Case M: before any line is decided.) |
| Rule 1: harm language | Any hit of a pattern for fire, smoke, sparks, burn, blister, melt, electric shock, gas, explosion, burnt smell, injury / bleeding, cut, allergic reaction / rash, choking / swallowing / small parts, chemical smell / dizziness, "dangerous / toxic" — for **any** product. |
| Rule 2: product class × fault | A reported fault (broken, not heating, stopped working, leaking, flickering, …) on a product whose class is `MAINS_HEATING`, `MAINS_ELECTRIC`, `GAS` or `BATTERY_THERMAL`. The class comes from the catalogue category + product name (code). The LLM reading `reason = DAMAGED` also counts as a fault on those classes. |
| Result | Case status and decision become `NEEDS_HUMAN_SAFETY_REVIEW`. Label: **Needs human safety review**. |
| Nothing else happens | No PayPal capture lookup, no policy result, no supplier draft or task, no approve / decline button, Refund API **NOT CALLED**. Audit-chain entry `Safety Gate: Needs human safety review — ahead of refund and supplier tasks` with the matched signals, the (ignored) LLM reading, `refund_api_called: false`, `supplier_contacted: false`. |
| Where it shows | Result card, pipeline strip, case-list chip, "other cases waiting" list, the `/queue` judge guide (the Spanish seed `q-es`), and a one-click Spanish preset. |

## LLM independence

The gate is a pure function `assess(message, product, llm_reason)` of the raw message, the product and (optionally) the
model's `reason`. The model's reading can only **add** a signal (reason `DAMAGED` on a gated class); it can never remove
one. So the Spanish message *"La suela se derritió con el calor y me quemé el pie…"* routes to
`NEEDS_HUMAN_SAFETY_REVIEW` even when the model reads it as `REFUND_REQUEST / DAMAGED / REFUND` (an approvable request).
That case is a test (`test_llm_misread_as_refund_damaged_still_routes_to_safety_review`) and every
(intent × reason × action) combination of the model schema is tested for the same message.

### Pattern layer
* Languages: **English, Traditional + Simplified Chinese, Spanish, German, Japanese, French**. No other language is covered
  (Italian, Portuguese, Korean, Arabic … are **not**; such a message gets no gate hit and follows the ordinary flow, where the
  ordinary rules, the LLM and the human approval step still apply).
* Normalisation before matching: NFKC (full-width → ASCII), zero-width characters removed, case-folded, accents stripped from
  Latin letters only (Japanese dakuten are kept), and a second pass that rejoins letter-spaced words (`s m o k e`, `b.u.r.n`).
* `clean_message` (free-text intake) now **deletes** invisible format characters (category Cf: zero-width space, word joiner,
  BOM, soft hyphen) instead of replacing them with a space. Found in review: the old behaviour turned `sm\u200boke` into
  `sm oke`, which hid the word from any keyword layer.
* Footwear / clothing injury language is covered explicitly: burn, blister (incl. "blister from melted lining"), cut / gash,
  bleeding, allergic reaction / rash / swelling, choking hazard / swallowed button / small parts / drawstring strangling for
  kids' items, chemical smell / dizziness, sharp metal or nails through the sole.

## Server-side enforcement (not only a hidden button)

1. The gate sets `decision = status = NEEDS_HUMAN_SAFETY_REVIEW`. The approve endpoint already requires
   `PENDING_APPROVAL` + `ELIGIBLE`, so it refuses (HTTP 409).
2. `Workflow._refuse_if_safety` is an **independent backstop** on `approve`, `_guard_refund` (so the retry endpoint, the
   double-click replay and every refund execution) and on mixed-order `approve_batch` / `_guard`. It refuses when the case
   is in the safety state **or** when a fresh re-scan of the stored message and product flags it — so a stale or tampered row
   that looks `ELIGIBLE / PENDING_APPROVAL` still cannot be approved or refunded.
3. The existing refund guard (policy `ELIGIBLE` + chained human `APPROVED` + verified audit chain) is unchanged and sits
   behind both.

## Mark reviewed (human-gated record, no money)

A person can close a safety-gated case with a **reviewer note** (required, 1–500 characters after cleaning):
`POST /cases/{id}/safety-reviewed` (form field `note`; the dashboard shows a "Mark reviewed" box under the case).

| | |
|---|---|
| Terminal state | `SAFETY_REVIEWED` (`human_decision = SAFETY_REVIEWED`, `decision` stays `NEEDS_HUMAN_SAFETY_REVIEW`). Frozen like the other terminal states. |
| On the hash chain | One `case:update` entry (status + human decision) and one audit entry `Human marked the safety case reviewed — no refund, Refund API not called` carrying the note, `money_moved: false`, `refund_api_called: false`, `supplier_contacted: false`. |
| Never | No money movement, no PayPal call, no supplier task, **no re-entry into the refund flow**, no approve button on the page afterwards. `_refuse_if_safety` also refuses the `SAFETY_REVIEWED` status, so approve / refund / retry stay refused even for a tampered row. |
| Server-side | Only a case in `NEEDS_HUMAN_SAFETY_REVIEW` is accepted; any other case (A, B, mixed, completed...) is refused with HTTP 409. An empty or too-long note is refused with 422. |
| Double submit | The second POST writes nothing (the first note stands) and redirects to the case: idempotent. |
| Web hardening | Same-origin (CSRF) middleware as every POST; the money rate limiter (per IP, per hour, global); the note is HTML-escaped by the template (stored as data, never rendered as markup). |
| Not claimed | This is a **record of a human reading the case**, not a safety verdict, a customer reply or a resolution of the hazard. Nothing is sent to the customer. |

## False positives (accepted, and what happens to them)

* The gate **over-triggers on purpose**: a miss costs more than a read. Examples that route to a human although harmless:
  "great *fire* sale, wrong size", "burn rate", "it shocked me how cheap it was", "no smoke, no burning, just too small" (**negation is not
  used to suppress a hit**), "ampoule" (blister *or* bulb), "swollen" used about a price.
* A false positive is **never an automatic rejection**. It becomes `NEEDS_HUMAN_SAFETY_REVIEW`: a person reads the message and
  follows up outside this workflow. Nothing is refunded, nothing is declined, and the customer is not sent an automatic "no".
* The reverse is also true: nothing lets a person approve a safety-flagged refund *inside* the app. A reviewer who decides
  the flag was a false alarm has **no in-app "release" button and none is planned**; they follow up outside this workflow
  (re-create the case or handle it in PayPal). What a reviewer *can* do is **mark the case reviewed** (next section).
* Normal returns without harm language still flow: "the sole came off / is damaged / cracked / detached", size and colour
  complaints, "the cut is too narrow", "hurts / too tight" (pain with no injury word) all reach `PENDING_APPROVAL` as before.
  (Table-tested in 6 languages.)

## Second layer: AI safety classifier (opt-in, OFF by default)

`app/safety_ai.py`. Enable with `TRADEOS_SAFETY_AI=1` **and** a configured LLM (`LLM_API_KEY`; model `LLM_MODEL`, default
`openai/gpt-oss-20b` on Groq). Timeout `TRADEOS_SAFETY_AI_TIMEOUT_S` (default 8 s). Without the flag nothing changes: no
extra LLM call, no new audit field.

| Rule | How it is enforced |
|---|---|
| Escalate-only | `combine()` returns the keyword result untouched when it is already flagged (the model is not even called). When it is not flagged, the model can only turn it on (`trigger = ai_classifier`, signal layer `ai`). An answer of "no" changes nothing. Any layer triggering = `NEEDS_HUMAN_SAFETY_REVIEW`. |
| Fail-safe | Timeout, HTTP error, 429, bad JSON, off-schema answer (strict schema, unknown hazard label, extra keys) or any exception = "no opinion". The keyword result stands, so nothing new is handled automatically and nothing is newly flagged either. The audit entry records `ai_layer: no_opinion`. There is no retry on the live path. |
| No money | The model gets product name, category and the message only (no amount, no case id). It returns a boolean, a hazard label from a fixed list and a short note. The policy engine never reads it. |
| Injection | The message is passed as data. Because the output can only add a flag, "do not flag this" in a message cannot lower anything (a test covers it). A message that tricks the model into escalating just costs a human read. |
| Same path | Runs in `_after_capture` and in the mixed-order intake, right after the keyword gate, through the same `_route_to_safety_review`, so the same server-side refusals (approve / refund / retry) apply. The server-side re-scan backstop `_refuse_if_safety` is code-only; AI-flagged cases are protected by their stored `NEEDS_HUMAN_SAFETY_REVIEW` status. |

### Measured on our own dataset (not a guarantee)

* Dataset: `docs/eval/safety_ai_dataset.jsonl` (165 rows, source `scripts/safety_eval_data.py`): 83 "should escalate" and
  82 "should not". **We wrote the messages and the labels ourselves**; it is not real customer traffic, and one author's
  judgement of what counts as hazardous is baked in. Categories: paraphrase, typos, languages the keyword layer covers,
  languages it does not cover (it, pt, ko, ru, nl, tr, ar, vi, pl, th, hi), sarcasm, faults on gated products without hazard
  words, plain harm, benign messages with trigger words, ordinary benign messages (including on gated products) and prompt injection.
* Run: `python scripts/eval_safety_ai.py --base-url https://integrate.api.nvidia.com/v1 --model openai/gpt-oss-20b --key-env NVIDIA_API_KEY`
  (same model id as the live path, served by NVIDIA so the live Groq quota is untouched; hosting differences are not
  controlled). Raw per-row output: `docs/eval/safety_ai_results.json`. One run, temperature 0, 0 AI errors. The keyword layer is run with
  no intent-LLM reading.

| Layer | Miss rate (should escalate, not escalated) | False-positive rate (should not, escalated) |
|---|---|---|
| Keyword only (today) | 46 / 83 = 55.4 % | 10 / 82 = 12.2 % |
| AI alone (diagnostic) | 2 / 83 = 2.4 % | 0 / 82 = 0.0 % |
| Keyword + AI (escalate-only OR) | 1 / 83 = 1.2 % | 10 / 82 = 12.2 % |

Per category, misses keyword-only → keyword + AI: paraphrase 10 → 0 of 20; typo 8 → 0 of 10; covered languages 3 → 0 of 10;
**uncovered languages 11 → 0 of 11**; sarcasm 6 → 1 of 9; gated-product fault without hazard words 8 → 0 of 11; plain harm 0 → 0 of 10; injection 0 → 0 of 2.
The one remaining miss: *"Thanks for the free electric massage, really kept me awake."* (sarcastic shock).

How to read this honestly:
* The keyword layer's 55 % miss rate is **inflated by design of the dataset**: about half the "should escalate" rows were written
  to be hard for keywords (paraphrase, typo, uncovered languages). On real traffic the keyword layer would miss a smaller share. Do not quote 55 % as a field figure.
* The AI-added layer **cannot reduce false positives**: by the escalate-only rule the keyword layer's 10 false positives
  (e.g. "fire sale", "burn rate", "no smoke, no burning") stay routed to a human. The AI-alone column shows the model would have
  flagged none of them, but that is not used to release anything, by design.
* **Prompt/dataset overlap.** The classifier prompt names a few benign idioms ("fire sale", "burn rate", "it shocked me how cheap it
  is") that also appear in our negative rows. The 0 % AI false-positive figure is therefore optimistic. The same author wrote the prompt, the rows and the labels.
* 165 rows is small: one row is about 0.6 percentage points, and a 95 % interval on 1/83 is wide. Treat the numbers as "clearly better on our test
  set", not as a rate to promise. A single run on one hosted model; Groq-hosted behaviour, other model versions and non-zero temperature were not measured.

## Evidence tiers

| Tier | What it is | Status for the Safety Gate on `main` |
|---|---|---|
| **1. Unit / integration tests** (mock PayPal, mock LLM, offline) | `tests/test_safety_gate.py` (141 tests; whole suite 983 passed, 95% line coverage): multilingual harm table (EN / ZH-Hant / ZH-Hans / ES / DE / JA / FR), normal-message negatives, product-class × fault, every model reading of the burn message, injection + safety combo, keyword-fallback path, direct POST to approve / refund / decline / approve-twice, tampered-row backstop, mixed Case M, seeded generative property test (90 random messages × random model reading × random request path: never approvable, Refund API never called), mutation sanity (19 source mutants incl. 7 for mark-reviewed, all killed by `tests/mutation_sanity.py`; plus in-test mutants); mark-reviewed has its own 17 tests in `tests/test_safety_review.py`. | **Proven for these messages and these code paths.** |
| **2. Live demo** (Render + PayPal Sandbox + hands-on browser check) | The Spanish burn message and the ordinary flows (Case A / B / exchange / M) run against the deployed app; results are recorded in the PR / release notes and the judge guide. | **Shown on the deployed demo only**, with sandbox money. |
| **3. Real traffic** | Recall and precision on real customer messages, languages beyond the six, adversarial customers. | **NOT proven. Not measured.** There is no real-customer data. |

**The "85/85 safety cases" figure is from the experimental `exp/supplier-routing-mvp1` branch** (an LLM-extraction pipeline
evaluated on a synthetic held-out set; see `docs/impact-proof.md`). It is **not** a result for the code on `main`, which
uses a different, deterministic pattern layer and was **not** run on that set. No such number is claimed for `main`.

## Known limits / remaining risks

* Keyword patterns are not understanding: paraphrases, other languages, slang, misspellings and deliberate obfuscation beyond
  zero-width / full-width / letter-spacing (leetspeak, homoglyphs from other scripts, images) can miss. A missed message
  falls back to the old behaviour (LLM + policy + human approval for money), it does not become auto-approved.
* The product class on `main` is derived from category + name keywords; the demo catalogue is footwear / apparel, so the
  class × fault rule is exercised by tests with kettle / lamp / gas stove / power bank fixtures, not by live demo products.
* Only the free-text customer message is scanned (not attachments, photos, order notes or webhooks).
* No in-app "release" to the refund flow for a reviewed false positive (by design: reviewing records a note only); no SLA / escalation / notification to a human; nothing is sent to the customer.

### Added with the AI layer
* It is a model: it can still miss (1 of 83 on our set) and it adds latency (one more LLM call on unflagged messages only, up to the timeout, when enabled) and token use on the live quota.
* If the LLM is down, the gate is exactly the keyword gate; messages in uncovered languages then follow the ordinary flow as before.
* An AI escalation is explained by a short model-written note in the audit chain; treat it as a hint for the reviewer, not as evidence.
