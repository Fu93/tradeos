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

## Four deterministic gates (`app/routing.py`)

1. **Intent clear?** A real request about the customer's order of one of the four types — not a policy question,
   an order lookup, venting, several issues at once, or instruction-like text.
   Fail → `NEEDS_CLARIFICATION` (venting, unclear, several types) or `NEEDS_HUMAN_REVIEW` (policy question,
   lookup, not one of the four types, injection-like text).
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
4. **Confidence + no duplicate.** Only after gates 1–3 pass: confidence band, then "no open task for
   `order | sku | type`". All met → `SUPPLIER_REQUIRED` and an internal task is created (`DRAFT_READY`).
   An open task already exists → the case is linked to it (no second task; also enforced by a partial UNIQUE
   index in SQLite and a lock).

## Confidence (honest description)

* `confidence` is an **extra, non-decisional** field in the LLM's strict JSON output, validated as a real number
  in [0, 1] (invalid/missing → treated as 0.5).
* Rule-based signals adjust it: −0.25 per AI identifier not found in the text; −0.10 if the deterministic
  multilingual keyword scan points to a different type; capped at 0.50 for instruction-like text; the keyword
  fallback (no LLM) uses a fixed rule score (0.80 / 0.60) **capped at 0.85, so it can never auto-route**.
* Bands (configurable, `ROUTING_AUTO_THRESHOLD`, `ROUTING_CONFIRM_THRESHOLD`; **initial assumptions, not
  calibrated**): ≥ 0.90 automatic route; 0.70–0.89 a human confirms the proposed route (a button that works only if
  gates 1–3 passed); < 0.70 human review. Gate failures stay what they are at any confidence: **even 0.99 cannot
  bypass a hard gate**, because confidence is only looked at after gates 1–3.
* Observed: gpt-oss-20b self-reports 0.95–0.99 for almost everything, so on the LLM path the bands rarely bite;
  the real safety comes from gates 1–3. Calibration needs real, labelled traffic (MVP 3).

## Three separate state machines

| | States | Notes |
| --- | --- | --- |
| Routing case (main) | `CASE_RECEIVED → CLASSIFYING → DIRECT_WORKFLOW / NEEDS_CLARIFICATION / NEEDS_HUMAN_REVIEW / SUPPLIER_REQUIRED → SUPPLIER_TASK_OPEN` | `NEEDS_HUMAN_REVIEW → SUPPLIER_REQUIRED` only via human confirm with all hard gates passed |
| Supplier task | `NOT_REQUIRED → DRAFT_READY → AWAITING_RESPONSE → RESPONSE_RECEIVED → RESOLVED` (+ `NEEDS_HUMAN_REVIEW`) | MVP 1 can only reach `NOT_REQUIRED` / `DRAFT_READY` (code refuses others). `DRAFT_READY` is always shown as "NOT sent, supplier NOT contacted". |
| Refund (Phase A, unchanged) | `NEW → … → PENDING_APPROVAL → REFUND_COMPLETED / REJECTED / …` | Lives in `cases`. Routing never reads or writes the refund columns; the refund guard never reads routing tables. |

## Logging

Every routing case logs, in `routing_log`: each status transition with timestamp, the AI extraction (fields,
self-reported confidence, extractor), the gate list with pass/fail reasons, trigger reason, data used (each item
marked MOCK or not), rule version (`supplier-routing-rules/0.1.1`), confidence signals, and task creation or
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
* Gate 1 relies on the LLM's `request_kind`; borderline "is this a question or a request" cases are the main
  source of route errors (see the eval).
* The dataset was written by the same author as the rules — numbers measure consistency, not field accuracy.
