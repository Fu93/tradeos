# Supplier routing — design and roadmap (EXPERIMENT)

Status: **experiment on branch `exp/supplier-routing-mvp1`**, based on `5d2a0e3` (the Phase A tree live on Render).
Not merged, not deployed. Adopt or delete after review. Phase A (policy → human approval → PayPal refund →
webhook) is unchanged; the experiment only adds files plus a few additive lines (see "Footprint").

## Goal

"Reliable triage only": for an incoming complaint, decide deterministically whether the supplier really has to be
involved — and if so, open exactly one internal task with a complete draft — without letting the AI decide,
without ever contacting a supplier, and without touching money.

## The four complaint types

| Type | Supplier is asked about | Typical case where the supplier is NOT needed |
| --- | --- | --- |
| `EXCHANGE` | spec / stock / feasibility of the requested variant | variant in our own stock; outside window or final sale (policy decides) |
| `RESHIP` | missing item, reship eligibility, ship time | parcel still in transit; we shipped it and have stock |
| `DEFECT` | product issue → repair or replacement under supplier warranty | inside our return window (existing refund policy covers it); our own warranty |
| `PART_REPLACEMENT` | part model, compatibility, availability | part known, compatible and in our stock |

A type label alone never triggers anything (e.g. a `DEFECT` that the existing refund policy covers needs no supplier).

## Three dimensions (round 2, rules 0.2.0)

| Dimension | Who | Values |
| --- | --- | --- |
| `issue_type` | AI extracts (validated, non-decisional) | SIZE_MISMATCH (size/colour/variant), DEFECT, MISSING_ITEM, PART_NEED, NO_ISSUE_INQUIRY, UNCLEAR |
| `customer_goal` (+ `mixed_goals`) | AI extracts | REFUND, EXCHANGE, RESHIP, REPAIR, BUY_PART, INFORMATION, UNCLEAR |
| `required_action` | **deterministic rules compute** | DIRECT_WORKFLOW, CREATE_SUPPLIER_TASK, CLARIFY_WITH_CUSTOMER, HUMAN_REVIEW |

A deterministic multilingual text scan runs on every message and cross-checks the AI. It can only make the outcome
more conservative. It looks for:

* explicit refund-only wording;
* question-form markers ("do you sell … separately", "just a question", 別売り, ¿venden…);
* explicitly negated problems ("not broken at all") and negated outcomes ("I don't want a replacement").

All three dimensions plus the deciding rule are shown in the dashboard panel and stored in the decision log.

## Four deterministic gates (`app/routing.py`)

1. **Intent rules** (first match wins):
   * R1: injection-like text → human.
   * R2: safety words or the AI safety flag → human.
   * R3: mixed or undecided goals, or several items → clarify.
   * R4: goal INFORMATION → human. It is a question, not a complaint, so no supplier task.
   * R5: goal REFUND → `DIRECT_WORKFLOW`. The existing refund policy flow owns it: policy checks, human approval, PayPal. **Never a supplier task.**
   * R6: the text says refund-only but the AI goal is an action → human.
   * R7: no outcome requested → clarify (or human if there is no problem either).
   * R8: question-form or negated-problem text with an AI action goal → human.
   * R9: issue × goal combination not actionable → clarify.
   * R10: otherwise, issue × goal maps to one internal family (EXCHANGE / RESHIP / DEFECT / PART_REPLACEMENT).

   A defect does not imply the supplier. A part mention does not imply a complaint.
2. **Case matches order / product?** Order number from the text (deterministic regex, NFKC-normalised) or the
   linked order; order must exist (no fuzzy matching) and belong to the case's customer; the product named in
   the text must be in that order; multi-item orders need the item; type-specific identifiers must be present:
   requested size/colour (EXCHANGE), fault description (DEFECT), part number (PART_REPLACEMENT).
   **AI identifiers are kept only if they literally appear in the customer's text** — the AI can never fill in a
   product, size or part model. Missing → `NEEDS_CLARIFICATION`; conflicting (other customer's / similar order
   number, product not in order, part of another product family) → `NEEDS_HUMAN_REVIEW`.
