# Supplier routing eval — round 2 (rules `supplier-routing-rules/0.2.0 (MVP 1 experiment, round 2)`)

Two sets, reported **separately** (never pooled). Every rate is `correct/n (%)`; key rates carry a Wilson 95% confidence interval. Extractor model: `openai/gpt-oss-120b` (Groq). All operational data is MOCK.
Round-1 history: [routing-results-round1-rules011.md](routing-results-round1-rules011.md), [routing-results-run1.md](routing-results-run1.md).

## Original 100 — regression set of known scenarios (author-written)

* **keyword** run 2026-10-09T09:25:52+00:00 UTC · extractor `keyword-fallback` · 429 retries 0 · LLM fallbacks 0 · keys with >1 open task 0

| Metric | keyword |
| --- | --- |
| issue_type accuracy (after text checks) | 73/100 (73.0%) [95% CI 63.6–80.7%] |
| issue_type accuracy (raw AI output) | 73/100 (73.0%) |
| customer_goal accuracy (after text checks) | 77/100 (77.0%) [95% CI 67.8–84.2%] |
| customer_goal accuracy (raw AI output) | 77/100 (77.0%) |
| mixed flag accuracy | 98/100 (98.0%) |
| required_action strict | 46/100 (46.0%) [95% CI 36.6–55.7%] |
| required_action lenient (acceptable_actions) | 49/100 (49.0%) [95% CI 39.4–58.7%] |
| all three dimensions right (strict) | 27/100 (27.0%) |
| supplier-task precision | n/a (0/0) |
| supplier-task recall (automatic) | 0/36 (0.0%) [95% CI 0–9.6%] |
| supplier-task recall incl. human-confirm proposal | 22/36 (61.1%) |
| false trigger on non-task cases | 0/64 (0.0%) [95% CI 0–5.7%] |
| should be human/clarify but automated | 0/52 (0.0%) [95% CI 0–6.9%] |
| duplicate rows that created a new task | 0/8 (0.0%) |
| task draft completeness | n/a (0/0) |
| automatic actions demoted by confidence | 33/100 (33.0%) |
| latency p50 per case (ms) | 13.5 |

### original / keyword: breakdowns

| Slice | n | issue_type | customer_goal | action lenient | tasks created | false triggers |
| --- | --- | --- | --- | --- | --- | --- |
| ambiguous | 16 | 8/16 (50.0%) | 14/16 (87.5%) | 16/16 (100.0%) | 0 | 0 |
| duplicate | 8 | 6/8 (75.0%) | 5/8 (62.5%) | 0/8 (0.0%) | 0 | 0 |
| missing | 16 | 13/16 (81.2%) | 12/16 (75.0%) | 16/16 (100.0%) | 0 | 0 |
| needed | 28 | 19/28 (67.9%) | 22/28 (78.6%) | 1/28 (3.6%) | 0 | 0 |
| not_needed | 24 | 20/24 (83.3%) | 19/24 (79.2%) | 9/24 (37.5%) | 0 | 0 |
| similar_order | 8 | 7/8 (87.5%) | 5/8 (62.5%) | 7/8 (87.5%) | 0 | 0 |

| Language | n | issue_type | customer_goal | action lenient | false triggers |
| --- | --- | --- | --- | --- | --- |
| en | 20 | 15/20 (75.0%) | 15/20 (75.0%) | 6/20 (30.0%) | 0 |
| zh-Hant | 20 | 17/20 (85.0%) | 17/20 (85.0%) | 9/20 (45.0%) | 0 |
| es | 20 | 13/20 (65.0%) | 16/20 (80.0%) | 10/20 (50.0%) | 0 |
| de | 20 | 13/20 (65.0%) | 16/20 (80.0%) | 11/20 (55.0%) | 0 |
| ja | 20 | 15/20 (75.0%) | 13/20 (65.0%) | 13/20 (65.0%) | 0 |

Confusion (label → system action): CLARIFY_WITH_CUSTOMER -> CLARIFY_WITH_CUSTOMER: 27; CREATE_SUPPLIER_TASK -> CLARIFY_WITH_CUSTOMER: 14; CREATE_SUPPLIER_TASK -> HUMAN_REVIEW: 22; DIRECT_WORKFLOW -> CLARIFY_WITH_CUSTOMER: 1; DIRECT_WORKFLOW -> HUMAN_REVIEW: 11; HUMAN_REVIEW -> CLARIFY_WITH_CUSTOMER: 6; HUMAN_REVIEW -> HUMAN_REVIEW: 19


**False triggers (supplier task created, label says no task) (0)**

none

