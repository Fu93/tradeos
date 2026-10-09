# Supplier routing eval — EXPERIMENT (MVP 1)

Rules `supplier-routing-rules/0.1.0 (MVP 1 experiment)` · dataset [routing-dataset.json](routing-dataset.json) (100 hand-labelled cases, 25 per type, 20 per language; labels written before the first run) · script `scripts/eval_routing.py`.
All order / inventory / logistics / supplier data is MOCK (`app/routing_data.py`). Thresholds are initial assumptions (auto ≥ 0.90, human-confirm 0.70–0.89).

* **keyword** run 2026-10-09T08:45:26+00:00 · extractor `keyword-fallback` · 429 retries 0 · LLM fallbacks 0 · delay 0 s
* **llm** run 2026-10-09T08:56:38+00:00 · extractor `llm:openai/gpt-oss-20b` · 429 retries 0 · LLM fallbacks 0 · delay 6.0 s

## Headline vs product acceptance targets (targets, not claims)

| Metric | Target | keyword | llm |
| --- | --- | --- | --- |
| Auto-trigger precision | ≥ 95% | n/a (0/0) | 100.0% (35/35) |
| Necessary-case recall (auto) | — | 0.0% (0/36) | 97.2% (35/36) |
| Necessary-case recall incl. human-confirm | — | 58.3% (21/36) | 97.2% (35/36) |
| Ambiguous false-trigger rate | < 2% | 0.0% (0/16) | 0.0% (0/16) |
| False trigger on all non-supplier cases | — | 0.0% (0/64) | 0.0% (0/64) |
| Duplicate rows that created a new task | 0 | 0.0% (0/8) | 0.0% (0/8) |
| Keys with >1 open task (DB) | 0 | 0 | 0 |
| Task completeness | 100% | n/a (0/0) | 100.0% (27/27) |
| Route accuracy strict / lenient | — | 40.0% (40/100) / 48.0% (48/100) | 97.0% (97/100) / 99.0% (99/100) |
| Latency p50 / p95 per case | — | 13.5 / 17.1 ms | 697.7 / 1227.2 ms |

## keyword: details

False triggers: none · missed necessary: E01, E02, E03, E04, E05, E06, E07, E08, E09, R01, R02, R03, R04, R05, R06, R07, R08, R09, D01, D02, D03, D04, D05, D06, D07, D08, D09, P01, P02, P03, P04, P05, P06, P07, P08, P09 · confidence bands: {'HUMAN_CONFIRM': 63, 'LOW': 37}

| Type | n | precision | recall | recall incl. confirm | ambiguous false-trigger | dup → new task | completeness | route strict | lenient |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EXCHANGE | 25 | n/a (0/0) | 0.0% (0/9) | 100.0% (9/9) | 0.0% (0/4) | 0.0% (0/2) | n/a (0/0) | 36.0% (9/25) | 44.0% (11/25) |
| RESHIP | 25 | n/a (0/0) | 0.0% (0/9) | 44.4% (4/9) | 0.0% (0/4) | 0.0% (0/2) | n/a (0/0) | 36.0% (9/25) | 48.0% (12/25) |
| DEFECT | 25 | n/a (0/0) | 0.0% (0/9) | 33.3% (3/9) | 0.0% (0/4) | 0.0% (0/2) | n/a (0/0) | 40.0% (10/25) | 48.0% (12/25) |
| PART_REPLACEMENT | 25 | n/a (0/0) | 0.0% (0/9) | 55.6% (5/9) | 0.0% (0/4) | 0.0% (0/2) | n/a (0/0) | 48.0% (12/25) | 52.0% (13/25) |

| Language | n | precision | recall | recall incl. confirm | false triggers | route strict | lenient | p50 ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| en | 20 | n/a (0/0) | 0.0% (0/8) | 50.0% (4/8) | 0 | 40.0% (8/20) | 40.0% (8/20) | 14.1 |
| zh-Hant | 20 | n/a (0/0) | 0.0% (0/6) | 83.3% (5/6) | 0 | 35.0% (7/20) | 45.0% (9/20) | 13.4 |
| es | 20 | n/a (0/0) | 0.0% (0/7) | 42.9% (3/7) | 0 | 45.0% (9/20) | 50.0% (10/20) | 13.5 |
| de | 20 | n/a (0/0) | 0.0% (0/8) | 50.0% (4/8) | 0 | 35.0% (7/20) | 50.0% (10/20) | 14.1 |
| ja | 20 | n/a (0/0) | 0.0% (0/7) | 71.4% (5/7) | 0 | 45.0% (9/20) | 55.0% (11/20) | 12.9 |