3. **Supplier actually necessary?** Existing TradeOS data is checked first: order date + policy (return window,
   final sale), MOCK inventory, MOCK logistics, MOCK parts table, and a MOCK **supplier responsibility table per
   SKU** (fulfilment, confirms stock, restocks, reships, warranty owner/days, supplies parts, answers
   compatibility). If existing data resolves the case → `DIRECT_WORKFLOW`. "No data found" (no inventory or
   logistics record, supplier has no responsibility) → `NEEDS_HUMAN_REVIEW`, never "ask the supplier".
   Safety words (fire, smoke, sparks, shock, gas, injury; 5 languages) or the AI's safety flag → human first.
   The supplier is chosen only when the responsibility table names it as the next actor / source of truth.
4. **Confidence + no duplicate.** Only after gates 1–3 pass: confidence may only demote (below 0.90 → a human confirms), then "no open task for
   `order | sku | type`". All met → `SUPPLIER_REQUIRED` and an internal task is created (`DRAFT_READY`).
   An open task already exists → the case is linked to it (no second task; also enforced by a partial UNIQUE
   index in SQLite and a lock).

## Confidence (honest description, rules 0.2.0: demote-only)

* `confidence` is an **extra, non-decisional** field in the LLM's strict JSON output. It is validated as a real number
  in [0, 1]; invalid or missing values are treated as 0.5. **It is uncalibrated.**
* Rule-based signals adjust it:
  - −0.25 per AI identifier not found in the text;
  - −0.10 if the deterministic keyword scan disagrees with the AI's issue, and another −0.10 if it disagrees with the goal;
  - capped at 0.50 for instruction-like text;
  - keyword fallback: fixed 0.80 / 0.60, **capped at 0.85**.
* **The primary control is the hard gates + routing rules + human fallback, not confidence.** Confidence is used in
  exactly one direction: an *automatic* action (`DIRECT_WORKFLOW` or `CREATE_SUPPLIER_TASK`) whose score is below
  `ROUTING_DEMOTE_BELOW` (default 0.90, an initial assumption) is demoted to `HUMAN_REVIEW`.
  - A demoted supplier proposal can be confirmed by a human (the button works only if gates 1–3 passed).
  - `CLARIFY_WITH_CUSTOMER` and `HUMAN_REVIEW` are never changed by confidence.
  - **Nothing is ever promoted.** A case that fails a hard gate or a routing rule stays where it is at any confidence. Confidence is only read after the gates and rules. The test `test_confidence_only_demotes_never_promotes` runs the same failing cases at 0.0 / 0.5 / 0.99 / 1.0.
* The keyword fallback is always below the floor, so it never performs an automatic action.
* Observed (round 2, both models): see the confidence analysis in [eval/routing-results.md](eval/routing-results.md). The self-report does not separate right from wrong actions: P(right > wrong) on held-out is 0.49 for 20b and 0.69 for 120b.
  - Self-reports sit at 0.90–0.99 for right and wrong answers alike.
  - P(conf right > conf wrong) is 0.61 (original) and 0.69 (held-out) on the raw self-report, and 0.73 / 0.75 on the combined score.
  - No threshold separates them: at 0.90 the raw self-report demotes 0 of 9 wrong held-out actions. At 0.99 it would demote 7/9 wrong, but also 20/51 right.
  - Calibration needs real labelled traffic (MVP 3). Until then confidence is a weak tie-breaker, not a control.

## Three separate state machines