**Missed triggers (label says task, none created) (36)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| E01 | en | SIZE_MISMATCH/EXCHANGE → CREATE_SUPPLIER_TASK | SIZE_MISMATCH/EXCHANGE → HUMAN_REVIEW | 0.8 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.8 < 0.9: demoted; a human confirms or rejects the proposal. |
| E02 | zh-Hant | SIZE_MISMATCH/EXCHANGE → CREATE_SUPPLIER_TASK | SIZE_MISMATCH/EXCHANGE → HUMAN_REVIEW | 0.8 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.8 < 0.9: demoted; a human confirms or rejects the proposal. |
| E03 | es | SIZE_MISMATCH/EXCHANGE → CREATE_SUPPLIER_TASK | SIZE_MISMATCH/EXCHANGE → HUMAN_REVIEW | 0.8 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.8 < 0.9: demoted; a human confirms or rejects the proposal. |
| E04 | de | SIZE_MISMATCH/EXCHANGE → CREATE_SUPPLIER_TASK | UNCLEAR/EXCHANGE → HUMAN_REVIEW | 0.6 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.6 < 0.9: demoted; a human confirms or rejects the proposal. |
| E05 | ja | SIZE_MISMATCH/EXCHANGE → CREATE_SUPPLIER_TASK | SIZE_MISMATCH/EXCHANGE → HUMAN_REVIEW | 0.8 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.8 < 0.9: demoted; a human confirms or rejects the proposal. |
| E06 | en | SIZE_MISMATCH/EXCHANGE → CREATE_SUPPLIER_TASK | SIZE_MISMATCH/EXCHANGE → HUMAN_REVIEW | 0.8 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.8 < 0.9: demoted; a human confirms or rejects the proposal. |
| E07 | es | SIZE_MISMATCH/EXCHANGE → CREATE_SUPPLIER_TASK | UNCLEAR/EXCHANGE → HUMAN_REVIEW | 0.6 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.6 < 0.9: demoted; a human confirms or rejects the proposal. |
| E08 | zh-Hant | SIZE_MISMATCH/EXCHANGE → CREATE_SUPPLIER_TASK | SIZE_MISMATCH/EXCHANGE → HUMAN_REVIEW | 0.8 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.8 < 0.9: demoted; a human confirms or rejects the proposal. |
| E09 | de | SIZE_MISMATCH/EXCHANGE → CREATE_SUPPLIER_TASK | SIZE_MISMATCH/EXCHANGE → HUMAN_REVIEW | 0.8 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.8 < 0.9: demoted; a human confirms or rejects the proposal. |
| R01 | en | MISSING_ITEM/RESHIP → CREATE_SUPPLIER_TASK | MISSING_ITEM/RESHIP → HUMAN_REVIEW | 0.8 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.8 < 0.9: demoted; a human confirms or rejects the proposal. |
| R02 | zh-Hant | MISSING_ITEM/RESHIP → CREATE_SUPPLIER_TASK | MISSING_ITEM/RESHIP → HUMAN_REVIEW | 0.8 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.8 < 0.9: demoted; a human confirms or rejects the proposal. |
| R03 | es | MISSING_ITEM/RESHIP → CREATE_SUPPLIER_TASK | UNCLEAR/RESHIP → CLARIFY_WITH_CUSTOMER | 0.6 | gate 2 (matches_order): Order TO-50140 has 2 items and the message does not say which one: ask. |
| R04 | de | MISSING_ITEM/RESHIP → CREATE_SUPPLIER_TASK | UNCLEAR/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue UNCLEAR but no requested outcome: ask what the customer wants. |
| R05 | ja | MISSING_ITEM/RESHIP → CREATE_SUPPLIER_TASK | MISSING_ITEM/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| R06 | en | MISSING_ITEM/RESHIP → CREATE_SUPPLIER_TASK | UNCLEAR/RESHIP → HUMAN_REVIEW | 0.6 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.6 < 0.9: demoted; a human confirms or rejects the proposal. |
| R07 | es | MISSING_ITEM/RESHIP → CREATE_SUPPLIER_TASK | UNCLEAR/RESHIP → HUMAN_REVIEW | 0.6 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.6 < 0.9: demoted; a human confirms or rejects the proposal. |
| R08 | ja | MISSING_ITEM/RESHIP → CREATE_SUPPLIER_TASK | UNCLEAR/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue UNCLEAR but no requested outcome: ask what the customer wants. |
| R09 | de | MISSING_ITEM/RESHIP → CREATE_SUPPLIER_TASK | MISSING_ITEM/RESHIP → HUMAN_REVIEW | 0.8 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.8 < 0.9: demoted; a human confirms or rejects the proposal. |
| D01 | en | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | UNCLEAR/REPAIR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 2 (matches_order): No description of the fault: ask. |
| D02 | zh-Hant | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | DEFECT/REPAIR → HUMAN_REVIEW | 0.8 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.8 < 0.9: demoted; a human confirms or rejects the proposal. |
| D03 | es | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | DEFECT/REPAIR → HUMAN_REVIEW | 0.8 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.8 < 0.9: demoted; a human confirms or rejects the proposal. |
| D04 | de | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | DEFECT/REPAIR → HUMAN_REVIEW | 0.8 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.8 < 0.9: demoted; a human confirms or rejects the proposal. |
| D05 | ja | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | DEFECT/BUY_PART → CLARIFY_WITH_CUSTOMER | 0.6 | gate 2 (matches_order): No part number in the message: ask for it (part models are never guessed). |
| D06 | en | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | UNCLEAR/REPAIR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 2 (matches_order): No description of the fault: ask. |
| D07 | de | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | UNCLEAR/REPAIR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 2 (matches_order): No description of the fault: ask. |
| D08 | es | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | UNCLEAR/REPAIR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 2 (matches_order): No description of the fault: ask. |
| D09 | ja | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | DEFECT/BUY_PART → CLARIFY_WITH_CUSTOMER | 0.6 | gate 2 (matches_order): No part number in the message: ask for it (part models are never guessed). |
| P01 | en | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | PART_NEED/BUY_PART → HUMAN_REVIEW | 0.6 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.6 < 0.9: demoted; a human confirms or rejects the proposal. |
| P02 | zh-Hant | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | PART_NEED/BUY_PART → HUMAN_REVIEW | 0.8 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.8 < 0.9: demoted; a human confirms or rejects the proposal. |
| P03 | es | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | PART_NEED/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue PART_NEED but no requested outcome: ask what the customer wants. |
| P04 | de | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | PART_NEED/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue PART_NEED but no requested outcome: ask what the customer wants. |
| P05 | ja | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | PART_NEED/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue PART_NEED but no requested outcome: ask what the customer wants. |
| P06 | zh-Hant | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | PART_NEED/BUY_PART → HUMAN_REVIEW | 0.8 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.8 < 0.9: demoted; a human confirms or rejects the proposal. |
| P07 | de | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | PART_NEED/BUY_PART → HUMAN_REVIEW | 0.8 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.8 < 0.9: demoted; a human confirms or rejects the proposal. |
| P08 | ja | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | PART_NEED/BUY_PART → HUMAN_REVIEW | 0.8 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.8 < 0.9: demoted; a human confirms or rejects the proposal. |
| P09 | en | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | PART_NEED/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue PART_NEED but no requested outcome: ask what the customer wants. |

**Should have gone to a human / clarification but was automated (0)**

none