| Slice (tag) | n | route strict | lenient | auto triggers |
| --- | --- | --- | --- | --- |
| needed | 28 | 0.0% (0/28) | 3.6% (1/28) | 0 |
| duplicate | 8 | 0.0% (0/8) | 0.0% (0/8) | 0 |
| not_needed | 24 | 29.2% (7/24) | 29.2% (7/24) | 0 |
| missing | 16 | 100.0% (16/16) | 100.0% (16/16) | 0 |
| ambiguous | 16 | 56.2% (9/16) | 100.0% (16/16) | 0 |
| similar_order | 8 | 100.0% (8/8) | 100.0% (8/8) | 0 |

Confusion (label → final route):

* DIRECT_WORKFLOW -> NEEDS_CLARIFICATION: 1
* DIRECT_WORKFLOW -> NEEDS_HUMAN_REVIEW: 11
* NEEDS_CLARIFICATION -> NEEDS_CLARIFICATION: 27
* NEEDS_HUMAN_REVIEW -> NEEDS_CLARIFICATION: 12
* NEEDS_HUMAN_REVIEW -> NEEDS_HUMAN_REVIEW: 13
* SUPPLIER_REQUIRED -> NEEDS_CLARIFICATION: 14
* SUPPLIER_REQUIRED -> NEEDS_HUMAN_REVIEW: 22

Rows outside the acceptable routes (52):

