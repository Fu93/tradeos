# Safety Gate (v3.2 principle, ported to `main`; rule 3 added in 3.3)

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
| Where it runs | In `_after_capture`, right after the intent is extracted and **before** the PayPal capture lookup, the policy engine, the supplier draft, the autonomy verdict and any approval. (Case M: on the message at intake, then line by line with each line's own reading, before any line is decided.) |
| Rule 1: harm language | Any hit of a pattern for fire, smoke, sparks, burn, blister, melt, electric shock, gas, explosion, burnt smell, injury / bleeding, cut, allergic reaction / rash, choking / swallowing / small parts, chemical smell / dizziness, "dangerous / toxic" — for **any** product. |
| Rule 2: product class × fault | A reported fault (broken, not heating, stopped working, leaking, flickering, …) on a product whose class is `MAINS_HEATING`, `MAINS_ELECTRIC`, `GAS` or `BATTERY_THERMAL`. The class comes from the catalogue category + product name (code). The LLM reading `reason = DAMAGED` also counts as a fault on those classes. |
| Rule 3 (3.3): hazard-class products need a clear reason | On those four classes, a return skips the review **only** when the model read it as `SIZE_MISMATCH`, `WRONG_ITEM` or `CHANGED_MIND`. Any other reading (`DAMAGED`, `NOT_AS_DESCRIBED`, `OTHER`, `UNKNOWN`) goes to a person, whatever words were used. Order-status questions (`ORDER_STATUS`) are not returns. Rules 1 and 2 still apply on top. |
| Result | Case status and decision become `NEEDS_HUMAN_SAFETY_REVIEW`. Label: **Needs human safety review**. |
| Which rule judged it | The rule version (`SAFETY_RULE_VERSION`, now `safety-gate/3.3.0-main`) is written to the case's hash chain: in the safety entry when the gate holds a case, in the `Intent extracted` entry (`safety_gate: {flagged, rule_version}`) when it does not. Case M's per-line hold writes it in its safety entry. |
| Nothing else happens | No PayPal capture lookup, no policy result, no supplier draft or task, no approve / decline button, Refund API **NOT CALLED**. Audit-chain entry `Safety Gate: Needs human safety review — ahead of refund and supplier tasks` with the matched signals, the (ignored) LLM reading, `refund_api_called: false`, `supplier_contacted: false`. |
| Where it shows | Result card, pipeline strip, case-list chip, "other cases waiting" list, the `/queue` judge guide (the Spanish seed `q-es`), and a one-click Spanish preset. |

## Why rule 3: stop growing the word list (3.3, 2026-10-25)

Rule 2 asked "did the customer use one of our fault words?". A live check on a gated kettle found that half of 78
plausible fault descriptions got past it: "doesn't turn on", "keeps tripping", "hot to touch", "smells odd", "frayed
cord", "battery bulging". Adding those words would fix those 39 and miss the next 39; a list of every way to describe a
fault does not exist. A list of reasons that say nothing about how a product works does: wrong size, wrong item, changed
mind. So for hazard-class products the question is now the second one, and the word lists stay only as an extra layer
(and as the whole gate for products that are not hazard-class).

Measured with [`scripts/eval_gate_phrasings.py`](../scripts/eval_gate_phrasings.py) on
[`docs/eval/gated-phrasings.json`](eval/gated-phrasings.json) (50 messages written for this check, on a kettle, a gas
stove, a power bank and a power strip). Every reading and outcome is in
[`gated-phrasings-results-keyword.json`](eval/gated-phrasings-results-keyword.json) (keyword reader) and
[`gated-phrasings-results-llm.json`](eval/gated-phrasings-results-llm.json) (live model):

| Messages (judgements) | 3.2, no model reading | 3.3, keyword fallback (LLM down) | 3.2 + live model reading | **3.3 + live model reading** |
|---|---|---|---|---|
| Faults the word lists miss (120) | 0 | 120 | 80 | **120** |
| Faults the word lists know (32) | 32 | 32 | 32 | **32** |
| Harmless returns: false positives (48) | 0 | 40 | 0 | **4** |

Live column: one run of the script on 2026-10-25 (12:25–12:35 London) with `openai/gpt-oss-20b` on Groq, rule
`safety-gate/3.3.0-main` at `99dc962`, `--pace 10`. Every message got a model reading; none fell back to the keyword reader.

* **In this set, all 30 fault phrasings that the word lists miss were held.** With the same model readings, 3.2 held 80
  of the 120 judgements (the model read 20 of the 30 messages as `DAMAGED`). The 40 that only rule 3 holds are 10
  messages the model read as `UNKNOWN` or `NOT_AS_DESCRIBED`, among them "It doesn't turn on", "The handle gets hot to
  touch", "It smells odd" and "It gave me a tingle". So rule 3 matters with the model on, not only when it is down.
* What 3.2 did with those 10, replayed through the app on the kettle only, with the same readings: 9 were refused by the
  policy (reason `UNKNOWN`), and 1 ("The base is wet after every use.") reached the approval step. Either way no person's
  safety review saw a fault report. Under 3.3 all 10 go to that review.
* **One harmless message is held**, on all four products: "The colour is not what the listing showed."
  (`NOT_AS_DESCRIBED`), so 1 message of 12. That is deliberate: `NOT_AS_DESCRIBED` is **not** a clear reason, because a hidden
  fault is often described that way, so a kettle in the wrong colour waits for a person. Change of mind, no longer needed,
  a gift, found it cheaper, ordered twice, wrong size, wrong item and an order-status question all pass.
* With the LLM down the keyword reader reads almost every message as `UNKNOWN`, so 40 of 48 harmless judgements go to a
  person: fail closed, by design.

**What these numbers are not.**
* There are 50 messages, written by us for this check; this is not customer traffic.
* Each message is read once and judged on four products, so the effective sample is 50 readings, not 200 independent
  judgements.
* This is one run. The model's output can differ from run to run.
* The set has no message giving two reasons and no non-English message. 120 / 120 and 32 / 32 are therefore not a recall
  rate for real customers. The known gap below (two reasons in one message) is not measured: its Chinese form ("I
  changed my mind, but it keeps tripping") passed once in a hand check, and the English form was held in the same check.

3.3 only adds reviews: `tests/test_safety_reasons.py` compares it with the released 3.2, frozen in
`tests/reference/safety_3_2.py` (not the new code with an argument dropped), over thousands of message × product ×
reading × intent combinations, and checks that nothing 3.2 flagged is unflagged. What that does and does not mean for the
published figures:

* The figures measured for `main` (17 / 85 on the v4 held-out set, 33 / 100 on CPSC, below) were measured with
  `llm_reason=None`, where rule 3 never fires; they are unchanged, not improved. They were not re-run.
* **85 / 85 is not a `main` figure**, before or after 3.3: it comes from the experimental branch (see Evidence tiers).
  This change says nothing about it.
* What does change is the share of hazard-class returns a person reads: it rises.

`scripts/eval_gate_phrasings.py` stops, writing nothing, if `LLM_API_KEY` is missing or the model fails on any message
(TradeOS then answers with the keyword reader): a live result half made of keyword readings would not be a live result.

## LLM independence

The gate is a pure function `assess(message, product, llm_reason, intent)` of the raw message, the product and
(optionally) the model's `reason` and `intent`. The model's reading can only **add** a signal (on a gated class: reason
`DAMAGED`, or since 3.3 any reason other than the three clear ones); it can never remove one. So the Spanish message *"La suela se derritió con el calor y me quemé el pie…"* routes to
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

**Off on the hosted demo, on purpose.** The demo's `LLM_API_KEY` is on Groq's **free tier**. Each case already makes about
two model calls (intent and note translation); the classifier would add a third to every message the keywords do not flag.
Free-tier rate limits ([Groq rate limits](https://console.groq.com/docs/rate-limits)) would then be reached sooner when
several judges use the demo at once, and on a 429 the layer gives "no opinion", so it would silently be absent exactly
when it is busiest. So the hosted demo runs the keyword layer only, and the numbers below are from offline runs, not
from the hosted demo.

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

### Real consumer hazard reports (CPSC SaferProducts.gov, recall only)

Real, human-written report narratives: 100 of them, all describing a harm or a risk of harm, labelled by hand before any
run, with no keyword tuning. Details, licence and rubric are in [`docs/eval/cpsc_real_text.md`](eval/cpsc_real_text.md).
**Keyword only** (what the hosted demo runs): **34 / 100 missed**. AI alone: 4 / 100. Keyword + AI: 3 / 100. This
measures recall only: the set has no benign rows, so false positives on real text are **not** measured. These are
reports to a regulator, in English, not merchant support traffic.

## Evidence tiers

| Tier | What it is | Status for the Safety Gate on `main` |
|---|---|---|
| **1. Unit / integration tests** (mock PayPal, mock LLM, offline) | `tests/test_safety_gate.py` (144 tests) and `tests/test_safety_reasons.py` (42 tests, rule 3; whole suite 1609 passed, 95.94% line coverage, CI on 2026-10-25 at 99dc962): multilingual harm table (EN / ZH-Hant / ZH-Hans / ES / DE / JA / FR), normal-message negatives, product-class × fault, every model reading of the burn message, injection + safety combo, keyword-fallback path, direct POST to approve / refund / decline / approve-twice, tampered-row backstop, mixed Case M, seeded generative property test (90 random messages × random model reading × random request path: never approvable, Refund API never called), mutation sanity (19 source mutants incl. 7 for mark-reviewed, all killed by `tests/mutation_sanity.py`; plus in-test mutants); mark-reviewed has its own 17 tests in `tests/test_safety_review.py`. | **Proven for these messages and these code paths.** |
| **2. Live demo** (Render + PayPal Sandbox + hands-on browser check) | The Spanish burn message and the ordinary flows (Case A / B / exchange / M) run against the deployed app; results are recorded in the PR / release notes and the judge guide; the 3.3 re-check of 2026-10-25 is listed below the table. | **Shown on the deployed demo only**, with sandbox money. |
| **3. Real traffic** | Recall and precision on real customer messages, languages beyond the six, adversarial customers. | **NOT proven. Not measured.** There is no real-customer data. |

**Live re-check of 3.3 (tier 2 detail).** After #86 and #87 were deployed (Render deploy `dep-dbeurbqvcj2c73e8ee10`, commit `99dc962`, rule `safety-gate/3.3.0-main`, live at 2026-10-25 11:54 London), the deployed demo was checked the same day against PayPal Sandbox and the real Channel3 catalogue. **Each item is one run, one sample, sandbox money only; none is a rate.**

* **Camping stove (the earlier miss):** a Jetboil Flash with "It stopped working after two days, please refund me." was held as **Needs human safety review**, class `GAS`, Refund API calls 0, audit chain intact. The T-shirt control with the same message was not held (waited for a person's approval).
* **Electric kettle:** "It keeps tripping the breaker" and "The colour is wrong, I'd like a refund" were **held** (rule 3: the model read `OTHER` and `NOT_AS_DESCRIBED`). "Wrong size, can I exchange it?" and "I changed my mind" were **not held** (waited for a person's approval, 0 refund calls).
* **Demo flows unaffected:** Case A and Case M waited for approval with no safety hold; the Spanish burn message was held (the `/queue` example, and once through the agent gateway); a "too small" return of the default sneakers through the agent gateway waited for approval. That last run called the gateway tools directly with a fixed message; the model-driven "Shop, buy, return" button was not re-run live.
* **Sandbox verification script on the deployed `99dc962`:** default run 31/31 PASS, `--mixed-only` 16/16 PASS (`--multi-batch-only` not re-run).
* Every new case carried the rule version on its hash chain except the seeded `/queue` example and an un-held Case M (its intake writes the version only when a line is held), and every checked chain verified.

**The "85/85 safety cases" figure is from the experimental `exp/supplier-routing-mvp1` branch** (an LLM-extraction pipeline
evaluated on a synthetic held-out set; see `docs/impact-proof.md`). It is **not** a result for the code on `main`, which
uses a different, deterministic pattern layer and was **not** run on that set. No such number is claimed for `main`.

## Product class: plural categories (fix, 2026-10-25)

**Defect found live.** Channel3 sends a category *path* whose leaf is plural ("Sporting Goods > … > Camping Stoves",
"… > Hair Dryers", "… > Space Heaters", "… > Toasters"). The class rules were written in the singular with a word
boundary (`camp(ing)? stove`, `heater`, `hair ?dryer` …), so a plural-only leaf matched nothing: a Jetboil Flash
(`find_product "Jetboil Flash"` -> `S2QsLVh`, title without a hazard word) with the plain message "It stopped working after
two days, please refund me." had class `NONE` and was not held. Even the root "Household Appliances" did not match
`appliance`.

**Fix 1: plural-aware matching (`app/safety.py`).** `class_text()` normalises the name + category before the class rules
read them: NFKC / case-fold / accents as before, then every run of non-letters (hyphen, `>`, `&`, comma, slash) becomes one
space and every word is reduced to a conservative singular (`stoves` -> `stove`, `batteries` -> `battery`, `torches` ->
`torch`; `gas`, `glass`, `bus`, words under 4 letters and -ss / -us / -is words are left alone). The rules are written for
that form (`e-?bike` -> `e ?bike`). `stove` replaces "camp(ing) stove" / "gas stove" (so "Portable Cooking Stoves", "Wood
Stoves"); `straightener`, `steamer`, `hot air`, `surge` cover leaves with no other hazard word.

**Fix 2: a short documented allowlist of non-hazard leaves (`NON_HAZARD_LEAVES`).** Plural matching exposed leaves that
contain a hazard word without being a hazard device ("Hair Extensions", "Pipe Caps & Plugs", "Tool Sockets", hardware
"Washers", "Dutch Ovens", "Double Boilers", bicycle / tow / steering "Cables", fireplace grates, andirons and log racks,
studio softboxes ...). Each entry is the last two segments of a category path ("parent > leaf"). Only an exact two-segment
match exempts, so a path cut short by the 120-character limit (parent missing) is **not** exempt and stays gated. An exempt
category adds no words; the leaf's own phrase is also removed from the product name, but every other word of the name is
still read (a "Heated Hair Extensions Clip" in the Hair Extensions category is still `MAINS_HEATING`). This is the only
place a category can lose a hazard word. Every entry has a test, a test that the entry is *needed* (without it the path is
gated), and its hazard neighbours (Firewood & Fuel, Wood Stove Fans & Blowers, Pressure Cookers & Canners, Stovetop Kettles,
Sauna Heaters, Plumbing / Diving Regulators, Riding Scooters, Cement Mixers ...) are tested to stay gated.

**Fix 3: gap words found by a sweep of the taxonomy.** Added (all escalate-only), each because a real hazard leaf had no
other matching word: `lighting`, `electrical`, `generator`, `inverter`, `power tool`, `power drill`, `powered`,
`compressor`, `welder`, `plasma cutter`, `welding gun` (mains); `torch`, `fuel`, `gasoline`, `kerosene`, `oxygen tank`,
`fireplace` (gas / fuel); `heat gun`, `heat tool`, `glue gun`, `wood burning`, `sauna`, `steam cleaner / inhaler / mop / press /
generator`, `bottle / wax / plate / dish / oil / stone / food / beverage / bed / foot warmer`, `hot dog roller` (heating);
`flashlight`, `headlamp`, `jump starter`, `robotic toy`, `remote control` toys (battery). Deliberately **not** added
(too many non-hazard children, see "Remaining gaps" in the PR): `power equipment` (53 categories, mostly mower blades, belts,
tyres), `candle`, `incense`, `firework`, `massage`, `treadmill`, `amplifier`, `saw`, `pump`.

The rules only ever gained matches except through the allowlist: **0 of 5,595 taxonomy categories that `main` gated lost
their gate**, and the allowlist touches only categories `main` did not gate. Class labels can change inside the gated set
(kettle `MAINS_ELECTRIC` -> `MAINS_HEATING`, "Batteries" `MAINS_ELECTRIC` -> `BATTERY_THERMAL`); all four classes are gated
identically, so no decision changes because of a label.

**Measured (offline, keyword layer only, `llm_reason=None`).**

| Set | `main` | Round 1 (plural only) | Now |
|---|---|---|---|
| 165-row self-authored eval (fixtures are singular) | 46 / 83 missed, 10 / 82 false positives | identical | identical |
| CPSC 100 real narratives (keyword only) | 34 / 100 missed | 33 / 100 | 33 / 100 (id 33, a gasoline can, category "Fuel, Lighters and Fireworks": "Lighters" now reaches `GAS`) |
| 308-item held-out v4 set, harm rule (no catalogue product in that set) | 17 / 85 safety cases flagged, 3 / 223 others | identical | identical (same 20 ids) |
| Google Product Taxonomy 2021, 5,595 paths, neutral name: gated | 674 (12.0 %) | 899 (16.1 %), newly gated 225 | 967 (17.3 %), newly gated **293**; 0 lost |

Of the 293 newly gated: 193 come from plural / hyphen matching (225 minus 32 removed by the allowlist) and 100 from the gap
words. The frozen CPSC results file is **not** rescored (`tests/test_cpsc_eval_data.py` pins the one row that flips); the v4
set and its frozen results are untouched.

**Honest limits.** (1) The taxonomy rows are category lists, not traffic. The file is the 2021 Google taxonomy; 13 of the 30
real Channel3 paths seen on the demo are not in it (Channel3's is newer), so the allowlist keys, taken from the 2021 file, can
miss a renamed parent. That fails safe: the category stays gated. (2) About 28 of the 293 are leaves I left gated on purpose
although they may not be hazards (Riding Scooters, Plumbing / Diving Regulators, Cement Mixers, Stovetop Kettles,
Chandeliers, Wall Plates, Lighting Timers, Wire Terminals, Water Filters, Firewood & Fuel ...): uncertain means gated.
(3) `stove` also covers electric and wood stoves and is labelled `GAS`. (4) Candles, incense, fireworks and ear candles are
**not** a gated class (decision): a fault word alone on a candle is an ordinary return, and fire / smoke / burn words are
caught by rule 1 for every product; an open-flame class needs a product decision. (5) English plurals only. (6) A product
whose title and category carry no known word is still `NONE`: the class rule is keywords, not understanding. (7) The
fault-word list is unchanged and has gaps: "doesn't turn on", "does not power on", "keeps tripping", "stopped heating",
"not charging", "hot to touch", "smells odd", "busted", "DOA" are not escalated by keywords alone (the intent model's
`DAMAGED` reading can add a flag on a gated class in the live flow; that was not measured here). Those are proposals, not part of this change.

## Known limits / remaining risks

* For hazard-class products (rule 3) a missed fault now needs the model to read it as wrong size, wrong item or a change
  of mind. In one live run on 50 messages we wrote ourselves, the model did that for none of the 30 faults (see "Why rule
  3"); that is not a rate for real customers. With the LLM down, harmless returns of those products go to a person
  (40 / 48 in the offline measurement).
* **One reason per message.** The extractor gives one reason. "I changed my mind, and it keeps tripping" can be read as
  `CHANGED_MIND`; "too small, and the cord is frayed" is `SIZE_MISMATCH` to the keyword reader. Neither is held when the
  fault words are on no list. Not fixed: pinned as a known gap in `test_known_gap_two_reasons_in_one_message`, so a fix
  shows up as a test change.
* The money backstop treats a missing stored reading as `UNKNOWN` (single case and each mixed line): a hazard-class
  product without a reading is refused, never assumed clear. Reaching that needs a database write.
* Products that no category marks as hazard-class (for example candles, lawnmowers, treadmills) get rules 1 and 2 only,
  so a fault on them needs a word from the lists. Which products count as hazard-class is a product decision.
* An apparel return with burn words ("a burnt hole through the sleeve") goes to a person: rule 1 is product-independent
  on purpose. A known false positive.
* Keyword patterns are not understanding: paraphrases, other languages, slang, misspellings and deliberate obfuscation beyond
  zero-width / full-width / letter-spacing (leetspeak, homoglyphs from other scripts, images) can miss. A missed message
  falls back to the old behaviour (LLM + policy + human approval for money), it does not become auto-approved.
* The product class on `main` is derived from category + name keywords (plural-aware since the fix above). The seeded demo
  catalogue is footwear / apparel, so the class × fault rule is exercised by tests (kettle / lamp / gas stove / power bank
  fixtures and real Channel3 category paths), and, for Channel3 products, by live runs of the deployed app.
* Only the free-text customer message is scanned (not attachments, photos, order notes or webhooks).
* No in-app "release" to the refund flow for a reviewed false positive (by design: reviewing records a note only); no SLA / escalation / notification to a human; nothing is sent to the customer.

### Added with the AI layer
* It is a model: it can still miss (1 of 83 on our set) and it adds latency (one more LLM call on unflagged messages only, up to the timeout, when enabled) and token use on the live quota.
* If the LLM is down, the AI layer adds nothing and the gate is the keyword rules plus rule 3 failing closed. The intent reader falls back to the keyword reader, which reads most messages as `UNKNOWN`, so a hazard-class return is held for a person unless its patterns read it as a wrong size, a wrong item or a change of mind (40 of 48 harmless judgements held in the offline measurement above). A hazard-class return with no stored reading is treated as `UNKNOWN` by the money backstop and held too. Messages in uncovered languages about products that are not hazard-class follow the ordinary flow as before.
* An AI escalation is explained by a short model-written note in the audit chain; treat it as a hint for the reviewer, not as evidence.