**Other required_action errors (outside acceptable_actions) (16)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| E10 | en | SIZE_MISMATCH/EXCHANGE → DIRECT_WORKFLOW | SIZE_MISMATCH/EXCHANGE → HUMAN_REVIEW | 0.8 | gate 3 (supplier_necessary): 3 × S in our warehouse: exchange from own stock. -> demoted (confidence 0.8 < 0.9) |
| E12 | de | SIZE_MISMATCH/EXCHANGE → DIRECT_WORKFLOW | SIZE_MISMATCH/EXCHANGE → HUMAN_REVIEW | 0.8 | gate 3 (supplier_necessary): Purchased 50 days ago, outside the 30-day window: the existing policy decides; supplier not needed. -> demoted (confidence 0.8 < 0.9) |
| E13 | zh-Hant | SIZE_MISMATCH/EXCHANGE → DIRECT_WORKFLOW | SIZE_MISMATCH/EXCHANGE → HUMAN_REVIEW | 0.8 | gate 3 (supplier_necessary): Final-sale item: the existing policy decides (no exchange); supplier not needed. -> demoted (confidence 0.8 < 0.9) |
| E14 | es | SIZE_MISMATCH/EXCHANGE → DIRECT_WORKFLOW | SIZE_MISMATCH/EXCHANGE → HUMAN_REVIEW | 0.8 | gate 3 (supplier_necessary): Purchased 40 days ago, outside the 30-day window: the existing policy decides; supplier not needed. -> demoted (confidence 0.8 < 0.9) |
| E15 | zh-Hant | SIZE_MISMATCH/EXCHANGE → DIRECT_WORKFLOW | SIZE_MISMATCH/EXCHANGE → HUMAN_REVIEW | 0.8 | gate 3 (supplier_necessary): 4 × black in our warehouse: exchange from own stock. -> demoted (confidence 0.8 < 0.9) |
| R10 | en | MISSING_ITEM/RESHIP → DIRECT_WORKFLOW | MISSING_ITEM/RESHIP → HUMAN_REVIEW | 0.8 | gate 3 (supplier_necessary): LOST: we shipped it and have 6 in stock: reship from our warehouse. -> demoted (confidence 0.8 < 0.9) |
| R11 | zh-Hant | MISSING_ITEM/RESHIP → DIRECT_WORKFLOW | MISSING_ITEM/RESHIP → HUMAN_REVIEW | 0.8 | gate 3 (supplier_necessary): LOST: we shipped it and have 3 in stock: reship from our warehouse. -> demoted (confidence 0.8 < 0.9) |
| R13 | de | MISSING_ITEM/RESHIP → HUMAN_REVIEW | MISSING_ITEM/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue MISSING_ITEM but no requested outcome: ask what the customer wants. |
| R15 | en | MISSING_ITEM/RESHIP → HUMAN_REVIEW | MISSING_ITEM/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue MISSING_ITEM but no requested outcome: ask what the customer wants. |
| R24 | es | MISSING_ITEM/RESHIP → HUMAN_REVIEW | MISSING_ITEM/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue MISSING_ITEM but no requested outcome: ask what the customer wants. |
| D10 | en | DEFECT/REPAIR → DIRECT_WORKFLOW | DEFECT/REPAIR → HUMAN_REVIEW | 0.8 | gate 3 (supplier_necessary): Purchased 10 days ago: covered by the existing return/refund policy (30 days). Supplier not needed. -> demoted (confidence 0.8 < 0.9) |
| D11 | zh-Hant | DEFECT/REPAIR → DIRECT_WORKFLOW | DEFECT/REPAIR → HUMAN_REVIEW | 0.8 | gate 3 (supplier_necessary): Inside our own 365-day warranty: merchant process. -> demoted (confidence 0.8 < 0.9) |
| P10 | zh-Hant | PART_NEED/BUY_PART → DIRECT_WORKFLOW | PART_NEED/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue PART_NEED but no requested outcome: ask what the customer wants. |
| P11 | es | PART_NEED/BUY_PART → DIRECT_WORKFLOW | PART_NEED/BUY_PART → HUMAN_REVIEW | 0.8 | gate 3 (supplier_necessary): KL-170-FLT (Limescale filter) compatible and 12 in stock: ship it. -> demoted (confidence 0.8 < 0.9) |
| P14 | en | PART_NEED/BUY_PART → HUMAN_REVIEW | PART_NEED/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue PART_NEED but no requested outcome: ask what the customer wants. |
| P15 | en | PART_NEED/BUY_PART → HUMAN_REVIEW | PART_NEED/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue PART_NEED but no requested outcome: ask what the customer wants. |