| | States | Notes |
| --- | --- | --- |
| Routing case (main) | `CASE_RECEIVED → CLASSIFYING → DIRECT_WORKFLOW / NEEDS_CLARIFICATION / NEEDS_HUMAN_REVIEW / SUPPLIER_REQUIRED → SUPPLIER_TASK_OPEN` | `NEEDS_HUMAN_REVIEW → SUPPLIER_REQUIRED` only via human confirm with all hard gates passed |
| Supplier task | `NOT_REQUIRED → DRAFT_READY → AWAITING_RESPONSE → RESPONSE_RECEIVED → RESOLVED` (+ `NEEDS_HUMAN_REVIEW`) | MVP 1 can only reach `NOT_REQUIRED` / `DRAFT_READY` (code refuses others). `DRAFT_READY` is always shown as "NOT sent, supplier NOT contacted". |
| Refund (Phase A, unchanged) | `NEW → … → PENDING_APPROVAL → REFUND_COMPLETED / REJECTED / …` | Lives in `cases`. Routing never reads or writes the refund columns; the refund guard never reads routing tables. |

## Logging

Every routing case logs, in `routing_log`: each status transition with timestamp, the AI extraction (fields,
self-reported confidence, extractor), the gate list with pass/fail reasons, trigger reason, data used (each item
marked MOCK or not), rule version (`supplier-routing-rules/0.2.0`; round 2 also logs issue_type / customer_goal / required_action and the deciding rule), confidence signals, and task creation or
duplicate linking. Visible in the dashboard panel and at `/api/routing/{id}`.

## MVP plan

* **MVP 1 — reliable triage (this experiment).** Four types, four gates, thresholds, duplicate prevention,
  internal task + complete draft, MOCK data, dashboard panel, eval set. Nothing is sent.
* **MVP 2 — supervised supplier contact** (proposal). A human approves the draft, it is sent through one real
  channel (e.g. email), `AWAITING_RESPONSE` / `RESPONSE_RECEIVED` become reachable, replies are parsed by the AI
  (extract only) and matched to the task; SLA timers; real inventory/logistics/supplier data replace the MOCK
  tables.
* **MVP 3 — closed loop** (proposal). Supplier answer feeds the resolution suggestion (still human-approved;
  money still only via the Phase A guard), per-supplier capability data maintained, thresholds calibrated on real
  labelled traffic, monitoring of the metrics below.

## Metrics (product acceptance targets, not claims)

* Auto-trigger precision ≥ 95% (of the auto-created tasks, how many were needed).
* Ambiguous false-trigger rate < 2%.
* Necessary-case recall (auto, and incl. human-confirm).
* Duplicate task rate (target 0).
* Task completeness (draft contains every field its type needs; target 100%).
* Per type, per language, latency.

Current numbers: [docs/eval/routing-results.md](eval/routing-results.md).

## What this experiment implemented

| File | What |
| --- | --- |
| `app/routing.py` | gates, confidence, state machines, storage (own tables), service, draft builder |
| `app/routing_extract.py` | strict-schema LLM extraction (+ validated confidence), multilingual keyword fallback |
| `app/routing_data.py` | **MOCK** catalog, inventory, logistics, parts and supplier responsibility table |
| `app/routing_web.py`, `app/templates/routing_panel.html` | dashboard panel + 3 POST endpoints + JSON |
| `tests/test_routing.py` | gates, thresholds, duplicates, state machine, refund independence, Case A/B unchanged |
| `scripts/eval_routing.py`, `docs/eval/routing-*.{json,md}` | 100-case eval, LLM + keyword modes |

### Footprint in existing files (additive only)

* `app/main.py`: build the routing service on its own tables, register its routes, pass the panel's view model
  into the dashboard context, accept `?rcase=`, and also reset the routing tables on "Reset demo". No existing
  route or behaviour changed.
* `app/templates/dashboard.html`: one `{% include "routing_panel.html" %}` line.
* `app/static/style.css`: appended `.routing`/`.rt-*` classes.
* No change to `workflow.py`, `policy.py`, `intent.py`, `db.py`, `config.py`, presets or existing tests.

## Known limits

* All operational data is MOCK and tiny; the rules are only as good as the responsibility table.
* Identifier verification is literal: a customer who writes "the bigger one" gets a clarification, by design.
* Single-character colour aliases in CJK (e.g. 白, 黒) can match unrelated words.
* Gate 1 relies on the LLM's `customer_goal` / `mixed_goals`; borderline "is this a question or a request" and
  "repair or replace = one goal or two?" cases are the main source of route errors (see the round-2 eval).
