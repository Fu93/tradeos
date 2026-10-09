# Held-out v2: generation and labelling protocol

**Status: LLM-generated, dual-LLM-labelled, author-adjudicated, pending human review.** MOCK data only.

## Generation (frozen in 49220cb before any v3 code existed)
- 300 messages: 216 design-grid cells (V001–V216) + 42 held-out minimal pairs (84 messages; 3 of 5 languages per
  pair type; the other 2 languages = 28 dev pairs used for tuning).
- Generators (non-gpt-oss, round-robin): `z-ai/glm-5.3`, `nvidia/nemotron-3-super-120b-a12b`, `meta/muse-glimmer-30b`,
  via NVIDIA. Fresh MOCK customers/orders (TO-80001…, `app/routing_data_v2.py`).
- Each cell has an **author-specified intended action** (`designed_action`), fixed in the design grid
  (`heldout-v2-design.json`, seed 20261009) before generation.

## Labelling: planned vs actual (deviation, disclosed)
Planned: two LLM judges from different families label all 300 with `labelling-guide-v3.md` (not the code), Cohen's
kappa per field, author adjudication of disagreements.

Actual, due to NVIDIA account throttling on 2026-10-09 (all calls logged):
- `z-ai/glm-5.3` (judge A) returned HTTP 429 on **every** call after 71 labels, including 20-token probes, for over an
  hour, so it became a supplementary judge on 71 items.
- Replacement second family `meta/muse-glimmer-30b` (judge C; schema not enforced server-side, so outputs are
  validated in code and retried) ran at about 1 label/min. It covers the items it finished before the freeze cutoff.
- `nvidia/nemotron-3-ultra-550b-a55b` (judge B) labelled **all 300**.
- Every item therefore has at least two independent labels: judge B plus the author-specified design action. Items
  covered by A and/or C have three or four.
- **Adjudication rule:** any item where the available labels (B, A, C, design) do not all agree is adjudicated by the
  author against the guide; the reason is recorded in `heldout-v2-adjudication.json`.
- Kappa is reported per field for B vs A and B vs C on their overlaps, and for the action for B vs design on all 300.
  Caveat: A and C cover the *first* cells in grid order, which skew towards simpler cell kinds.
- Known limitation: GLM, Nemotron and Meta models are also the generators. Every message has at least one judge from
  a different family than its generator; kappa is reported by generator family.
- Acceptable actions: intersection of the agreeing judges' `acceptable_actions` plus the required action.
  `CREATE_SUPPLIER_TASK` is never acceptable for a non-task label.

## Files
- `judge-heldout_v2-{A,B,C}.json`: raw judge outputs (with evidence quotes and reasoning).
- `heldout-v2-agreement.json`: kappas and coverage.
- `heldout-v2-disagreements.json`: everything that was adjudicated.
- `heldout-v2-adjudication.json`: the author's decision and reason per item.
- `heldout-v2-labels.json`: **frozen** final labels, composition and the status string.
- `heldout-v2-review.csv`: about 40 priority rows for human review (all adjudicated items + edge cases, every language).