**Dimension misclassifications (issue_type or customer_goal ≠ label; route may still be right) (44)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| E04 | de | SIZE_MISMATCH/EXCHANGE → CREATE_SUPPLIER_TASK | UNCLEAR/EXCHANGE → HUMAN_REVIEW | 0.6 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.6 < 0.9: demoted; a human confirms or rejects the proposal. |
| E07 | es | SIZE_MISMATCH/EXCHANGE → CREATE_SUPPLIER_TASK | UNCLEAR/EXCHANGE → HUMAN_REVIEW | 0.6 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.6 < 0.9: demoted; a human confirms or rejects the proposal. |
| E11 | ja | SIZE_MISMATCH/EXCHANGE → HUMAN_REVIEW | UNCLEAR/EXCHANGE → HUMAN_REVIEW | 0.6 | gate 3 (supplier_necessary): green out of stock and the supplier has no restock responsibility. |
| E17 | ja | SIZE_MISMATCH/EXCHANGE → CLARIFY_WITH_CUSTOMER | SIZE_MISMATCH/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| E18 | de | SIZE_MISMATCH/EXCHANGE → CLARIFY_WITH_CUSTOMER | UNCLEAR/EXCHANGE → CLARIFY_WITH_CUSTOMER | 0.6 | gate 2 (matches_order): Requested size not stated in the message: ask (never guessed). |
| E20 | ja | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | SIZE_MISMATCH/INFORMATION → HUMAN_REVIEW | 0.6 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue SIZE_MISMATCH): a question, not a request to act; support answers it. No supplier task. |
| E25 | de | SIZE_MISMATCH/EXCHANGE → CLARIFY_WITH_CUSTOMER | UNCLEAR/EXCHANGE → CLARIFY_WITH_CUSTOMER | 0.6 | gate 2 (matches_order): Order TO-2032 not found (no fuzzy matching): ask the customer to confirm it. |
| R03 | es | MISSING_ITEM/RESHIP → CREATE_SUPPLIER_TASK | UNCLEAR/RESHIP → CLARIFY_WITH_CUSTOMER | 0.6 | gate 2 (matches_order): Order TO-50140 has 2 items and the message does not say which one: ask. |
| R04 | de | MISSING_ITEM/RESHIP → CREATE_SUPPLIER_TASK | UNCLEAR/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue UNCLEAR but no requested outcome: ask what the customer wants. |
| R05 | ja | MISSING_ITEM/RESHIP → CREATE_SUPPLIER_TASK | MISSING_ITEM/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| R06 | en | MISSING_ITEM/RESHIP → CREATE_SUPPLIER_TASK | UNCLEAR/RESHIP → HUMAN_REVIEW | 0.6 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.6 < 0.9: demoted; a human confirms or rejects the proposal. |
| R07 | es | MISSING_ITEM/RESHIP → CREATE_SUPPLIER_TASK | UNCLEAR/RESHIP → HUMAN_REVIEW | 0.6 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.6 < 0.9: demoted; a human confirms or rejects the proposal. |
| R08 | ja | MISSING_ITEM/RESHIP → CREATE_SUPPLIER_TASK | UNCLEAR/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue UNCLEAR but no requested outcome: ask what the customer wants. |
| R13 | de | MISSING_ITEM/RESHIP → HUMAN_REVIEW | MISSING_ITEM/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue MISSING_ITEM but no requested outcome: ask what the customer wants. |
| R14 | ja | MISSING_ITEM/RESHIP → HUMAN_REVIEW | UNCLEAR/RESHIP → HUMAN_REVIEW | 0.6 | gate 3 (supplier_necessary): No logistics record for this item: a human checks (not a supplier trigger). |
| R15 | en | MISSING_ITEM/RESHIP → HUMAN_REVIEW | MISSING_ITEM/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue MISSING_ITEM but no requested outcome: ask what the customer wants. |
| R19 | es | MISSING_ITEM/RESHIP → CLARIFY_WITH_CUSTOMER | MISSING_ITEM/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue MISSING_ITEM but no requested outcome: ask what the customer wants. |
| R22 | zh-Hant | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | MISSING_ITEM/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue MISSING_ITEM but no requested outcome: ask what the customer wants. |
| R23 | de | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | MISSING_ITEM/INFORMATION → HUMAN_REVIEW | 0.6 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue MISSING_ITEM): a question, not a request to act; support answers it. No supplier task. |
| R24 | es | MISSING_ITEM/RESHIP → HUMAN_REVIEW | MISSING_ITEM/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue MISSING_ITEM but no requested outcome: ask what the customer wants. |
| D01 | en | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | UNCLEAR/REPAIR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 2 (matches_order): No description of the fault: ask. |
| D05 | ja | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | DEFECT/BUY_PART → CLARIFY_WITH_CUSTOMER | 0.6 | gate 2 (matches_order): No part number in the message: ask for it (part models are never guessed). |
| D06 | en | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | UNCLEAR/REPAIR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 2 (matches_order): No description of the fault: ask. |
| D07 | de | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | UNCLEAR/REPAIR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 2 (matches_order): No description of the fault: ask. |
| D08 | es | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | UNCLEAR/REPAIR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 2 (matches_order): No description of the fault: ask. |
| D09 | ja | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | DEFECT/BUY_PART → CLARIFY_WITH_CUSTOMER | 0.6 | gate 2 (matches_order): No part number in the message: ask for it (part models are never guessed). |
| D12 | de | DEFECT/UNCLEAR → HUMAN_REVIEW | UNCLEAR/UNCLEAR → HUMAN_REVIEW | 0.6 | gate 1 (intent_rules): R2 possible safety issue (fire/smoke/sparks/shock/gas/injury): always a human first. |
| D15 | en | DEFECT/UNCLEAR → HUMAN_REVIEW | UNCLEAR/UNCLEAR → HUMAN_REVIEW | 0.6 | gate 1 (intent_rules): R2 possible safety issue (fire/smoke/sparks/shock/gas/injury): always a human first. |
| D21 | zh-Hant | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | UNCLEAR/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue UNCLEAR but no requested outcome: ask what the customer wants. |
| D22 | es | DEFECT/INFORMATION → CLARIFY_WITH_CUSTOMER | UNCLEAR/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue UNCLEAR but no requested outcome: ask what the customer wants. |
| D24 | ja | DEFECT/REPAIR → HUMAN_REVIEW | DEFECT/BUY_PART → HUMAN_REVIEW | 0.6 | gate 2 (matches_order): Order TO-60203 belongs to a different customer (possible mistyped / similar order number). |
| P03 | es | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | PART_NEED/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue PART_NEED but no requested outcome: ask what the customer wants. |
| P04 | de | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | PART_NEED/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue PART_NEED but no requested outcome: ask what the customer wants. |
| P05 | ja | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | PART_NEED/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue PART_NEED but no requested outcome: ask what the customer wants. |
| P09 | en | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | PART_NEED/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue PART_NEED but no requested outcome: ask what the customer wants. |
| P10 | zh-Hant | PART_NEED/BUY_PART → DIRECT_WORKFLOW | PART_NEED/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue PART_NEED but no requested outcome: ask what the customer wants. |
| P14 | en | PART_NEED/BUY_PART → HUMAN_REVIEW | PART_NEED/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue PART_NEED but no requested outcome: ask what the customer wants. |
| P15 | en | PART_NEED/BUY_PART → HUMAN_REVIEW | PART_NEED/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue PART_NEED but no requested outcome: ask what the customer wants. |
| P16 | en | PART_NEED/BUY_PART → CLARIFY_WITH_CUSTOMER | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue DEFECT but no requested outcome: ask what the customer wants. |
| P17 | zh-Hant | PART_NEED/BUY_PART → CLARIFY_WITH_CUSTOMER | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue DEFECT but no requested outcome: ask what the customer wants. |
| P20 | ja | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | PART_NEED/INFORMATION → HUMAN_REVIEW | 0.6 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue PART_NEED): a question, not a request to act; support answers it. No supplier task. |
| P21 | es | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | PART_NEED/INFORMATION → HUMAN_REVIEW | 0.6 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue PART_NEED): a question, not a request to act; support answers it. No supplier task. |
| P22 | es | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | UNCLEAR/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue UNCLEAR but no requested outcome: ask what the customer wants. |
| P24 | de | PART_NEED/BUY_PART → CLARIFY_WITH_CUSTOMER | PART_NEED/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue PART_NEED but no requested outcome: ask what the customer wants. |

## Held-out 60 — unseen, blind-generated (qwen/qwen3.8-27b), author-labelled, pending human review

* **keyword** run 2026-10-09T09:25:53+00:00 UTC · extractor `keyword-fallback` · 429 retries 0 · LLM fallbacks 0 · keys with >1 open task 0
* **llm** run 2026-10-09T10:03:04+00:00 UTC · extractor `llm:openai/gpt-oss-120b` · 429 retries 0 · LLM fallbacks 0 · keys with >1 open task 0