| id | lang | label | final | conf | extracted | stopped at |
| --- | --- | --- | --- | --- | --- | --- |
| E01 | en | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.8 | EXCHANGE/ACTION_REQUEST | G4: Confidence 0.8 < auto threshold 0.9: a human confirms the supplier route. |
| E02 | zh-Hant | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.8 | EXCHANGE/ACTION_REQUEST | G4: Confidence 0.8 < auto threshold 0.9: a human confirms the supplier route. |
| E03 | es | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.8 | EXCHANGE/ACTION_REQUEST | G4: Confidence 0.8 < auto threshold 0.9: a human confirms the supplier route. |
| E04 | de | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.8 | EXCHANGE/ACTION_REQUEST | G4: Confidence 0.8 < auto threshold 0.9: a human confirms the supplier route. |
| E05 | ja | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.8 | EXCHANGE/ACTION_REQUEST | G4: Confidence 0.8 < auto threshold 0.9: a human confirms the supplier route. |
| E06 | en | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.8 | EXCHANGE/ACTION_REQUEST | G4: Confidence 0.8 < auto threshold 0.9: a human confirms the supplier route. |
| E07 | es | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.8 | EXCHANGE/ACTION_REQUEST | G4: Confidence 0.8 < auto threshold 0.9: a human confirms the supplier route. |
| E08 | zh-Hant | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.8 | EXCHANGE/ACTION_REQUEST | G4: Confidence 0.8 < auto threshold 0.9: a human confirms the supplier route. |
| E09 | de | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.8 | EXCHANGE/ACTION_REQUEST | G4: Confidence 0.8 < auto threshold 0.9: a human confirms the supplier route. |
| E10 | en | DIRECT_WORKFLOW | NEEDS_HUMAN_REVIEW | 0.8 | EXCHANGE/ACTION_REQUEST | G3: 3 × S in our warehouse: exchange from own stock. |
| E12 | de | DIRECT_WORKFLOW | NEEDS_HUMAN_REVIEW | 0.8 | EXCHANGE/ACTION_REQUEST | G3: Purchased 50 days ago, outside the 30-day window: the existing policy decides; supplier not needed. |
| E13 | zh-Hant | DIRECT_WORKFLOW | NEEDS_HUMAN_REVIEW | 0.8 | EXCHANGE/ACTION_REQUEST | G3: Final-sale item: the existing policy decides (no exchange); supplier not needed. |
| E14 | es | DIRECT_WORKFLOW | NEEDS_HUMAN_REVIEW | 0.8 | EXCHANGE/ACTION_REQUEST | G3: Purchased 40 days ago, outside the 30-day window: the existing policy decides; supplier not needed. |
| E15 | zh-Hant | DIRECT_WORKFLOW | NEEDS_HUMAN_REVIEW | 0.8 | EXCHANGE/ACTION_REQUEST | G3: 4 × black in our warehouse: exchange from own stock. |
| R01 | en | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.8 | RESHIP/ACTION_REQUEST | G4: Confidence 0.8 < auto threshold 0.9: a human confirms the supplier route. |
| R02 | zh-Hant | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.8 | RESHIP/ACTION_REQUEST | G4: Confidence 0.8 < auto threshold 0.9: a human confirms the supplier route. |
| R03 | es | SUPPLIER_REQUIRED | NEEDS_CLARIFICATION | 0.6 | UNKNOWN/OTHER | G1: Request type unclear: ask what they need. |
| R04 | de | SUPPLIER_REQUIRED | NEEDS_CLARIFICATION | 0.6 | UNKNOWN/OTHER | G1: Request type unclear: ask what they need. |
| R05 | ja | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.8 | RESHIP/ACTION_REQUEST | G4: Confidence 0.8 < auto threshold 0.9: a human confirms the supplier route. |
| R06 | en | SUPPLIER_REQUIRED | NEEDS_CLARIFICATION | 0.6 | UNKNOWN/OTHER | G1: Request type unclear: ask what they need. |
| R07 | es | SUPPLIER_REQUIRED | NEEDS_CLARIFICATION | 0.6 | UNKNOWN/OTHER | G1: Request type unclear: ask what they need. |
| R08 | ja | SUPPLIER_REQUIRED | NEEDS_CLARIFICATION | 0.6 | UNKNOWN/OTHER | G1: Request type unclear: ask what they need. |
| R09 | de | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.8 | RESHIP/ACTION_REQUEST | G4: Confidence 0.8 < auto threshold 0.9: a human confirms the supplier route. |
| R10 | en | DIRECT_WORKFLOW | NEEDS_HUMAN_REVIEW | 0.8 | RESHIP/ACTION_REQUEST | G3: LOST: we shipped it and have 6 in stock: reship from our warehouse. |
| R11 | zh-Hant | DIRECT_WORKFLOW | NEEDS_HUMAN_REVIEW | 0.8 | RESHIP/ACTION_REQUEST | G3: LOST: we shipped it and have 3 in stock: reship from our warehouse. |
| R12 | es | DIRECT_WORKFLOW | NEEDS_CLARIFICATION | 0.6 | UNKNOWN/OTHER | G1: Request type unclear: ask what they need. |
| R14 | ja | NEEDS_HUMAN_REVIEW | NEEDS_CLARIFICATION | 0.6 | UNKNOWN/OTHER | G1: Request type unclear: ask what they need. |
| D01 | en | SUPPLIER_REQUIRED | NEEDS_CLARIFICATION | 0.6 | UNKNOWN/OTHER | G1: Request type unclear: ask what they need. |
| D02 | zh-Hant | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.8 | DEFECT/ACTION_REQUEST | G4: Confidence 0.8 < auto threshold 0.9: a human confirms the supplier route. |
| D03 | es | SUPPLIER_REQUIRED | NEEDS_CLARIFICATION | 0.6 | UNKNOWN/OTHER | G1: Request type unclear: ask what they need. |
| D05 | ja | SUPPLIER_REQUIRED | NEEDS_CLARIFICATION | 0.6 | MULTIPLE/OTHER | G1: Several complaint types in one message: ask the customer to separate them. |
| D06 | en | SUPPLIER_REQUIRED | NEEDS_CLARIFICATION | 0.6 | UNKNOWN/OTHER | G1: Request type unclear: ask what they need. |
| D07 | de | SUPPLIER_REQUIRED | NEEDS_CLARIFICATION | 0.6 | UNKNOWN/OTHER | G1: Request type unclear: ask what they need. |
| D08 | es | SUPPLIER_REQUIRED | NEEDS_CLARIFICATION | 0.6 | UNKNOWN/OTHER | G1: Request type unclear: ask what they need. |
| D09 | ja | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.8 | DEFECT/ACTION_REQUEST | G4: Confidence 0.8 < auto threshold 0.9: a human confirms the supplier route. |
| D10 | en | DIRECT_WORKFLOW | NEEDS_HUMAN_REVIEW | 0.8 | DEFECT/ACTION_REQUEST | G3: Purchased 10 days ago: covered by the existing return/refund policy (30 days). Supplier not needed. |
| D11 | zh-Hant | DIRECT_WORKFLOW | NEEDS_HUMAN_REVIEW | 0.8 | DEFECT/ACTION_REQUEST | G3: Inside our own 365-day warranty: merchant process. |
| D12 | de | NEEDS_HUMAN_REVIEW | NEEDS_CLARIFICATION | 0.6 | UNKNOWN/OTHER | G1: Request type unclear: ask what they need. |
| D14 | ja | NEEDS_HUMAN_REVIEW | NEEDS_CLARIFICATION | 0.6 | UNKNOWN/OTHER | G1: Request type unclear: ask what they need. |
| D15 | en | NEEDS_HUMAN_REVIEW | NEEDS_CLARIFICATION | 0.6 | UNKNOWN/OTHER | G1: Request type unclear: ask what they need. |
| P01 | en | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.8 | PART_REPLACEMENT/ACTION_REQUEST | G4: Confidence 0.8 < auto threshold 0.9: a human confirms the supplier route. |
| P02 | zh-Hant | SUPPLIER_REQUIRED | NEEDS_CLARIFICATION | 0.6 | UNKNOWN/OTHER | G1: Request type unclear: ask what they need. |
| P03 | es | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.8 | PART_REPLACEMENT/ACTION_REQUEST | G4: Confidence 0.8 < auto threshold 0.9: a human confirms the supplier route. |
| P04 | de | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.8 | PART_REPLACEMENT/ACTION_REQUEST | G3: Possible safety issue (fire/smoke/shock/gas/injury): always a human first. |
| P05 | ja | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.6 | PART_REPLACEMENT/ACTION_REQUEST | G4: Confidence 0.6 < auto threshold 0.9: human review. |
| P06 | zh-Hant | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.8 | PART_REPLACEMENT/ACTION_REQUEST | G4: Confidence 0.8 < auto threshold 0.9: a human confirms the supplier route. |
| P07 | de | SUPPLIER_REQUIRED | NEEDS_CLARIFICATION | 0.6 | UNKNOWN/OTHER | G1: Request type unclear: ask what they need. |
| P08 | ja | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.6 | PART_REPLACEMENT/ACTION_REQUEST | G4: Confidence 0.6 < auto threshold 0.9: human review. |
| P09 | en | SUPPLIER_REQUIRED | NEEDS_CLARIFICATION | 0.6 | UNKNOWN/OTHER | G1: Request type unclear: ask what they need. |
| P10 | zh-Hant | DIRECT_WORKFLOW | NEEDS_HUMAN_REVIEW | 0.8 | PART_REPLACEMENT/ACTION_REQUEST | G3: BP-BUCKLE-25 (25 mm buckle) compatible and 30 in stock: ship it. |
| P11 | es | DIRECT_WORKFLOW | NEEDS_HUMAN_REVIEW | 0.8 | PART_REPLACEMENT/ACTION_REQUEST | G3: KL-170-FLT (Limescale filter) compatible and 12 in stock: ship it. |
| P12 | de | NEEDS_HUMAN_REVIEW | NEEDS_CLARIFICATION | 0.6 | UNKNOWN/OTHER | G1: Request type unclear: ask what they need. |

