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

## False positives (accepted, and what happens to them)

* The gate **over-triggers on purpose**: a miss costs more than a read. Examples that route to a human although harmless:
  "great *fire* sale, wrong size", "burn rate", "it shocked me how cheap it was", "no smoke, no burning, just too small" (**negation is not
  used to suppress a hit**), "ampoule" (blister *or* bulb), "swollen" used about a price.
* A false positive is **never an automatic rejection**. It becomes `NEEDS_HUMAN_SAFETY_REVIEW`: a person reads the message and
  follows up outside this workflow. Nothing is refunded, nothing is declined, and the customer is not sent an automatic "no".
* The reverse is also true: nothing in this port lets a person approve a safety-flagged refund *inside* the app. A reviewer
  who decides the flag was a false alarm has no in-app "release" button (not built); they would re-create the case or handle
  it in PayPal. That is a known gap, listed under remaining risks.
* Normal returns without harm language still flow: "the sole came off / is damaged / cracked / detached", size and colour
  complaints, "the cut is too narrow", "hurts / too tight" (pain with no injury word) all reach `PENDING_APPROVAL` as before.
  (Table-tested in 6 languages.)

## Evidence tiers

| Tier | What it is | Status for the Safety Gate on `main` |
|---|---|---|
| **1. Unit / integration tests** (mock PayPal, mock LLM, offline) | `tests/test_safety_gate.py` (141 tests; whole suite 910 passed, 95% line coverage): multilingual harm table (EN / ZH-Hant / ZH-Hans / ES / DE / JA / FR), normal-message negatives, product-class × fault, every model reading of the burn message, injection + safety combo, keyword-fallback path, direct POST to approve / refund / decline / approve-twice, tampered-row backstop, mixed Case M, seeded generative property test (90 random messages × random model reading × random request path: never approvable, Refund API never called), mutation sanity (12 source mutants, all killed by `tests/mutation_sanity.py`; plus in-test mutants). | **Proven for these messages and these code paths.** |
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
* No in-app release path for a reviewed false positive; no SLA / escalation / notification to a human.