| Metric | keyword | llm |
| --- | --- | --- |
| issue_type accuracy (after text checks) | 42/60 (70.0%) [95% CI 57.5–80.1%] | 48/60 (80.0%) [95% CI 68.2–88.2%] |
| issue_type accuracy (raw AI output) | 42/60 (70.0%) | 49/60 (81.7%) |
| customer_goal accuracy (after text checks) | 42/60 (70.0%) [95% CI 57.5–80.1%] | 49/60 (81.7%) [95% CI 70.1–89.4%] |
| customer_goal accuracy (raw AI output) | 42/60 (70.0%) | 49/60 (81.7%) |
| mixed flag accuracy | 51/60 (85.0%) | 52/60 (86.7%) |
| required_action strict | 30/60 (50.0%) [95% CI 37.7–62.3%] | 50/60 (83.3%) [95% CI 72.0–90.7%] |
| required_action lenient (acceptable_actions) | 35/60 (58.3%) [95% CI 45.7–69.9%] | 51/60 (85.0%) [95% CI 73.9–91.9%] |
| all three dimensions right (strict) | 20/60 (33.3%) | 35/60 (58.3%) |
| supplier-task precision | n/a (0/0) | 3/4 (75.0%) [95% CI 30.1–95.4%] |
| supplier-task recall (automatic) | 0/3 (0.0%) [95% CI 0–56.2%] | 3/3 (100.0%) [95% CI 43.8–100%] |
| supplier-task recall incl. human-confirm proposal | 3/3 (100.0%) | 3/3 (100.0%) |
| false trigger on non-task cases | 0/57 (0.0%) [95% CI 0–6.3%] | 1/57 (1.8%) [95% CI 0.3–9.3%] |
| should be human/clarify but automated | 0/44 (0.0%) [95% CI 0.0–8.0%] | 2/44 (4.5%) [95% CI 1.3–15.1%] |
| duplicate rows that created a new task | n/a (0/0) | n/a (0/0) |
| task draft completeness | n/a (0/0) | 4/4 (100.0%) |
| automatic actions demoted by confidence | 18/60 (30.0%) | 1/60 (1.7%) |
| latency p50 per case (ms) | 13.55 | 1548.25 |

### heldout / keyword: breakdowns

| Slice | n | issue_type | customer_goal | action lenient | tasks created | false triggers |
| --- | --- | --- | --- | --- | --- | --- |
| clear_request | 8 | 7/8 (87.5%) | 6/8 (75.0%) | 6/8 (75.0%) | 0 | 0 |
| inquiry_about_problem | 5 | 3/5 (60.0%) | 3/5 (60.0%) | 4/5 (80.0%) | 0 | 0 |
| insufficient_info | 9 | 6/9 (66.7%) | 9/9 (100.0%) | 8/9 (88.9%) | 0 | 0 |
| mixed | 9 | 7/9 (77.8%) | 7/9 (77.8%) | 6/9 (66.7%) | 0 | 0 |
| mixed_safety | 1 | 0/1 (0.0%) | 0/1 (0.0%) | 1/1 (100.0%) | 0 | 0 |
| negation | 6 | 5/6 (83.3%) | 5/6 (83.3%) | 5/6 (83.3%) | 0 | 0 |
| part_inquiry | 8 | 6/8 (75.0%) | 3/8 (37.5%) | 4/8 (50.0%) | 0 | 0 |
| pre_purchase | 3 | 0/3 (0.0%) | 0/3 (0.0%) | 0/3 (0.0%) | 0 | 0 |
| refund_only | 11 | 8/11 (72.7%) | 9/11 (81.8%) | 1/11 (9.1%) | 0 | 0 |

| Language | n | issue_type | customer_goal | action lenient | false triggers |
| --- | --- | --- | --- | --- | --- |
| en | 20 | 16/20 (80.0%) | 15/20 (75.0%) | 10/20 (50.0%) | 0 |
| zh-Hant | 8 | 6/8 (75.0%) | 6/8 (75.0%) | 7/8 (87.5%) | 0 |
| es | 11 | 6/11 (54.5%) | 8/11 (72.7%) | 4/11 (36.4%) | 0 |
| de | 11 | 5/11 (45.5%) | 5/11 (45.5%) | 7/11 (63.6%) | 0 |
| ja | 10 | 9/10 (90.0%) | 8/10 (80.0%) | 7/10 (70.0%) | 0 |

Confusion (label → system action): CLARIFY_WITH_CUSTOMER -> CLARIFY_WITH_CUSTOMER: 16; CLARIFY_WITH_CUSTOMER -> HUMAN_REVIEW: 3; CREATE_SUPPLIER_TASK -> HUMAN_REVIEW: 3; DIRECT_WORKFLOW -> CLARIFY_WITH_CUSTOMER: 3; DIRECT_WORKFLOW -> HUMAN_REVIEW: 10; HUMAN_REVIEW -> CLARIFY_WITH_CUSTOMER: 11; HUMAN_REVIEW -> HUMAN_REVIEW: 14


**False triggers (supplier task created, label says no task) (0)**

none

**Missed triggers (label says task, none created) (3)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| H46 | en | SIZE_MISMATCH/EXCHANGE → CREATE_SUPPLIER_TASK | SIZE_MISMATCH/EXCHANGE → HUMAN_REVIEW | 0.8 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.8 < 0.9: demoted; a human confirms or rejects the proposal. |
| H50 | ja | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | PART_NEED/BUY_PART → HUMAN_REVIEW | 0.8 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.8 < 0.9: demoted; a human confirms or rejects the proposal. |
| H51 | en | SIZE_MISMATCH/EXCHANGE → CREATE_SUPPLIER_TASK | SIZE_MISMATCH/EXCHANGE → HUMAN_REVIEW | 0.8 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.8 < 0.9: demoted; a human confirms or rejects the proposal. |

**Should have gone to a human / clarification but was automated (0)**

none