## llm: details

False triggers: none · missed necessary: P04 · confidence bands: {'AUTO': 99, 'HUMAN_CONFIRM': 1}

| Type | n | precision | recall | recall incl. confirm | ambiguous false-trigger | dup → new task | completeness | route strict | lenient |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EXCHANGE | 25 | 100.0% (9/9) | 100.0% (9/9) | 100.0% (9/9) | 0.0% (0/4) | 0.0% (0/2) | 100.0% (7/7) | 100.0% (25/25) | 100.0% (25/25) |
| RESHIP | 25 | 100.0% (9/9) | 100.0% (9/9) | 100.0% (9/9) | 0.0% (0/4) | 0.0% (0/2) | 100.0% (7/7) | 100.0% (25/25) | 100.0% (25/25) |
| DEFECT | 25 | 100.0% (9/9) | 100.0% (9/9) | 100.0% (9/9) | 0.0% (0/4) | 0.0% (0/2) | 100.0% (7/7) | 96.0% (24/25) | 100.0% (25/25) |
| PART_REPLACEMENT | 25 | 100.0% (8/8) | 88.9% (8/9) | 88.9% (8/9) | 0.0% (0/4) | 0.0% (0/2) | 100.0% (6/6) | 92.0% (23/25) | 96.0% (24/25) |

