# Held-out v3 results (v3.1 round, single final run)

**Labels:** `heldout-v3-labels.json`. Status: **LLM-generated, dual-LLM-labelled, adjudicated, pending human review**. MOCK data only.
- 327 messages, all 5 languages (en 67 · zh-Hant 66 · es 66 · ja 66 · de 62). 83 need a supplier task, 244 are non-supplier, 40 are safety cases.
- Generators (all non-gpt-oss, via NVIDIA): nemotron-3-super 157 · muse-glimmer-30b 113 · deepseek-v4.1-flash 55 · gemma-4-31b 2. Reassignments are recorded in `heldout-v3-raw.json`.
- Judges, guide v3.1: `nvidia/nemotron-3-super-120b-a12b` (N) and `meta/muse-glimmer-30b` (M), all 327 each. Cohen's kappa N vs M: required_action 0.816 · speech_act 0.918 · safety 0.971 · issue_type 0.958 · first goal 0.960 · order-ref hedged 0.932 · deciding rule 0.801. Against the design action: N 0.805, M 0.917.
- Label sources: 276 where both judges and the design agree · 35 decided 2 of 3 (design plus one judge) · 9 author-adjudicated (`heldout-v3-author-adjudication.json`; 7 of the 9 are hyphen-variant ids that the judges' record lookup did not normalise) · 7 where both judges agree and override the design.
- Freeze order: design and MOCK orders `be57838` → messages `15130a7` → labels `4d4acad` → build `ba8e60e` → single runs.

**Builds:** v3.1 = `supplier-routing-rules/3.1.0`, prompt v3-extract-1, gpt-oss-20b via NVIDIA, k=5 samples in one run (k1 primary, k3 and k5 secondary). Baselines: the v3 frozen build `04b65fc` (only the held-out v3 MOCK orders were added) and rules 0.2.0. Each was run once on the same set.

## Results
| run | correct (lenient) / n [Wilson 95%] | strict | tasks TP/pred (prec) | recall TP/true | false triggers / non-supplier | safety → human | tasks on no-request | bar |
|---|---|---|---|---|---|---|---|---|
| v3.1 k1 (primary) | 291/327 [85.1–91.9] | 290/327 | 72/81 (0.889) | 72/83 (0.867) | 9/244 ['W019', 'W044', 'W107', 'W105', 'W156', 'W153', 'W183', 'W181', 'W231'] | 35/40 | 0/16 | not met |
| v3.1 k3 | 287/327 [83.8–90.9] | 286/327 | 65/71 (0.915) | 65/83 (0.783) | 6/244 ['W019', 'W107', 'W156', 'W153', 'W183', 'W181'] | 35/40 | 0/16 | not met |
| v3.1 k5 | 280/327 [81.4–89.0] | 279/327 | 57/62 (0.919) | 57/83 (0.687) | 5/244 ['W019', 'W107', 'W156', 'W153', 'W181'] | 36/40 | 0/16 | not met |
| v3 frozen 04b65fc (k1) | 257/327 [73.8–82.7] | 256/327 | 75/105 (0.714) | 75/83 (0.904) | 30/244 ['W019', 'W097', 'W098', 'W096', 'W106', 'W105', 'W107', 'W104', 'W100', 'W108', 'W113', 'W112', 'W109', 'W115', 'W117', 'W114', 'W116', 'W121', 'W111', 'W118', 'W119', 'W152', 'W155', 'W153', 'W156', 'W160', 'W162', 'W181', 'W183', 'W231'] | 31/40 | 0/16 | not met |
| rules 0.2.0 | 186/327 [51.5–62.1] | 184/327 | 36/79 (0.456) | 36/83 (0.434) | 43/244 ['W086', 'W094', 'W093', 'W095', 'W087', 'W085', 'W099', 'W090', 'W100', 'W088', 'W092', 'W102', 'W091', 'W106', 'W109', 'W096', 'W097', 'W098', 'W113', 'W103', 'W108', 'W112', 'W119', 'W111', 'W116', 'W115', 'W105', 'W110', 'W120', 'W117', 'W118', 'W121', 'W107', 'W154', 'W156', 'W155', 'W157', 'W153', 'W163', 'W181', 'W174', 'W173', 'W231'] | 23/40 | 0/16 | not met |

"Correct" means the predicted action is in the label's acceptable set; "strict" means it equals the required action. Safety → human = safety-case messages routed to HUMAN_REVIEW. "Tasks on no-request" = suggested tasks created on complaint-only / no-explicit-request messages.

### Per slice (correct/n)
| slice | v3.1 k1 (primary) | v3.1 k3 | v3.1 k5 | v3 frozen 04b65fc (k1) | rules 0.2.0 |
|---|---|---|---|---|---|
| buyer_vs_seller | 28/36 | 27/36 | 25/36 | 28/36 | 1/36 |
| order_conflict | 30/32 | 31/32 | 31/32 | 7/32 | 8/32 |
| multi_item | 8/8 | 8/8 | 8/8 | 7/8 | 8/8 |
| safety | 35/40 | 35/40 | 36/40 | 31/40 | 23/40 |
| intent_revision | 13/16 | 13/16 | 13/16 | 13/16 | 12/16 |
| complaint_only | 14/16 | 14/16 | 14/16 | 15/16 | 16/16 |
| normalisation | 14/16 | 15/16 | 15/16 | 6/16 | 3/16 |
| normal_task | 61/67 | 56/67 | 50/67 | 64/67 | 37/67 |
| other | 88/96 | 88/96 | 88/96 | 86/96 | 78/96 |


## Breakthrough bar: NOT met
The bar requires at least 36 suggested tasks with 0 errors, 0 false triggers on at least 183 non-supplier messages, and 0 safety cases automated.
- k1: 72 correct out of 81 suggested, **9 false triggers** out of 244, **5 safety cases automated** (W149 refund flow; W153, W156, W181 and W183 suggested tasks).
- k3: 6 false triggers, 5 safety cases automated. k5: 5 false triggers, 4 safety cases automated.

## Error analysis (k1). Documented, NOT fixed (fixing would be tuning on held-out v3)
- **Safety lexicon gaps (5, unsafe):**
  - W149 (DE): "riecht beim Kochen nach verbranntem Plastik". Words sit between *riecht* and *nach*, and S1 `verbrannt` has an exact boundary, so `verbranntem` does not match. The case went to the refund flow.
  - W153 (zh): "底座接觸鬆動經常斷電". 斷電 is not in the base-fault list.
  - W156 (JA): "電気ポットの台が壊れて…電源入らなく". 台 is not covered, and ポット is not a kettle alias.
  - W181 (zh) "底座進水" and W183 (DE) "Wasser … in den Fuß": water-in-base patterns require the words to be adjacent, and the German "Fuß" is missing.
  - The model also reported safety NONE on all five. Next: broaden the lexicon by meaning, plus a mains-product + base/power-fault rule. This must be validated on fresh data.
- **Order conflict missed (2, false triggers):** W105 has a typo ("whte"), so the claimed variant was not canonicalised. In W107 the model extracted no current variant. In both, the fallback scan accepted the claim. Next: if the claimed or received variant cannot be canonicalised, go to a human.
- **Other false triggers:** W019 (the customer asks how to proceed, not explicitly for a remedy; adjudicated CLARIFY), W044 (judges said human for a dripping kettle; arguable label), W231 (process question "wie ich … einsenden kann", label V6 HUMAN).
- **Buyer error read as a conflict (W096, W098; safe direction):** "I meant black" was read as a claimed order variant.
- **Seller error demoted (W009, W017, W018, W024; safe direction):** the old v3 V3 "variant you have differs from the order" check fires before C1 when the model labels the issue SIZE_MISMATCH/DEFECT.
- **Recall cost of the V12b explicit-request gate:** 2 cases (W007, W022).
- **Rest (safe direction):** clarify/human on undecided, no-order and malformed-reference cases (V6/V11/V2).

## Latency and cost
- v3.1: median 36.1 s/message, p90 125.5 s on the shared NVIDIA endpoint, which was heavily loaded. 408 calls, 507k prompt + 773k completion tokens, 18 counted retries, wall time 1474 s at 14 workers.
- At Groq list price for gpt-oss-20b ($0.075 / $0.30 per 1M tokens), that is about $0.27 for 327 messages including the k=5 samples, ≈ $0.0008 per message.
- v3 04b65fc: median 31.6 s, $0.15. Rules 0.2.0: median 12.3 s.

## Full error list (v3.1 k1)
### Errors, v3.1 k1 (primary)

| id | lang | kind | predicted | label (acceptable) | rule | reason |
|---|---|---|---|---|---|---|
| W007 | de | exch_shoe_size | CLARIFY_WITH_CUSTOMER | CREATE_SUPPLIER_TASK (CREATE_SUPPLIER_TASK) | V12b | Would be a supplier task, but the text contains no explicit remedy request: ask what the customer would like. |
| W006 | es | exch_shoe_size | CLARIFY_WITH_CUSTOMER | CREATE_SUPPLIER_TASK (CREATE_SUPPLIER_TASK) | V7 | 2 items need separate handling (D13): ask which first. |
| W009 | en | seller_wrong_size | HUMAN_REVIEW | CREATE_SUPPLIER_TASK (CREATE_SUPPLIER_TASK) | V3 | Customer says they have 40, the order shows 41. |
| W018 | ja | seller_wrong_size | HUMAN_REVIEW | CREATE_SUPPLIER_TASK (CREATE_SUPPLIER_TASK) | V3 | Customer says they have 43, the order shows 42. |
| W017 | de | seller_wrong_size | HUMAN_REVIEW | CREATE_SUPPLIER_TASK (CREATE_SUPPLIER_TASK) | V3 | Customer says they have 45, the order shows 43. |
| W024 | ja | seller_wrong_colour_lamp | HUMAN_REVIEW | CREATE_SUPPLIER_TASK (CREATE_SUPPLIER_TASK) | V3 | Wrong-item claim that cannot be checked against the order record (received/ordered variant not stated): a human verifies. |
| W022 | es | seller_wrong_colour_lamp | CLARIFY_WITH_CUSTOMER | CREATE_SUPPLIER_TASK (CREATE_SUPPLIER_TASK) | V12b | Would be a supplier task, but the text contains no explicit remedy request: ask what the customer would like. |
| W019 | ja | seller_wrong_colour_lamp | CREATE_SUPPLIER_TASK | CLARIFY_WITH_CUSTOMER (CLARIFY_WITH_CUSTOMER/HUMAN_REVIEW) | V12 | Drop-shipped by Lumina Lighting (MOCK supplier): the supplier confirms stock of black and what was shipped (C1). |
| W040 | ja | reship_shoe | HUMAN_REVIEW | CREATE_SUPPLIER_TASK (CREATE_SUPPLIER_TASK) | V9 | No problem and no requested outcome: standard support reads it. |
| W047 | de | kettle_warranty | HUMAN_REVIEW | CREATE_SUPPLIER_TASK (CREATE_SUPPLIER_TASK) | V1 | Possible safety issue (S1 hazard words Rauch): always a human first. |
| W044 | en | kettle_warranty | CREATE_SUPPLIER_TASK | HUMAN_REVIEW (HUMAN_REVIEW) | V12 | Outside our 30-day window, inside the 365-day supplier warranty: Kettleworks Ltd. (MOCK supplier) decides. |
| W076 | es | part_lamp | HUMAN_REVIEW | CREATE_SUPPLIER_TASK (CREATE_SUPPLIER_TASK) | V9 | No problem and no requested outcome: standard support reads it. |
| W096 | ja | buyer_wrong_colour | HUMAN_REVIEW | DIRECT_WORKFLOW (DIRECT_WORKFLOW) | V3 | Customer says they ordered black, but order TO-90096 shows white: claim conflicts with the order record; a human verifies. |
| W098 | zh-Hant | buyer_wrong_colour | HUMAN_REVIEW | DIRECT_WORKFLOW (DIRECT_WORKFLOW) | V3 | Customer says they ordered black, but order TO-90098 shows white: claim conflicts with the order record; a human verifies. |
| W107 | es | conflict_lamp_colour | CREATE_SUPPLIER_TASK | HUMAN_REVIEW (HUMAN_REVIEW) | V12 | Drop-shipped by Lumina Lighting (MOCK supplier): the supplier confirms stock of white and what was shipped (C1). |
| W105 | en | conflict_lamp_colour | CREATE_SUPPLIER_TASK | HUMAN_REVIEW (HUMAN_REVIEW) | V12 | Drop-shipped by Lumina Lighting (MOCK supplier): the supplier confirms stock of white and what was shipped (C1). |
| W149 | de | safety_burnt_plastic | DIRECT_WORKFLOW | HUMAN_REVIEW (HUMAN_REVIEW) | V8 | Refund wish: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. |
| W156 | ja | safety_power_base | CREATE_SUPPLIER_TASK | HUMAN_REVIEW (HUMAN_REVIEW) | V12 | Outside our 30-day window, inside the 365-day supplier warranty: Kettleworks Ltd. (MOCK supplier) decides. |
| W153 | zh-Hant | safety_power_base | CREATE_SUPPLIER_TASK | HUMAN_REVIEW (HUMAN_REVIEW) | V12 | Outside our 30-day window, inside the 365-day supplier warranty: Kettleworks Ltd. (MOCK supplier) decides. |
| W183 | de | safety_water_base | CREATE_SUPPLIER_TASK | HUMAN_REVIEW (HUMAN_REVIEW) | V12 | Outside our 30-day window, inside the 730-day supplier warranty: Lumina Lighting (MOCK supplier) decides. |
| W195 | de | revision_ambiguous | HUMAN_REVIEW | CLARIFY_WITH_CUSTOMER (CLARIFY_WITH_CUSTOMER) | V2 | Evidence quote not found in the message (item1.goal REFUND): a human reads it. |
| W187 | ja | revision_to_refund | CLARIFY_WITH_CUSTOMER | DIRECT_WORKFLOW (DIRECT_WORKFLOW) | V7 | 2 items need separate handling (D13): ask which first. |
| W201 | de | complaint_only | HUMAN_REVIEW | CLARIFY_WITH_CUSTOMER (CLARIFY_WITH_CUSTOMER) | V9 | No problem and no requested outcome: standard support reads it. |
| W181 | zh-Hant | safety_water_base | CREATE_SUPPLIER_TASK | HUMAN_REVIEW (HUMAN_REVIEW) | V12 | Outside our 30-day window, inside the 730-day supplier warranty: Lumina Lighting (MOCK supplier) decides. |
| W207 | ja | complaint_only | HUMAN_REVIEW | CLARIFY_WITH_CUSTOMER (CLARIFY_WITH_CUSTOMER) | V3 | Several products described and “Trail Runner” cannot be matched to order TO-90207: resolve the data conflict before any multi-item handling. |
| W223 | ja | norm_valid_refund | DIRECT_WORKFLOW | CLARIFY_WITH_CUSTOMER (CLARIFY_WITH_CUSTOMER/HUMAN_REVIEW) | V8 | Refund wish: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. |
| W231 | de | norm_valid_task | CREATE_SUPPLIER_TASK | HUMAN_REVIEW (HUMAN_REVIEW) | V12 | Outside our 30-day window, inside the 730-day supplier warranty: Lumina Lighting (MOCK supplier) decides. |
| W271 | en | no_order_ref | CLARIFY_WITH_CUSTOMER | HUMAN_REVIEW (HUMAN_REVIEW) | V11 | No order number in the message and no linked order: ask for it. |
| W269 | de | no_order_ref | CLARIFY_WITH_CUSTOMER | HUMAN_REVIEW (HUMAN_REVIEW) | V11 | No order number in the message and no linked order: ask for it. |
| W274 | de | undecided | HUMAN_REVIEW | CLARIFY_WITH_CUSTOMER (CLARIFY_WITH_CUSTOMER) | V6 | Information question: support answers it. No supplier task. |
| W275 | ja | undecided | HUMAN_REVIEW | CLARIFY_WITH_CUSTOMER (CLARIFY_WITH_CUSTOMER) | V1 | Possible safety issue (S4 mains-electric hazard): always a human first. |
| W272 | zh-Hant | undecided | HUMAN_REVIEW | CLARIFY_WITH_CUSTOMER (CLARIFY_WITH_CUSTOMER) | V6 | Information question: support answers it. No supplier task. |
| W276 | en | undecided | HUMAN_REVIEW | CLARIFY_WITH_CUSTOMER (CLARIFY_WITH_CUSTOMER) | V6 | Information question: support answers it. No supplier task. |
| W265 | de | malformed_ref | HUMAN_REVIEW | CLARIFY_WITH_CUSTOMER (CLARIFY_WITH_CUSTOMER) | V2 | Evidence quote not found in the message (item1.goal REPAIR): a human reads it. |
| W186 | de | revision_to_refund | CLARIFY_WITH_CUSTOMER | DIRECT_WORKFLOW (DIRECT_WORKFLOW) | V4b | The customer revises their request towards a refund, but the extracted intent disagrees: ask which outcome they want. |
| W314 | en | backpack_warranty | DIRECT_WORKFLOW | HUMAN_REVIEW (HUMAN_REVIEW) | V12 | Inside our own 365-day warranty: merchant process. |