**Other required_action errors (outside acceptable_actions) (24)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| H01 | en | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H02 | en | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | SIZE_MISMATCH/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue SIZE_MISMATCH but no requested outcome: ask what the customer wants. |
| H03 | en | DEFECT/INFORMATION → HUMAN_REVIEW | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue DEFECT but no requested outcome: ask what the customer wants. |
| H04 | de | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | PART_NEED/BUY_PART → CLARIFY_WITH_CUSTOMER | 0.8 | gate 2 (matches_order): No order number in the message and no linked order: ask for it. |
| H09 | es | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | SIZE_MISMATCH/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue SIZE_MISMATCH but no requested outcome: ask what the customer wants. |
| H10 | de | DEFECT/INFORMATION → HUMAN_REVIEW | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue DEFECT but no requested outcome: ask what the customer wants. |
| H15 | ja | PART_NEED/INFORMATION → HUMAN_REVIEW | PART_NEED/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue PART_NEED but no requested outcome: ask what the customer wants. |
| H16 | en | SIZE_MISMATCH/REFUND → DIRECT_WORKFLOW | SIZE_MISMATCH/REFUND → HUMAN_REVIEW | 0.8 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.8 < 0.9) |
| H17 | en | DEFECT/REFUND → DIRECT_WORKFLOW | DEFECT/REFUND → HUMAN_REVIEW | 0.8 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.8 < 0.9) |
| H18 | en | SIZE_MISMATCH/REFUND → DIRECT_WORKFLOW | SIZE_MISMATCH/REFUND → HUMAN_REVIEW | 0.8 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.8 < 0.9) |
| H19 | de | DEFECT/REFUND → DIRECT_WORKFLOW | PART_NEED/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H20 | es | UNCLEAR/REFUND → DIRECT_WORKFLOW | UNCLEAR/REFUND → HUMAN_REVIEW | 0.6 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.6 < 0.9) |
| H21 | es | NO_ISSUE_INQUIRY/REFUND → DIRECT_WORKFLOW | UNCLEAR/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H22 | ja | SIZE_MISMATCH/REFUND → DIRECT_WORKFLOW | SIZE_MISMATCH/REFUND → HUMAN_REVIEW | 0.8 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.8 < 0.9) |
| H23 | en | DEFECT/REFUND → DIRECT_WORKFLOW | DEFECT/REFUND → HUMAN_REVIEW | 0.8 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.8 < 0.9) |
| H24 | zh-Hant | SIZE_MISMATCH/REFUND → DIRECT_WORKFLOW | UNCLEAR/REFUND → HUMAN_REVIEW | 0.6 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.6 < 0.9) |
| H28 | en | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/REFUND → HUMAN_REVIEW | 0.8 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.8 < 0.9) |
| H32 | es | DEFECT/REFUND/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/REFUND → HUMAN_REVIEW | 0.8 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.8 < 0.9) |
| H35 | ja | UNCLEAR/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | UNCLEAR/REFUND → HUMAN_REVIEW | 0.6 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.6 < 0.9) |
| H39 | es | SIZE_MISMATCH/REFUND → DIRECT_WORKFLOW | UNCLEAR/REFUND → HUMAN_REVIEW | 0.6 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.6 < 0.9) |
| H45 | en | UNCLEAR/REFUND → DIRECT_WORKFLOW | UNCLEAR/REFUND → HUMAN_REVIEW | 0.6 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.6 < 0.9) |
| H48 | es | DEFECT/REPAIR → DIRECT_WORKFLOW | UNCLEAR/REPAIR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 2 (matches_order): No description of the fault: ask. |
| H53 | de | PART_NEED/INFORMATION → HUMAN_REVIEW | PART_NEED/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue PART_NEED but no requested outcome: ask what the customer wants. |
| H58 | es | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | SIZE_MISMATCH/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue SIZE_MISMATCH but no requested outcome: ask what the customer wants. |

**Dimension misclassifications (issue_type or customer_goal ≠ label; route may still be right) (28)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| H01 | en | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H02 | en | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | SIZE_MISMATCH/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue SIZE_MISMATCH but no requested outcome: ask what the customer wants. |
| H03 | en | DEFECT/INFORMATION → HUMAN_REVIEW | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue DEFECT but no requested outcome: ask what the customer wants. |
| H04 | de | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | PART_NEED/BUY_PART → CLARIFY_WITH_CUSTOMER | 0.8 | gate 2 (matches_order): No order number in the message and no linked order: ask for it. |
| H06 | en | UNCLEAR/INFORMATION → HUMAN_REVIEW | MISSING_ITEM/INFORMATION → HUMAN_REVIEW | 0.6 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue MISSING_ITEM): a question, not a request to act; support answers it. No supplier task. |
| H08 | zh-Hant | SIZE_MISMATCH/INFORMATION → HUMAN_REVIEW | SIZE_MISMATCH/REFUND → HUMAN_REVIEW | 0.8 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.8 < 0.9) |
| H09 | es | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | SIZE_MISMATCH/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue SIZE_MISMATCH but no requested outcome: ask what the customer wants. |
| H10 | de | DEFECT/INFORMATION → HUMAN_REVIEW | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue DEFECT but no requested outcome: ask what the customer wants. |
| H12 | en | DEFECT/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | 0.6 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue NO_ISSUE_INQUIRY): a question, not a request to act; support answers it. No supplier task. |
| H13 | de | PART_NEED/INFORMATION → HUMAN_REVIEW | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue DEFECT but no requested outcome: ask what the customer wants. |
| H15 | ja | PART_NEED/INFORMATION → HUMAN_REVIEW | PART_NEED/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue PART_NEED but no requested outcome: ask what the customer wants. |
| H19 | de | DEFECT/REFUND → DIRECT_WORKFLOW | PART_NEED/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H21 | es | NO_ISSUE_INQUIRY/REFUND → DIRECT_WORKFLOW | UNCLEAR/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H24 | zh-Hant | SIZE_MISMATCH/REFUND → DIRECT_WORKFLOW | UNCLEAR/REFUND → HUMAN_REVIEW | 0.6 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.6 < 0.9) |
| H28 | en | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/REFUND → HUMAN_REVIEW | 0.8 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.8 < 0.9) |
| H29 | zh-Hant | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | UNCLEAR/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H33 | de | UNCLEAR/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H34 | de | DEFECT/UNCLEAR/mixed → HUMAN_REVIEW | PART_NEED/REFUND → HUMAN_REVIEW | 0.8 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.8 < 0.9) |
| H35 | ja | UNCLEAR/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | UNCLEAR/REFUND → HUMAN_REVIEW | 0.6 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.6 < 0.9) |
| H37 | en | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | UNCLEAR/INFORMATION → HUMAN_REVIEW | 0.6 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue UNCLEAR): a question, not a request to act; support answers it. No supplier task. |
| H39 | es | SIZE_MISMATCH/REFUND → DIRECT_WORKFLOW | UNCLEAR/REFUND → HUMAN_REVIEW | 0.6 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.6 < 0.9) |
| H41 | de | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | UNCLEAR/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue UNCLEAR but no requested outcome: ask what the customer wants. |
| H47 | zh-Hant | MISSING_ITEM/INFORMATION → HUMAN_REVIEW | MISSING_ITEM/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue MISSING_ITEM but no requested outcome: ask what the customer wants. |
| H48 | es | DEFECT/REPAIR → DIRECT_WORKFLOW | UNCLEAR/REPAIR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 2 (matches_order): No description of the fault: ask. |
| H53 | de | PART_NEED/INFORMATION → HUMAN_REVIEW | PART_NEED/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue PART_NEED but no requested outcome: ask what the customer wants. |
| H55 | en | SIZE_MISMATCH/EXCHANGE → CLARIFY_WITH_CUSTOMER | SIZE_MISMATCH/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H58 | es | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | SIZE_MISMATCH/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.6 | gate 1 (intent_rules): R7 issue SIZE_MISMATCH but no requested outcome: ask what the customer wants. |
| H60 | ja | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | PART_NEED/INFORMATION → HUMAN_REVIEW | 0.6 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue PART_NEED): a question, not a request to act; support answers it. No supplier task. |