| Language | n | precision | recall | recall incl. confirm | false triggers | route strict | lenient | p50 ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| en | 20 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0 | 100.0% (20/20) | 100.0% (20/20) | 667.3 |
| zh-Hant | 20 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0 | 100.0% (20/20) | 100.0% (20/20) | 752.2 |
| es | 20 | 100.0% (7/7) | 100.0% (7/7) | 100.0% (7/7) | 0 | 95.0% (19/20) | 100.0% (20/20) | 681.3 |
| de | 20 | 100.0% (7/7) | 87.5% (7/8) | 87.5% (7/8) | 0 | 90.0% (18/20) | 95.0% (19/20) | 664.8 |
| ja | 20 | 100.0% (7/7) | 100.0% (7/7) | 100.0% (7/7) | 0 | 100.0% (20/20) | 100.0% (20/20) | 745.8 |

| Slice (tag) | n | route strict | lenient | auto triggers |
| --- | --- | --- | --- | --- |
| needed | 28 | 96.4% (27/28) | 96.4% (27/28) | 27 |
| duplicate | 8 | 100.0% (8/8) | 100.0% (8/8) | 8 |
| not_needed | 24 | 100.0% (24/24) | 100.0% (24/24) | 0 |
| missing | 16 | 93.8% (15/16) | 100.0% (16/16) | 0 |
| ambiguous | 16 | 93.8% (15/16) | 100.0% (16/16) | 0 |
| similar_order | 8 | 100.0% (8/8) | 100.0% (8/8) | 0 |

Confusion (label → final route):

* DIRECT_WORKFLOW -> DIRECT_WORKFLOW: 12
* NEEDS_CLARIFICATION -> NEEDS_CLARIFICATION: 25
* NEEDS_CLARIFICATION -> NEEDS_HUMAN_REVIEW: 2
* NEEDS_HUMAN_REVIEW -> NEEDS_HUMAN_REVIEW: 25
* SUPPLIER_REQUIRED -> NEEDS_HUMAN_REVIEW: 1
* SUPPLIER_REQUIRED -> SUPPLIER_REQUIRED: 35

Rows outside the acceptable routes (1):

| id | lang | label | final | conf | extracted | stopped at |
| --- | --- | --- | --- | --- | --- | --- |
| P04 | de | SUPPLIER_REQUIRED | NEEDS_HUMAN_REVIEW | 0.95 | PART_REPLACEMENT/ACTION_REQUEST | G3: Possible safety issue (fire/smoke/shock/gas/injury): always a human first. |

## Reading these numbers

* 100 cases is small: one case moves a per-type number by 4 points and a per-language number by 5.
* The dataset and the rules were written by the same person (the experiment author), so these are
  *consistency* numbers for this rule set on this MOCK data, not field accuracy. Real tickets will be messier.
* Precision/recall measure the full pipeline (LLM extraction + rules). The rules are deterministic, so most
  errors come from extraction (type / request kind / identifiers) or from the confidence band.
* The LLM confidence is a self-report. gpt-oss-20b returns 0.9–0.95 for almost everything, so the threshold
  bands do little on the LLM path; they matter mainly for the keyword fallback (capped at 0.85 => it can never
  auto-trigger) and when identifiers are discarded (−0.25 each). This is documented, not hidden.
* Keyword-fallback numbers are reported for completeness: the fallback is a degraded mode and by design never
  creates supplier tasks on its own (precision is therefore n/a and auto recall 0).