* The dataset was written by the same author as the rules — numbers measure consistency, not field accuracy.

## Local sanity check (2026-10-09, real Groq `openai/gpt-oss-20b` + PayPal Sandbox, run locally, not deployed)

* Case A (sandbox order + capture) → `PENDING_APPROVAL`; "Triage selected case" → all 4 gates passed →
  `SUPPLIER_TASK_OPEN`, task `DRAFT_READY` (drop-shipped size 43). The case row and timeline were unchanged by the
  triage; Approve then refunded exactly once (sandbox refund `COMPLETED`, 1 refund call).
* Case B → `REJECTED`; triage → `DIRECT_WORKFLOW` ("45 days, outside window: existing policy decides");
  Approve / Refund still refused (HTTP 409, 0 refund calls).
* Free-text probes: zh defect in window → `DIRECT_WORKFLOW`; ja part KL-170-LID → task; similar order number
  (conf 0.99) → `NEEDS_HUMAN_REVIEW` at gate 2; injection → `NEEDS_HUMAN_REVIEW` (conf capped 0.5); two issues in one
  message → `NEEDS_CLARIFICATION`; German follow-up on TO-10421 → linked to the existing task (no duplicate).
* **Two out-of-dataset probes produced tasks a careful human might not have created:**
  "My kettle from TO-60202 broke again, honestly I just want my money back" → supplier warranty task (the customer's
  wish for a refund is not modelled), and "the lamp broke after 5 months, do you sell the LED module separately?" →
  read as DEFECT → supplier warranty task (arguably a part question without a part number → clarification).
  Both are inside the stated rules, but they show the 100/100 eval is optimistic.

Screenshots: [all gates passed](supplier-routing-panel.png) · [gate 2 failed at 0.99 confidence](supplier-routing-panel-gate-fail.png).

## Round 2 (rules 0.2.0): three dimensions, held-out set, demote-only confidence

**Eval models and providers.** Production extractor: `openai/gpt-oss-20b` on Groq.

* **20b via NVIDIA (production model):** both sets were run with `openai/gpt-oss-20b` served by NVIDIA (`integrate.api.nvidia.com`, an eval-only key, never used by the app or Render). This kept the Groq quota for the live app. Same model, **different provider** from production, so serving and decoding may differ slightly.
* **120b via Groq (comparison):** the earlier runs used `openai/gpt-oss-120b`, because the Groq 20b daily cap was used up. Kept for comparison only.
* **NVIDIA instability:** the first attempts of both 20b runs were aborted on a dropped connection (`RemoteProtocolError`; original at R14, held-out at H58). The script stops rather than score a keyword fallback as "llm". After adding a counted same-request network retry, both sets were re-run from scratch to completion (0 fallbacks).
* Side by side: [eval/routing-model-comparison.md](eval/routing-model-comparison.md).

**Held-out set.**

* 60 messages, generated blind by `qwen/qwen3.8-27b` (a different model family) from
  [a prompt with no rules](eval/heldout-generation-prompt.md).
* Labelled by the author per [the guide](eval/heldout-labelling-guide.md), frozen in d5752f0 **before** any run.
* Status: *blind-generated, author-labelled, pending human review*. Spot-check file:
  [eval/heldout-review.csv](eval/heldout-review.csv), with 30 rows marked `priority_review` (columns for both 20b and 120b).
* **Not used for tuning.** Rules 0.2.0 (a4ffee8) were committed before the first held-out run and have not changed since.
* Caveat: the author read the messages while labelling, before writing 0.2.0. The next round needs a fresh held-out set anyway.

Headline (full tables, per-case error lists with the deciding rule, and CIs: [eval/routing-results.md](eval/routing-results.md),
[eval/routing-model-comparison.md](eval/routing-model-comparison.md)):