### heldout / llm: breakdowns

| Slice | n | issue_type | customer_goal | action lenient | tasks created | false triggers |
| --- | --- | --- | --- | --- | --- | --- |
| clear_request | 8 | 6/8 (75.0%) | 7/8 (87.5%) | 7/8 (87.5%) | 3 | 0 |
| inquiry_about_problem | 5 | 2/5 (40.0%) | 4/5 (80.0%) | 3/5 (60.0%) | 0 | 0 |
| insufficient_info | 9 | 9/9 (100.0%) | 6/9 (66.7%) | 9/9 (100.0%) | 0 | 0 |
| mixed | 9 | 8/9 (88.9%) | 7/9 (77.8%) | 6/9 (66.7%) | 0 | 0 |
| mixed_safety | 1 | 1/1 (100.0%) | 0/1 (0.0%) | 1/1 (100.0%) | 0 | 0 |
| negation | 6 | 5/6 (83.3%) | 6/6 (100.0%) | 6/6 (100.0%) | 0 | 0 |
| part_inquiry | 8 | 4/8 (50.0%) | 5/8 (62.5%) | 6/8 (75.0%) | 1 | 1 |
| pre_purchase | 3 | 3/3 (100.0%) | 3/3 (100.0%) | 3/3 (100.0%) | 0 | 0 |
| refund_only | 11 | 10/11 (90.9%) | 11/11 (100.0%) | 10/11 (90.9%) | 0 | 0 |

| Language | n | issue_type | customer_goal | action lenient | false triggers |
| --- | --- | --- | --- | --- | --- |
| en | 20 | 16/20 (80.0%) | 19/20 (95.0%) | 18/20 (90.0%) | 0 |
| zh-Hant | 8 | 8/8 (100.0%) | 5/8 (62.5%) | 6/8 (75.0%) | 0 |
| es | 11 | 9/11 (81.8%) | 9/11 (81.8%) | 8/11 (72.7%) | 0 |
| de | 11 | 9/11 (81.8%) | 8/11 (72.7%) | 9/11 (81.8%) | 1 |
| ja | 10 | 6/10 (60.0%) | 8/10 (80.0%) | 10/10 (100.0%) | 0 |

Confusion (label → system action): CLARIFY_WITH_CUSTOMER -> CLARIFY_WITH_CUSTOMER: 15; CLARIFY_WITH_CUSTOMER -> DIRECT_WORKFLOW: 1; CLARIFY_WITH_CUSTOMER -> HUMAN_REVIEW: 3; CREATE_SUPPLIER_TASK -> CREATE_SUPPLIER_TASK: 3; DIRECT_WORKFLOW -> CLARIFY_WITH_CUSTOMER: 1; DIRECT_WORKFLOW -> DIRECT_WORKFLOW: 11; DIRECT_WORKFLOW -> HUMAN_REVIEW: 1; HUMAN_REVIEW -> CLARIFY_WITH_CUSTOMER: 3; HUMAN_REVIEW -> CREATE_SUPPLIER_TASK: 1; HUMAN_REVIEW -> HUMAN_REVIEW: 21


**False triggers (supplier task created, label says no task) (1)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| H13 | de | PART_NEED/INFORMATION → HUMAN_REVIEW | DEFECT/BUY_PART → CREATE_SUPPLIER_TASK | 0.97 | gates 1-4 passed: KL-170-LID (Lid assembly) compatible but 0 in stock; Kettleworks Ltd. (MOCK supplier) supplies parts: confirm availability and lead time. |

**Missed triggers (label says task, none created) (0)**

none

**Should have gone to a human / clarification but was automated (2)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| H13 | de | PART_NEED/INFORMATION → HUMAN_REVIEW | DEFECT/BUY_PART → CREATE_SUPPLIER_TASK | 0.97 | gates 1-4 passed: KL-170-LID (Lid assembly) compatible but 0 in stock; Kettleworks Ltd. (MOCK supplier) supplies parts: confirm availability and lead time. |
| H32 | es | DEFECT/REFUND/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/REFUND → DIRECT_WORKFLOW | 0.98 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. |

**Other required_action errors (outside acceptable_actions) (7)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| H08 | zh-Hant | SIZE_MISMATCH/INFORMATION → HUMAN_REVIEW | SIZE_MISMATCH/EXCHANGE/mixed → CLARIFY_WITH_CUSTOMER | 0.88 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H12 | en | DEFECT/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/INFORMATION/mixed → CLARIFY_WITH_CUSTOMER | 0.96 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H14 | es | PART_NEED/INFORMATION → HUMAN_REVIEW | PART_NEED/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.96 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H19 | de | DEFECT/REFUND → DIRECT_WORKFLOW | DEFECT/REFUND → HUMAN_REVIEW | 0.64 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.64 < 0.9) |
| H28 | en | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/INFORMATION → HUMAN_REVIEW | 0.96 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. |
| H30 | zh-Hant | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/REPAIR → HUMAN_REVIEW | 0.93 | gate 2 (matches_order): Several order numbers in the message (TO-40005, TO-50120). |
| H48 | es | DEFECT/REPAIR → DIRECT_WORKFLOW | DEFECT/REPAIR/mixed → CLARIFY_WITH_CUSTOMER | 0.99 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |

**Dimension misclassifications (issue_type or customer_goal ≠ label; route may still be right) (22)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| H06 | en | UNCLEAR/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | 0.83 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue NO_ISSUE_INQUIRY): a question, not a request to act; support answers it. No supplier task. |
| H07 | en | PART_NEED/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | 0.99 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue NO_ISSUE_INQUIRY): a question, not a request to act; support answers it. No supplier task. |
| H08 | zh-Hant | SIZE_MISMATCH/INFORMATION → HUMAN_REVIEW | SIZE_MISMATCH/EXCHANGE/mixed → CLARIFY_WITH_CUSTOMER | 0.88 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H11 | ja | SIZE_MISMATCH/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | 0.98 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue NO_ISSUE_INQUIRY): a question, not a request to act; support answers it. No supplier task. |
| H12 | en | DEFECT/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/INFORMATION/mixed → CLARIFY_WITH_CUSTOMER | 0.96 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H13 | de | PART_NEED/INFORMATION → HUMAN_REVIEW | DEFECT/BUY_PART → CREATE_SUPPLIER_TASK | 0.97 | gates 1-4 passed: KL-170-LID (Lid assembly) compatible but 0 in stock; Kettleworks Ltd. (MOCK supplier) supplies parts: confirm availability and lead time. |
| H14 | es | PART_NEED/INFORMATION → HUMAN_REVIEW | PART_NEED/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.96 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H15 | ja | PART_NEED/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | 0.99 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue NO_ISSUE_INQUIRY): a question, not a request to act; support answers it. No supplier task. |
| H28 | en | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/INFORMATION → HUMAN_REVIEW | 0.96 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. |
| H30 | zh-Hant | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/REPAIR → HUMAN_REVIEW | 0.93 | gate 2 (matches_order): Several order numbers in the message (TO-40005, TO-50120). |
| H31 | es | UNCLEAR/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.93 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H34 | de | DEFECT/UNCLEAR/mixed → HUMAN_REVIEW | DEFECT/INFORMATION → HUMAN_REVIEW | 0.84 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. |
| H40 | es | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | DEFECT/INFORMATION → HUMAN_REVIEW | 0.97 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. |
| H41 | de | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | DEFECT/REPAIR → CLARIFY_WITH_CUSTOMER | 0.93 | gate 2 (matches_order): No order number in the message and no linked order: ask for it. |
| H44 | ja | MISSING_ITEM/UNCLEAR → CLARIFY_WITH_CUSTOMER | MISSING_ITEM/RESHIP → CLARIFY_WITH_CUSTOMER | 0.99 | gate 2 (matches_order): Order TO-703031 not found (no fuzzy matching): ask the customer to confirm it. |
| H45 | en | UNCLEAR/REFUND → DIRECT_WORKFLOW | NO_ISSUE_INQUIRY/REFUND → DIRECT_WORKFLOW | 0.97 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. |
| H47 | zh-Hant | MISSING_ITEM/INFORMATION → HUMAN_REVIEW | MISSING_ITEM/RESHIP → HUMAN_REVIEW | 0.99 | gate 3 (supplier_necessary): Carrier shows the item delivered in full; the claim conflicts with our data. A human investigates before anyone reships. |
| H50 | ja | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | DEFECT/BUY_PART → CREATE_SUPPLIER_TASK | 0.99 | gates 1-4 passed: KL-170-LID (Lid assembly) compatible but 0 in stock; Kettleworks Ltd. (MOCK supplier) supplies parts: confirm availability and lead time. |
| H52 | es | PART_NEED/BUY_PART → CLARIFY_WITH_CUSTOMER | DEFECT/BUY_PART → CLARIFY_WITH_CUSTOMER | 0.87 | gate 2 (matches_order): No order number in the message and no linked order: ask for it. |
| H53 | de | PART_NEED/INFORMATION → HUMAN_REVIEW | DEFECT/INFORMATION → HUMAN_REVIEW | 0.89 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. |
| H54 | ja | PART_NEED/INFORMATION → HUMAN_REVIEW | PART_NEED/BUY_PART → HUMAN_REVIEW | 0.99 | gate 1 (intent_rules): R8 the text is question-form but the AI goal is BUY_PART: a human answers (no automatic action on a question). |
| H60 | ja | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | MISSING_ITEM/INFORMATION → HUMAN_REVIEW | 0.83 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue MISSING_ITEM): a question, not a request to act; support answers it. No supplier task. |

**Confidence analysis (LLM self-report; 60 rows with a confidence)**

* *action wrong*: right {'n': 51, 'min': 0.9, 'p25': 0.97, 'median': 0.99, 'max': 0.99, 'mean': 0.977} · wrong {'n': 9, 'min': 0.93, 'p25': 0.96, 'median': 0.97, 'max': 0.99, 'mean': 0.969} · P(conf right > conf wrong) = 0.687 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 0/9, right 0/51; t=0.85: wrong 0/9, right 0/51; t=0.9: wrong 0/9, right 0/51; t=0.95: wrong 1/9, right 7/51; t=0.99: wrong 7/9, right 20/51
  * right/n per bucket: [0, 0.8): 0/0; [0.8, 0.9): 0/0; [0.9, 0.95): 7/8; [0.95, 0.99): 13/19; [0.99, 1.0]: 31/33
* *any dimension wrong*: right {'n': 35, 'min': 0.9, 'p25': 0.98, 'median': 0.99, 'max': 0.99, 'mean': 0.981} · wrong {'n': 25, 'min': 0.93, 'p25': 0.96, 'median': 0.97, 'max': 0.99, 'mean': 0.968} · P(conf right > conf wrong) = 0.69 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 0/25, right 0/35; t=0.85: wrong 0/25, right 0/35; t=0.9: wrong 0/25, right 0/35; t=0.95: wrong 6/25, right 2/35; t=0.99: wrong 16/25, right 11/35
  * right/n per bucket: [0, 0.8): 0/0; [0.8, 0.9): 0/0; [0.9, 0.95): 2/8; [0.95, 0.99): 9/19; [0.99, 1.0]: 24/33

## Reading these numbers