| | Original 100 · **20b@NVIDIA** | Original 100 · 120b@Groq | Held-out 60 · **20b@NVIDIA** | Held-out 60 · 120b@Groq |
| --- | --- | --- | --- | --- |
| issue_type | 88/100 (CI 80–93%) | 96/100 (CI 90–98%) | 48/60 (CI 68–88%) | 48/60 (CI 68–88%) |
| customer_goal | 90/100 (CI 83–95%) | 93/100 (CI 86–97%) | 45/60 (CI 63–84%) | 49/60 (CI 70–89%) |
| required_action (lenient) | 91/100 (CI 84–95%) | 92/100 (CI 85–96%) | **48/60 (80.0%, CI 68–88%)** | 51/60 (85.0%, CI 74–92%) |
| supplier-task precision | 29/29 (CI 88–100%) | 30/30 (CI 89–100%) | 3/4 (CI 30–95%) | 3/4 |
| supplier-task recall (automatic) | 29/36 (CI 65–90%) | 30/36 (CI 68–92%) | 3/3 (CI 44–100%) | 3/3 |
| false trigger on non-task cases | 0/64 (CI 0–6%) | 0/64 | **1/57 (H13)** (CI 0.3–9%) | 1/57 (H13) |
| should be human/clarify but automated | 0/52 (CI 0–7%) | 0/52 | **1/44 (H13)** (CI 0.4–12%) | 2/44 (H13, H32) |
| keyword fallback: tasks / automatic actions | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |

**Do the conclusions change with the production model? Not qualitatively.**

* The 20b is somewhat weaker on dimensions: customer_goal 45/60 vs 49/60, and action 48/60 vs 51/60. The CIs overlap heavily, so this is not a demonstrated difference.
* Its errors fail more toward people: 4 automatic routes were demoted by confidence vs 1. That includes H32, which 120b sent to the refund flow.
* The safety-relevant picture is the same:
  - the same single false supplier task (H13);
  - no automated-but-should-be-manual case other than H13;
  - task precision 29/29 on the original set;
  - zero automatic actions from the keyword fallback.
* The same weaknesses appear: "repair or replace" read as mixed (D04, D05, H48), inconsistent mixed detection, and INFORMATION chosen where the label is UNCLEAR (H27, H28, H30).
* The new 20b-only failure modes:
  - R7 "no requested outcome" (D03, D10);
  - P09, gate 3, carrier-delivered conflict after the AI read MISSING_ITEM;
  - H53, gate 2, no order.
  All of them route to a human or to clarification.

Even a perfect 60/60 would only be preliminary evidence: its lower 95% bound is about 94%, and the held-out set has only 3
supplier-task cases. These numbers are not proof of 95% production accuracy.

**Regression messages** (permanent tests; real LLM, local, 2026-10-09). With **20b via NVIDIA** through the full pipeline: "I just want my money back" → NO_ISSUE_INQUIRY/REFUND → `DIRECT_WORKFLOW` (R5), no task; "Do you sell the LED module separately?" → NO_ISSUE_INQUIRY/INFORMATION → `HUMAN_REVIEW` (R4), no task. With 120b via Groq:

* "I just want my money back" → REFUND → `DIRECT_WORKFLOW` (R5), no task. Same with a linked order inside the supplier warranty.
* "Do you sell the LED module separately?" → the LLM said PART_NEED/**BUY_PART**. Rule R8 (question-form text) stopped it → `HUMAN_REVIEW`, no task. The tests also cover an adversarial DEFECT extraction, which the text check overrides.
* The longer round-1 probes now give: "…broke again, I just want my money back" → `DIRECT_WORKFLOW`; "…lamp broke after 5 months, do you sell the LED module separately?" → INFORMATION → `HUMAN_REVIEW`.

Screenshots: [regression: LED question](supplier-routing-panel-r2-led-question.png),
[regression: money back](supplier-routing-panel-r2-money-back.png).

**Remaining weaknesses (not fixed. Fixing them would make the held-out set "used for tuning".)**

1. **H13, the false trigger (both 20b and 120b).** German question form "Hättet ihr noch Ersatzfilter oder den Deckel KL-170-LID?" The AI read BUY_PART, and the question markers don't cover "Hättet ihr / habt ihr …?". A supplier task was created for what the label calls a question.
   Possible fix: never auto-create a part task from a "?"-terminated sentence without an explicit order verb.
2. **H32 (120b; 20b got it demoted to a human).** Two items (kettle + socks) with "can I return both?". The AI did not flag mixed, so it went to the refund flow (`DIRECT_WORKFLOW`) instead of clarification. Phase A's human approval still guards the money.
3. **"Repair or replace" flagged as mixed.** This caused 4 of the 6 missed tasks on the original set and H48. It fails safe (clarification).
4. **Mixed / two-item detection is inconsistent** in both directions: H08, H12 and H14 were over-flagged; H28 and H30 were missed.
5. **Confidence does not separate right from wrong** (above). On held-out 20b, P(self-report of right > wrong) = 0.49, which is no separation; the combined score gives 0.63. It stays a demote-only signal.
6. **Small samples.** The keyword fallback only routes to people. The labels are pending human review (1 erratum: H60). Everything is MOCK data.

## Round 3 (rules 3.0.0, taxonomy v3) — EXPERIMENT

Additive and separate from 0.2.0: `app/routing_v3.py` (extraction schema, code checks, rules), `app/routing_v3_service.py`
(own `routing_v3_*` tables), `app/routing_v3_web.py` + `routing_v3_panel.html` (panel labelled EXPERIMENTAL). The 0.2.0
pipeline, refund path and the 152 Phase A tests are untouched.

- **Extraction (LLM, strict json_schema, gpt-oss-20b):** speech act, items[] (issue_type per item, goals[] + goal_relation),
  negated goals, order-ref / hedge / part / variant quotes, safety level + quote. No action, no `mixed`, no identifiers
  from the model: every decision-relevant field carries a verbatim quote verified by code (NFKC/case/whitespace).
- **Code-derived facts:** order status (CONFIRMED / OTHER_CUSTOMER / NOT_FOUND / MALFORMED / HEDGED), part numbers,
  variants, safety S1 (multilingual hazard words, narrow negation guard), S3 gas appliances, S4 mains-electric (burn words or
  power parts), catalogue/inventory/logistics/responsibility tables.
- **Rules V0–V12 (first match, safety first):** injection → safety → evidence invalid → data conflict → uncertain order ref
  (clarify) → availability-question cross-check → information question → mixed (computed) → refund (existing flow) →
  no goal → non-actionable combos → slots → responsibility table. Demote-only checks; the refund-handoff confidence demotion
  is kept (D10); no confidence demotion of supplier tasks.
- **V13 agreement gate (optional):** k−1 extra samples only for suggested tasks; all must agree on action + family.
  Pre-registered primary k=1; k=3/5 reported as a trade-off.
- **Clarify engine:** rule-chosen templates (ASK_ORDER_REF, ASK_WHICH_ITEM(_FIRST), ASK_GOAL(_CHOICE), ASK_VARIANT, ASK_PART,
  ASK_FAULT), LLM translation with code checks (placeholders verbatim, no new identifiers/numbers, length) and a cache;
  max 2 rounds, a slot is never asked twice, ≤2 slots per question; the reply is re-gated with the original message; reply
  with injection / request for a person → human. In the panel the customer reply is **simulated**; nothing is sent.
- **Supplier task = suggestion:** status SUGGESTED_TASK; a human confirms → internal draft (NOT sent) or dismisses.

Results: `docs/eval/v3/heldout-v2-results.md` (single final run on held-out v2 vs rules 0.2.0 on the same set);
dev tuning: `docs/eval/v3/dev-tuning-log.md`; labelling: `docs/eval/v3/heldout-v2-labelling-protocol.md`.

Next (not done): human review of `heldout-v2-review.csv`; a fresh human-written test set; Groq production k-sample cost
(Groq requires n=1 → k requests); translation cache review workflow; real supplier channel stays out of scope.
