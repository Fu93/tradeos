# Supplier routing eval — round 2 (rules `supplier-routing-rules/0.2.0 (MVP 1 experiment, round 2)`)

Two sets, reported **separately** (never pooled). Every rate is `correct/n (%)`; key rates carry a Wilson 95% confidence interval. All operational data is MOCK. Rules and frozen labels are identical for every run.

**Models / providers.** Production extractor is `openai/gpt-oss-20b` on **Groq**. Runs named `llm-120b-groq` used `openai/gpt-oss-120b` on Groq (the Groq free-tier daily token cap for 20b was exhausted on 2026-10-09). Runs named `llm-20b-nvidia` used the production model `openai/gpt-oss-20b` served by **NVIDIA** (integrate.api.nvidia.com, eval-only key): same model weights as production, different provider (serving stack/sampling defaults may differ slightly from Groq). Held-out set NOT used for tuning: rules 0.2.0 unchanged since before any held-out run.

Round-1 history: [routing-results-round1-rules011.md](routing-results-round1-rules011.md), [routing-results-run1.md](routing-results-run1.md).

## Original 100 — regression set of known scenarios (author-written)

* **llm-20b-nvidia** run 2026-10-09T11:38:35+00:00 UTC · provider NVIDIA · model `openai/gpt-oss-20b` · extractor `llm:openai/gpt-oss-20b` · 429 retries 0 · network retries 0 · LLM fallbacks 0 · keys with >1 open task 0
* **llm-120b-groq** run 2026-10-09T10:23:44+00:00 UTC · provider Groq · model `openai/gpt-oss-120b` · extractor `llm:openai/gpt-oss-120b` · 429 retries 0 · network retries 0 · LLM fallbacks 0 · keys with >1 open task 0
* **keyword** run 2026-10-09T09:25:52+00:00 UTC · provider — · model `—` · extractor `keyword-fallback` · 429 retries 0 · network retries 0 · LLM fallbacks 0 · keys with >1 open task 0

| Metric | llm-20b-nvidia | llm-120b-groq | keyword |
| --- | --- | --- | --- |
| issue_type accuracy (after text checks) | 88/100 (88.0%) [95% CI 80.2–93.0%] | 96/100 (96.0%) [95% CI 90.2–98.4%] | 73/100 (73.0%) [95% CI 63.6–80.7%] |
| issue_type accuracy (raw AI output) | 88/100 (88.0%) | 96/100 (96.0%) | 73/100 (73.0%) |
| customer_goal accuracy (after text checks) | 90/100 (90.0%) [95% CI 82.6–94.5%] | 93/100 (93.0%) [95% CI 86.3–96.6%] | 77/100 (77.0%) [95% CI 67.8–84.2%] |
| customer_goal accuracy (raw AI output) | 90/100 (90.0%) | 93/100 (93.0%) | 77/100 (77.0%) |
| mixed flag accuracy | 98/100 (98.0%) | 96/100 (96.0%) | 98/100 (98.0%) |
| required_action strict | 90/100 (90.0%) [95% CI 82.6–94.5%] | 91/100 (91.0%) [95% CI 83.8–95.2%] | 46/100 (46.0%) [95% CI 36.6–55.7%] |
| required_action lenient (acceptable_actions) | 91/100 (91.0%) [95% CI 83.8–95.2%] | 92/100 (92.0%) [95% CI 85.0–95.9%] | 49/100 (49.0%) [95% CI 39.4–58.7%] |
| all three dimensions right (strict) | 79/100 (79.0%) | 85/100 (85.0%) | 27/100 (27.0%) |
| supplier-task precision | 29/29 (100.0%) [95% CI 88.3–100%] | 30/30 (100.0%) [95% CI 88.6–100%] | n/a (0/0) |
| supplier-task recall (automatic) | 29/36 (80.6%) [95% CI 65.0–90.2%] | 30/36 (83.3%) [95% CI 68.1–92.1%] | 0/36 (0.0%) [95% CI 0–9.6%] |
| supplier-task recall incl. human-confirm proposal | 30/36 (83.3%) | 31/36 (86.1%) | 22/36 (61.1%) |
| false trigger on non-task cases | 0/64 (0.0%) [95% CI 0–5.7%] | 0/64 (0.0%) [95% CI 0–5.7%] | 0/64 (0.0%) [95% CI 0–5.7%] |
| should be human/clarify but automated | 0/52 (0.0%) [95% CI 0–6.9%] | 0/52 (0.0%) [95% CI 0–6.9%] | 0/52 (0.0%) [95% CI 0–6.9%] |
| duplicate rows that created a new task | 0/8 (0.0%) | 1/8 (12.5%) | 0/8 (0.0%) |
| task draft completeness | 23/23 (100.0%) | 24/24 (100.0%) | n/a (0/0) |
| automatic actions demoted by confidence | 2/100 (2.0%) | 2/100 (2.0%) | 33/100 (33.0%) |
| latency p50 per case (ms) | 13786.35 | 1268.5 | 13.5 |

### original / llm-20b-nvidia: breakdowns

| Slice | n | issue_type | customer_goal | action lenient | tasks created | false triggers |
| --- | --- | --- | --- | --- | --- | --- |
| ambiguous | 16 | 13/16 (81.2%) | 14/16 (87.5%) | 16/16 (100.0%) | 0 | 0 |
| duplicate | 8 | 6/8 (75.0%) | 6/8 (75.0%) | 6/8 (75.0%) | 6 | 0 |
| missing | 16 | 13/16 (81.2%) | 14/16 (87.5%) | 16/16 (100.0%) | 0 | 0 |
| needed | 28 | 25/28 (89.3%) | 26/28 (92.9%) | 23/28 (82.1%) | 23 | 0 |
| not_needed | 24 | 23/24 (95.8%) | 22/24 (91.7%) | 22/24 (91.7%) | 0 | 0 |
| similar_order | 8 | 8/8 (100.0%) | 8/8 (100.0%) | 8/8 (100.0%) | 0 | 0 |

| Language | n | issue_type | customer_goal | action lenient | false triggers |
| --- | --- | --- | --- | --- | --- |
| en | 20 | 17/20 (85.0%) | 17/20 (85.0%) | 17/20 (85.0%) | 0 |
| zh-Hant | 20 | 15/20 (75.0%) | 18/20 (90.0%) | 19/20 (95.0%) | 0 |
| es | 20 | 20/20 (100.0%) | 19/20 (95.0%) | 19/20 (95.0%) | 0 |
| de | 20 | 19/20 (95.0%) | 20/20 (100.0%) | 19/20 (95.0%) | 0 |
| ja | 20 | 17/20 (85.0%) | 16/20 (80.0%) | 17/20 (85.0%) | 0 |

Confusion (label → system action): CLARIFY_WITH_CUSTOMER -> CLARIFY_WITH_CUSTOMER: 26; CLARIFY_WITH_CUSTOMER -> HUMAN_REVIEW: 1; CREATE_SUPPLIER_TASK -> CLARIFY_WITH_CUSTOMER: 4; CREATE_SUPPLIER_TASK -> CREATE_SUPPLIER_TASK: 29; CREATE_SUPPLIER_TASK -> HUMAN_REVIEW: 3; DIRECT_WORKFLOW -> CLARIFY_WITH_CUSTOMER: 1; DIRECT_WORKFLOW -> DIRECT_WORKFLOW: 10; DIRECT_WORKFLOW -> HUMAN_REVIEW: 1; HUMAN_REVIEW -> HUMAN_REVIEW: 25


**False triggers (supplier task created, label says no task) (0)**

none

**Missed triggers (label says task, none created) (7)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| D03 | es | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.8 | gate 1 (intent_rules): R7 issue DEFECT but no requested outcome: ask what the customer wants. |
| D04 | de | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | DEFECT/REPAIR/mixed → CLARIFY_WITH_CUSTOMER | 0.95 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| D05 | ja | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | DEFECT/REPAIR/mixed → CLARIFY_WITH_CUSTOMER | 0.95 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| P01 | en | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | DEFECT/BUY_PART → HUMAN_REVIEW | 0.85 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.85 < 0.9: demoted; a human confirms or rejects the proposal. |
| P05 | ja | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue NO_ISSUE_INQUIRY): a question, not a request to act; support answers it. No supplier task. |
| P08 | ja | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | DEFECT/EXCHANGE → CLARIFY_WITH_CUSTOMER | 0.75 | gate 2 (matches_order): No description of the fault: ask. |
| P09 | en | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | MISSING_ITEM/RESHIP → HUMAN_REVIEW | 0.85 | gate 3 (supplier_necessary): Carrier shows the item delivered in full; the claim conflicts with our data. A human investigates before anyone reships. |

**Should have gone to a human / clarification but was automated (0)**

none

**Other required_action errors (outside acceptable_actions) (2)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| D10 | en | DEFECT/REPAIR → DIRECT_WORKFLOW | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.8 | gate 1 (intent_rules): R7 issue DEFECT but no requested outcome: ask what the customer wants. |
| P10 | zh-Hant | PART_NEED/BUY_PART → DIRECT_WORKFLOW | DEFECT/BUY_PART → HUMAN_REVIEW | 0.85 | gate 3 (supplier_necessary): BP-BUCKLE-25 (25 mm buckle) compatible and 30 in stock: ship it. -> demoted (confidence 0.85 < 0.9) |

**Dimension misclassifications (issue_type or customer_goal ≠ label; route may still be right) (18)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| E18 | de | SIZE_MISMATCH/EXCHANGE → CLARIFY_WITH_CUSTOMER | NO_ISSUE_INQUIRY/EXCHANGE → CLARIFY_WITH_CUSTOMER | 0.95 | gate 2 (matches_order): Requested size not stated in the message: ask (never guessed). |
| E20 | ja | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | SIZE_MISMATCH/EXCHANGE → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R8 the text is question-form but the AI goal is EXCHANGE: a human answers (no automatic action on a question). |
| E21 | zh-Hant | SIZE_MISMATCH/UNCLEAR → CLARIFY_WITH_CUSTOMER | SIZE_MISMATCH/EXCHANGE → CLARIFY_WITH_CUSTOMER | 0.95 | gate 2 (matches_order): Requested size not stated in the message: ask (never guessed). |
| R22 | zh-Hant | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | MISSING_ITEM/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue MISSING_ITEM): a question, not a request to act; support answers it. No supplier task. |
| D03 | es | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.8 | gate 1 (intent_rules): R7 issue DEFECT but no requested outcome: ask what the customer wants. |
| D10 | en | DEFECT/REPAIR → DIRECT_WORKFLOW | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.8 | gate 1 (intent_rules): R7 issue DEFECT but no requested outcome: ask what the customer wants. |
| D15 | en | DEFECT/UNCLEAR → HUMAN_REVIEW | DEFECT/INFORMATION → HUMAN_REVIEW | 0.9 | gate 1 (intent_rules): R2 possible safety issue (fire/smoke/sparks/shock/gas/injury): always a human first. |
| D17 | zh-Hant | DEFECT/REPAIR → CLARIFY_WITH_CUSTOMER | DEFECT/EXCHANGE → CLARIFY_WITH_CUSTOMER | 0.85 | gate 2 (matches_order): No order number in the message and no linked order: ask for it. |
| D19 | ja | DEFECT/REPAIR → CLARIFY_WITH_CUSTOMER | DEFECT/EXCHANGE → CLARIFY_WITH_CUSTOMER | 0.85 | gate 2 (matches_order): No order number in the message and no linked order: ask for it. |
| D21 | zh-Hant | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | UNCLEAR/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.8 | gate 1 (intent_rules): R7 issue UNCLEAR but no requested outcome: ask what the customer wants. |
| P01 | en | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | DEFECT/BUY_PART → HUMAN_REVIEW | 0.85 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.85 < 0.9: demoted; a human confirms or rejects the proposal. |
| P05 | ja | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue NO_ISSUE_INQUIRY): a question, not a request to act; support answers it. No supplier task. |
| P06 | zh-Hant | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | NO_ISSUE_INQUIRY/BUY_PART → CREATE_SUPPLIER_TASK | 0.95 | gates 1-4 passed: KL-170-GSK is not in our parts table; Kettleworks Ltd. (MOCK supplier) is responsible for compatibility: confirm model, compatibility and availability. |
| P08 | ja | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | DEFECT/EXCHANGE → CLARIFY_WITH_CUSTOMER | 0.75 | gate 2 (matches_order): No description of the fault: ask. |
| P09 | en | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | MISSING_ITEM/RESHIP → HUMAN_REVIEW | 0.85 | gate 3 (supplier_necessary): Carrier shows the item delivered in full; the claim conflicts with our data. A human investigates before anyone reships. |
| P10 | zh-Hant | PART_NEED/BUY_PART → DIRECT_WORKFLOW | DEFECT/BUY_PART → HUMAN_REVIEW | 0.85 | gate 3 (supplier_necessary): BP-BUCKLE-25 (25 mm buckle) compatible and 30 in stock: ship it. -> demoted (confidence 0.85 < 0.9) |
| P16 | en | PART_NEED/BUY_PART → CLARIFY_WITH_CUSTOMER | DEFECT/BUY_PART → CLARIFY_WITH_CUSTOMER | 0.95 | gate 2 (matches_order): No part number in the message: ask for it (part models are never guessed). |
| P17 | zh-Hant | PART_NEED/BUY_PART → CLARIFY_WITH_CUSTOMER | DEFECT/BUY_PART → CLARIFY_WITH_CUSTOMER | 0.95 | gate 2 (matches_order): No part number in the message: ask for it (part models are never guessed). |

**Confidence analysis — LLM self-report; 100 rows**

* *action wrong*: right {'n': 91, 'min': 0.6, 'p25': 0.95, 'median': 0.95, 'max': 0.99, 'mean': 0.946} · wrong {'n': 9, 'min': 0.8, 'p25': 0.95, 'median': 0.95, 'max': 0.95, 'mean': 0.917} · P(conf right > conf wrong) = 0.667 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 0/9, right 3/91; t=0.85: wrong 2/9, right 4/91; t=0.9: wrong 2/9, right 4/91; t=0.95: wrong 2/9, right 9/91; t=0.99: wrong 9/9, right 67/91
  * right/n per bucket: [0, 0.8): 3/3; [0.8, 0.9): 1/3; [0.9, 0.95): 5/5; [0.95, 0.99): 58/65; [0.99, 1.0]: 24/24
* *any dimension wrong*: right {'n': 80, 'min': 0.6, 'p25': 0.95, 'median': 0.95, 'max': 0.99, 'mean': 0.948} · wrong {'n': 20, 'min': 0.8, 'p25': 0.95, 'median': 0.95, 'max': 0.95, 'mean': 0.925} · P(conf right > conf wrong) = 0.676 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 0/20, right 3/80; t=0.85: wrong 3/20, right 3/80; t=0.9: wrong 3/20, right 3/80; t=0.95: wrong 4/20, right 7/80; t=0.99: wrong 20/20, right 56/80
  * right/n per bucket: [0, 0.8): 3/3; [0.8, 0.9): 0/3; [0.9, 0.95): 4/5; [0.95, 0.99): 49/65; [0.99, 1.0]: 24/24

**Confidence analysis — combined score after rule penalties (what the demotion floor actually sees); 100 rows**

* *action wrong*: right {'n': 91, 'min': 0.6, 'p25': 0.95, 'median': 0.95, 'max': 0.99, 'mean': 0.944} · wrong {'n': 9, 'min': 0.75, 'p25': 0.8, 'median': 0.85, 'max': 0.95, 'mean': 0.861} · P(conf right > conf wrong) = 0.827 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 1/9, right 3/91; t=0.85: wrong 3/9, right 4/91; t=0.9: wrong 6/9, right 6/91; t=0.95: wrong 6/9, right 11/91; t=0.99: wrong 9/9, right 67/91
  * right/n per bucket: [0, 0.8): 3/4; [0.8, 0.9): 3/8; [0.9, 0.95): 5/5; [0.95, 0.99): 56/59; [0.99, 1.0]: 24/24
* *any dimension wrong*: right {'n': 80, 'min': 0.6, 'p25': 0.95, 'median': 0.95, 'max': 0.99, 'mean': 0.948} · wrong {'n': 20, 'min': 0.75, 'p25': 0.85, 'median': 0.925, 'max': 0.95, 'mean': 0.89} · P(conf right > conf wrong) = 0.783 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 1/20, right 3/80; t=0.85: wrong 4/20, right 3/80; t=0.9: wrong 9/20, right 3/80; t=0.95: wrong 10/20, right 7/80; t=0.99: wrong 20/20, right 56/80
  * right/n per bucket: [0, 0.8): 3/4; [0.8, 0.9): 0/8; [0.9, 0.95): 4/5; [0.95, 0.99): 49/59; [0.99, 1.0]: 24/24

### original / llm-120b-groq: breakdowns

| Slice | n | issue_type | customer_goal | action lenient | tasks created | false triggers |
| --- | --- | --- | --- | --- | --- | --- |
| ambiguous | 16 | 15/16 (93.8%) | 16/16 (100.0%) | 16/16 (100.0%) | 0 | 0 |
| duplicate | 8 | 8/8 (100.0%) | 7/8 (87.5%) | 7/8 (87.5%) | 7 | 0 |
| missing | 16 | 15/16 (93.8%) | 13/16 (81.2%) | 15/16 (93.8%) | 0 | 0 |
| needed | 28 | 27/28 (96.4%) | 27/28 (96.4%) | 23/28 (82.1%) | 23 | 0 |
| not_needed | 24 | 23/24 (95.8%) | 22/24 (91.7%) | 23/24 (95.8%) | 0 | 0 |
| similar_order | 8 | 8/8 (100.0%) | 8/8 (100.0%) | 8/8 (100.0%) | 0 | 0 |

| Language | n | issue_type | customer_goal | action lenient | false triggers |
| --- | --- | --- | --- | --- | --- |
| en | 20 | 19/20 (95.0%) | 19/20 (95.0%) | 19/20 (95.0%) | 0 |
| zh-Hant | 20 | 17/20 (85.0%) | 19/20 (95.0%) | 19/20 (95.0%) | 0 |
| es | 20 | 20/20 (100.0%) | 19/20 (95.0%) | 19/20 (95.0%) | 0 |
| de | 20 | 20/20 (100.0%) | 18/20 (90.0%) | 17/20 (85.0%) | 0 |
| ja | 20 | 20/20 (100.0%) | 18/20 (90.0%) | 18/20 (90.0%) | 0 |

Confusion (label → system action): CLARIFY_WITH_CUSTOMER -> CLARIFY_WITH_CUSTOMER: 25; CLARIFY_WITH_CUSTOMER -> HUMAN_REVIEW: 2; CREATE_SUPPLIER_TASK -> CLARIFY_WITH_CUSTOMER: 5; CREATE_SUPPLIER_TASK -> CREATE_SUPPLIER_TASK: 30; CREATE_SUPPLIER_TASK -> HUMAN_REVIEW: 1; DIRECT_WORKFLOW -> DIRECT_WORKFLOW: 11; DIRECT_WORKFLOW -> HUMAN_REVIEW: 1; HUMAN_REVIEW -> HUMAN_REVIEW: 25


**False triggers (supplier task created, label says no task) (0)**

none

**Missed triggers (label says task, none created) (6)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| D04 | de | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | DEFECT/REPAIR/mixed → CLARIFY_WITH_CUSTOMER | 0.99 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| D05 | ja | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.99 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| D07 | de | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | DEFECT/REPAIR/mixed → CLARIFY_WITH_CUSTOMER | 0.99 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| D08 | es | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.97 | gate 1 (intent_rules): R7 issue DEFECT but no requested outcome: ask what the customer wants. |
| P01 | en | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | DEFECT/BUY_PART → HUMAN_REVIEW | 0.89 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.89 < 0.9: demoted; a human confirms or rejects the proposal. |
| P05 | ja | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | PART_NEED/BUY_PART/mixed → CLARIFY_WITH_CUSTOMER | 0.96 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |

**Should have gone to a human / clarification but was automated (0)**

none

**Other required_action errors (outside acceptable_actions) (2)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| D18 | de | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | DEFECT/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. |
| P10 | zh-Hant | PART_NEED/BUY_PART → DIRECT_WORKFLOW | DEFECT/BUY_PART → HUMAN_REVIEW | 0.89 | gate 3 (supplier_necessary): BP-BUCKLE-25 (25 mm buckle) compatible and 30 in stock: ship it. -> demoted (confidence 0.89 < 0.9) |

**Dimension misclassifications (issue_type or customer_goal ≠ label; route may still be right) (11)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| D05 | ja | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.99 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| D08 | es | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.97 | gate 1 (intent_rules): R7 issue DEFECT but no requested outcome: ask what the customer wants. |
| D12 | de | DEFECT/UNCLEAR → HUMAN_REVIEW | DEFECT/INFORMATION → HUMAN_REVIEW | 0.93 | gate 1 (intent_rules): R2 possible safety issue (fire/smoke/sparks/shock/gas/injury): always a human first. |
| D15 | en | DEFECT/UNCLEAR → HUMAN_REVIEW | DEFECT/INFORMATION → HUMAN_REVIEW | 0.97 | gate 1 (intent_rules): R2 possible safety issue (fire/smoke/sparks/shock/gas/injury): always a human first. |
| D17 | zh-Hant | DEFECT/REPAIR → CLARIFY_WITH_CUSTOMER | DEFECT/EXCHANGE → CLARIFY_WITH_CUSTOMER | 0.89 | gate 2 (matches_order): No order number in the message and no linked order: ask for it. |
| D18 | de | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | DEFECT/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. |
| D19 | ja | DEFECT/REPAIR → CLARIFY_WITH_CUSTOMER | DEFECT/EXCHANGE → CLARIFY_WITH_CUSTOMER | 0.89 | gate 2 (matches_order): No order number in the message and no linked order: ask for it. |
| D21 | zh-Hant | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | UNCLEAR/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.95 | gate 1 (intent_rules): R7 issue UNCLEAR but no requested outcome: ask what the customer wants. |
| P01 | en | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | DEFECT/BUY_PART → HUMAN_REVIEW | 0.89 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.89 < 0.9: demoted; a human confirms or rejects the proposal. |
| P10 | zh-Hant | PART_NEED/BUY_PART → DIRECT_WORKFLOW | DEFECT/BUY_PART → HUMAN_REVIEW | 0.89 | gate 3 (supplier_necessary): BP-BUCKLE-25 (25 mm buckle) compatible and 30 in stock: ship it. -> demoted (confidence 0.89 < 0.9) |
| P17 | zh-Hant | PART_NEED/BUY_PART → CLARIFY_WITH_CUSTOMER | DEFECT/BUY_PART → CLARIFY_WITH_CUSTOMER | 0.98 | gate 2 (matches_order): No part number in the message: ask for it (part models are never guessed). |

**Confidence analysis — LLM self-report; 100 rows**

* *action wrong*: right {'n': 92, 'min': 0.9, 'p25': 0.99, 'median': 0.99, 'max': 0.99, 'mean': 0.985} · wrong {'n': 8, 'min': 0.95, 'p25': 0.97, 'median': 0.99, 'max': 0.99, 'mean': 0.979} · P(conf right > conf wrong) = 0.611 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 0/8, right 0/92; t=0.85: wrong 0/8, right 0/92; t=0.9: wrong 0/8, right 0/92; t=0.95: wrong 0/8, right 2/92; t=0.99: wrong 3/8, right 16/92
  * right/n per bucket: [0, 0.8): 0/0; [0.8, 0.9): 0/0; [0.9, 0.95): 2/2; [0.95, 0.99): 14/17; [0.99, 1.0]: 76/81
* *any dimension wrong*: right {'n': 86, 'min': 0.9, 'p25': 0.99, 'median': 0.99, 'max': 0.99, 'mean': 0.986} · wrong {'n': 14, 'min': 0.93, 'p25': 0.96, 'median': 0.985, 'max': 0.99, 'mean': 0.974} · P(conf right > conf wrong) = 0.69 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 0/14, right 0/86; t=0.85: wrong 0/14, right 0/86; t=0.9: wrong 0/14, right 0/86; t=0.95: wrong 1/14, right 1/86; t=0.99: wrong 7/14, right 12/86
  * right/n per bucket: [0, 0.8): 0/0; [0.8, 0.9): 0/0; [0.9, 0.95): 1/2; [0.95, 0.99): 11/17; [0.99, 1.0]: 74/81

**Confidence analysis — combined score after rule penalties (what the demotion floor actually sees); 100 rows**

* *action wrong*: right {'n': 92, 'min': 0.74, 'p25': 0.99, 'median': 0.99, 'max': 0.99, 'mean': 0.98} · wrong {'n': 8, 'min': 0.89, 'p25': 0.95, 'median': 0.965, 'max': 0.99, 'mean': 0.954} · P(conf right > conf wrong) = 0.734 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 0/8, right 1/92; t=0.85: wrong 0/8, right 1/92; t=0.9: wrong 2/8, right 3/92; t=0.95: wrong 2/8, right 5/92; t=0.99: wrong 5/8, right 19/92
  * right/n per bucket: [0, 0.8): 1/1; [0.8, 0.9): 2/4; [0.9, 0.95): 2/2; [0.95, 0.99): 14/17; [0.99, 1.0]: 73/76
* *any dimension wrong*: right {'n': 86, 'min': 0.74, 'p25': 0.99, 'median': 0.99, 'max': 0.99, 'mean': 0.983} · wrong {'n': 14, 'min': 0.89, 'p25': 0.89, 'median': 0.955, 'max': 0.99, 'mean': 0.946} · P(conf right > conf wrong) = 0.842 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 0/14, right 1/86; t=0.85: wrong 0/14, right 1/86; t=0.9: wrong 4/14, right 1/86; t=0.95: wrong 5/14, right 2/86; t=0.99: wrong 11/14, right 13/86
  * right/n per bucket: [0, 0.8): 1/1; [0.8, 0.9): 0/4; [0.9, 0.95): 1/2; [0.95, 0.99): 11/17; [0.99, 1.0]: 73/76

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

* **llm-20b-nvidia** run 2026-10-09T11:43:23+00:00 UTC · provider NVIDIA · model `openai/gpt-oss-20b` · extractor `llm:openai/gpt-oss-20b` · 429 retries 0 · network retries 1 · LLM fallbacks 0 · keys with >1 open task 0
* **llm-120b-groq** run 2026-10-09T10:03:04+00:00 UTC · provider Groq · model `openai/gpt-oss-120b` · extractor `llm:openai/gpt-oss-120b` · 429 retries 0 · network retries 0 · LLM fallbacks 0 · keys with >1 open task 0
* **keyword** run 2026-10-09T09:25:53+00:00 UTC · provider — · model `—` · extractor `keyword-fallback` · 429 retries 0 · network retries 0 · LLM fallbacks 0 · keys with >1 open task 0

| Metric | llm-20b-nvidia | llm-120b-groq | keyword |
| --- | --- | --- | --- |
| issue_type accuracy (after text checks) | 48/60 (80.0%) [95% CI 68.2–88.2%] | 48/60 (80.0%) [95% CI 68.2–88.2%] | 42/60 (70.0%) [95% CI 57.5–80.1%] |
| issue_type accuracy (raw AI output) | 49/60 (81.7%) | 49/60 (81.7%) | 42/60 (70.0%) |
| customer_goal accuracy (after text checks) | 45/60 (75.0%) [95% CI 62.8–84.2%] | 49/60 (81.7%) [95% CI 70.1–89.4%] | 42/60 (70.0%) [95% CI 57.5–80.1%] |
| customer_goal accuracy (raw AI output) | 43/60 (71.7%) | 49/60 (81.7%) | 42/60 (70.0%) |
| mixed flag accuracy | 51/60 (85.0%) | 52/60 (86.7%) | 51/60 (85.0%) |
| required_action strict | 47/60 (78.3%) [95% CI 66.4–86.9%] | 50/60 (83.3%) [95% CI 72.0–90.7%] | 30/60 (50.0%) [95% CI 37.7–62.3%] |
| required_action lenient (acceptable_actions) | 48/60 (80.0%) [95% CI 68.2–88.2%] | 51/60 (85.0%) [95% CI 73.9–91.9%] | 35/60 (58.3%) [95% CI 45.7–69.9%] |
| all three dimensions right (strict) | 31/60 (51.7%) | 35/60 (58.3%) | 20/60 (33.3%) |
| supplier-task precision | 3/4 (75.0%) [95% CI 30.1–95.4%] | 3/4 (75.0%) [95% CI 30.1–95.4%] | n/a (0/0) |
| supplier-task recall (automatic) | 3/3 (100.0%) [95% CI 43.8–100%] | 3/3 (100.0%) [95% CI 43.8–100%] | 0/3 (0.0%) [95% CI 0–56.2%] |
| supplier-task recall incl. human-confirm proposal | 3/3 (100.0%) | 3/3 (100.0%) | 3/3 (100.0%) |
| false trigger on non-task cases | 1/57 (1.8%) [95% CI 0.3–9.3%] | 1/57 (1.8%) [95% CI 0.3–9.3%] | 0/57 (0.0%) [95% CI 0–6.3%] |
| should be human/clarify but automated | 1/44 (2.3%) [95% CI 0.4–11.8%] | 2/44 (4.5%) [95% CI 1.3–15.1%] | 0/44 (0.0%) [95% CI 0.0–8.0%] |
| duplicate rows that created a new task | n/a (0/0) | n/a (0/0) | n/a (0/0) |
| task draft completeness | 4/4 (100.0%) | 4/4 (100.0%) | n/a (0/0) |
| automatic actions demoted by confidence | 4/60 (6.7%) | 1/60 (1.7%) | 18/60 (30.0%) |
| latency p50 per case (ms) | 15712.0 | 1548.25 | 13.55 |

### heldout / llm-20b-nvidia: breakdowns

| Slice | n | issue_type | customer_goal | action lenient | tasks created | false triggers |
| --- | --- | --- | --- | --- | --- | --- |
| clear_request | 8 | 7/8 (87.5%) | 7/8 (87.5%) | 7/8 (87.5%) | 3 | 0 |
| inquiry_about_problem | 5 | 3/5 (60.0%) | 4/5 (80.0%) | 3/5 (60.0%) | 0 | 0 |
| insufficient_info | 9 | 9/9 (100.0%) | 7/9 (77.8%) | 9/9 (100.0%) | 0 | 0 |
| mixed | 9 | 6/9 (66.7%) | 6/9 (66.7%) | 5/9 (55.6%) | 0 | 0 |
| mixed_safety | 1 | 1/1 (100.0%) | 0/1 (0.0%) | 1/1 (100.0%) | 0 | 0 |
| negation | 6 | 5/6 (83.3%) | 4/6 (66.7%) | 6/6 (100.0%) | 0 | 0 |
| part_inquiry | 8 | 4/8 (50.0%) | 3/8 (37.5%) | 5/8 (62.5%) | 1 | 1 |
| pre_purchase | 3 | 3/3 (100.0%) | 3/3 (100.0%) | 3/3 (100.0%) | 0 | 0 |
| refund_only | 11 | 10/11 (90.9%) | 11/11 (100.0%) | 9/11 (81.8%) | 0 | 0 |

| Language | n | issue_type | customer_goal | action lenient | false triggers |
| --- | --- | --- | --- | --- | --- |
| en | 20 | 15/20 (75.0%) | 16/20 (80.0%) | 17/20 (85.0%) | 0 |
| zh-Hant | 8 | 8/8 (100.0%) | 5/8 (62.5%) | 6/8 (75.0%) | 0 |
| es | 11 | 9/11 (81.8%) | 11/11 (100.0%) | 7/11 (63.6%) | 0 |
| de | 11 | 10/11 (90.9%) | 6/11 (54.5%) | 8/11 (72.7%) | 1 |
| ja | 10 | 6/10 (60.0%) | 7/10 (70.0%) | 10/10 (100.0%) | 0 |

Confusion (label → system action): CLARIFY_WITH_CUSTOMER -> CLARIFY_WITH_CUSTOMER: 14; CLARIFY_WITH_CUSTOMER -> HUMAN_REVIEW: 5; CREATE_SUPPLIER_TASK -> CREATE_SUPPLIER_TASK: 3; DIRECT_WORKFLOW -> CLARIFY_WITH_CUSTOMER: 1; DIRECT_WORKFLOW -> DIRECT_WORKFLOW: 10; DIRECT_WORKFLOW -> HUMAN_REVIEW: 2; HUMAN_REVIEW -> CLARIFY_WITH_CUSTOMER: 4; HUMAN_REVIEW -> CREATE_SUPPLIER_TASK: 1; HUMAN_REVIEW -> HUMAN_REVIEW: 20


**False triggers (supplier task created, label says no task) (1)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| H13 | de | PART_NEED/INFORMATION → HUMAN_REVIEW | DEFECT/BUY_PART → CREATE_SUPPLIER_TASK | 0.95 | gates 1-4 passed: KL-170-LID (Lid assembly) compatible but 0 in stock; Kettleworks Ltd. (MOCK supplier) supplies parts: confirm availability and lead time. |

**Missed triggers (label says task, none created) (0)**

none

**Should have gone to a human / clarification but was automated (1)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| H13 | de | PART_NEED/INFORMATION → HUMAN_REVIEW | DEFECT/BUY_PART → CREATE_SUPPLIER_TASK | 0.95 | gates 1-4 passed: KL-170-LID (Lid assembly) compatible but 0 in stock; Kettleworks Ltd. (MOCK supplier) supplies parts: confirm availability and lead time. |

**Other required_action errors (outside acceptable_actions) (11)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| H08 | zh-Hant | SIZE_MISMATCH/INFORMATION → HUMAN_REVIEW | SIZE_MISMATCH/EXCHANGE/mixed → CLARIFY_WITH_CUSTOMER | 0.85 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H12 | en | DEFECT/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/INFORMATION/mixed → CLARIFY_WITH_CUSTOMER | 0.95 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H14 | es | PART_NEED/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/INFORMATION/mixed → CLARIFY_WITH_CUSTOMER | 0.85 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H19 | de | DEFECT/REFUND → DIRECT_WORKFLOW | DEFECT/REFUND → HUMAN_REVIEW | 0.6 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.6 < 0.9) |
| H20 | es | UNCLEAR/REFUND → DIRECT_WORKFLOW | UNCLEAR/REFUND → HUMAN_REVIEW | 0.85 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.85 < 0.9) |
| H27 | en | SIZE_MISMATCH/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | SIZE_MISMATCH/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue SIZE_MISMATCH): a question, not a request to act; support answers it. No supplier task. |
| H28 | en | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. |
| H30 | zh-Hant | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. |
| H32 | es | DEFECT/REFUND/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/REFUND → HUMAN_REVIEW | 0.7 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.7 < 0.9) |
| H48 | es | DEFECT/REPAIR → DIRECT_WORKFLOW | DEFECT/REPAIR/mixed → CLARIFY_WITH_CUSTOMER | 0.95 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H53 | de | PART_NEED/INFORMATION → HUMAN_REVIEW | PART_NEED/BUY_PART → CLARIFY_WITH_CUSTOMER | 0.95 | gate 2 (matches_order): No order number in the message and no linked order: ask for it. |

**Dimension misclassifications (issue_type or customer_goal ≠ label; route may still be right) (25)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| H01 | en | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/EXCHANGE → HUMAN_REVIEW | 0.9 | gate 1 (intent_rules): R8 the text is question-form / negates a problem but the AI goal is EXCHANGE: a human answers (no automatic action on a question). |
| H05 | ja | DEFECT/INFORMATION → HUMAN_REVIEW | DEFECT/REPAIR → HUMAN_REVIEW | 0.9 | gate 1 (intent_rules): R8 the text is question-form but the AI goal is REPAIR: a human answers (no automatic action on a question). |
| H06 | en | UNCLEAR/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | 0.85 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue NO_ISSUE_INQUIRY): a question, not a request to act; support answers it. No supplier task. |
| H07 | en | PART_NEED/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/BUY_PART → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R8 the text is question-form but the AI goal is BUY_PART: a human answers (no automatic action on a question). |
| H08 | zh-Hant | SIZE_MISMATCH/INFORMATION → HUMAN_REVIEW | SIZE_MISMATCH/EXCHANGE/mixed → CLARIFY_WITH_CUSTOMER | 0.85 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H10 | de | DEFECT/INFORMATION → HUMAN_REVIEW | DEFECT/BUY_PART → HUMAN_REVIEW | 0.7 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.7 < 0.9: demoted; a human confirms or rejects the proposal. |
| H12 | en | DEFECT/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/INFORMATION/mixed → CLARIFY_WITH_CUSTOMER | 0.95 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H13 | de | PART_NEED/INFORMATION → HUMAN_REVIEW | DEFECT/BUY_PART → CREATE_SUPPLIER_TASK | 0.95 | gates 1-4 passed: KL-170-LID (Lid assembly) compatible but 0 in stock; Kettleworks Ltd. (MOCK supplier) supplies parts: confirm availability and lead time. |
| H14 | es | PART_NEED/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/INFORMATION/mixed → CLARIFY_WITH_CUSTOMER | 0.85 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H15 | ja | PART_NEED/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue NO_ISSUE_INQUIRY): a question, not a request to act; support answers it. No supplier task. |
| H26 | en | UNCLEAR/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | MISSING_ITEM/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.9 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H27 | en | SIZE_MISMATCH/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | SIZE_MISMATCH/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue SIZE_MISMATCH): a question, not a request to act; support answers it. No supplier task. |
| H28 | en | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. |
| H30 | zh-Hant | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. |
| H31 | es | UNCLEAR/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.9 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H34 | de | DEFECT/UNCLEAR/mixed → HUMAN_REVIEW | DEFECT/INFORMATION → HUMAN_REVIEW | 0.85 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. |
| H35 | ja | UNCLEAR/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.95 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H41 | de | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | DEFECT/INFORMATION → HUMAN_REVIEW | 0.8 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. |
| H44 | ja | MISSING_ITEM/UNCLEAR → CLARIFY_WITH_CUSTOMER | MISSING_ITEM/RESHIP → CLARIFY_WITH_CUSTOMER | 0.95 | gate 2 (matches_order): Order TO-703031 not found (no fuzzy matching): ask the customer to confirm it. |
| H45 | en | UNCLEAR/REFUND → DIRECT_WORKFLOW | NO_ISSUE_INQUIRY/REFUND → DIRECT_WORKFLOW | 0.95 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. |
| H47 | zh-Hant | MISSING_ITEM/INFORMATION → HUMAN_REVIEW | MISSING_ITEM/RESHIP → HUMAN_REVIEW | 0.95 | gate 3 (supplier_necessary): Carrier shows the item delivered in full; the claim conflicts with our data. A human investigates before anyone reships. |
| H50 | ja | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | DEFECT/BUY_PART → CREATE_SUPPLIER_TASK | 0.95 | gates 1-4 passed: KL-170-LID (Lid assembly) compatible but 0 in stock; Kettleworks Ltd. (MOCK supplier) supplies parts: confirm availability and lead time. |
| H53 | de | PART_NEED/INFORMATION → HUMAN_REVIEW | PART_NEED/BUY_PART → CLARIFY_WITH_CUSTOMER | 0.95 | gate 2 (matches_order): No order number in the message and no linked order: ask for it. |
| H54 | ja | PART_NEED/INFORMATION → HUMAN_REVIEW | PART_NEED/BUY_PART → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R8 the text is question-form but the AI goal is BUY_PART: a human answers (no automatic action on a question). |
| H60 | ja | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | MISSING_ITEM/INFORMATION → HUMAN_REVIEW | 0.8 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue MISSING_ITEM): a question, not a request to act; support answers it. No supplier task. |

**Confidence analysis — LLM self-report; 60 rows**

* *action wrong*: right {'n': 48, 'min': 0.8, 'p25': 0.95, 'median': 0.95, 'max': 0.99, 'mean': 0.938} · wrong {'n': 12, 'min': 0.85, 'p25': 0.95, 'median': 0.95, 'max': 0.95, 'mean': 0.942} · P(conf right > conf wrong) = 0.489 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 0/12, right 0/48; t=0.85: wrong 0/12, right 2/48; t=0.9: wrong 1/12, right 4/48; t=0.95: wrong 1/12, right 9/48; t=0.99: wrong 12/12, right 44/48
  * right/n per bucket: [0, 0.8): 0/0; [0.8, 0.9): 4/5; [0.9, 0.95): 5/5; [0.95, 0.99): 35/46; [0.99, 1.0]: 4/4
* *any dimension wrong*: right {'n': 31, 'min': 0.8, 'p25': 0.95, 'median': 0.95, 'max': 0.99, 'mean': 0.944} · wrong {'n': 29, 'min': 0.8, 'p25': 0.95, 'median': 0.95, 'max': 0.95, 'mean': 0.933} · P(conf right > conf wrong) = 0.613 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 0/29, right 0/31; t=0.85: wrong 1/29, right 1/31; t=0.9: wrong 2/29, right 3/31; t=0.95: wrong 7/29, right 3/31; t=0.99: wrong 29/29, right 27/31
  * right/n per bucket: [0, 0.8): 0/0; [0.8, 0.9): 3/5; [0.9, 0.95): 0/5; [0.95, 0.99): 24/46; [0.99, 1.0]: 4/4

**Confidence analysis — combined score after rule penalties (what the demotion floor actually sees); 60 rows**

* *action wrong*: right {'n': 48, 'min': 0.7, 'p25': 0.95, 'median': 0.95, 'max': 0.99, 'mean': 0.926} · wrong {'n': 12, 'min': 0.6, 'p25': 0.85, 'median': 0.95, 'max': 0.95, 'mean': 0.875} · P(conf right > conf wrong) = 0.628 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 2/12, right 1/48; t=0.85: wrong 2/12, right 4/48; t=0.9: wrong 5/12, right 8/48; t=0.95: wrong 5/12, right 12/48; t=0.99: wrong 12/12, right 44/48
  * right/n per bucket: [0, 0.8): 1/3; [0.8, 0.9): 7/10; [0.9, 0.95): 4/4; [0.95, 0.99): 32/39; [0.99, 1.0]: 4/4
* *any dimension wrong*: right {'n': 31, 'min': 0.8, 'p25': 0.95, 'median': 0.95, 'max': 0.99, 'mean': 0.944} · wrong {'n': 29, 'min': 0.6, 'p25': 0.85, 'median': 0.95, 'max': 0.95, 'mean': 0.886} · P(conf right > conf wrong) = 0.724 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 3/29, right 0/31; t=0.85: wrong 5/29, right 1/31; t=0.9: wrong 10/29, right 3/31; t=0.95: wrong 14/29, right 3/31; t=0.99: wrong 29/29, right 27/31
  * right/n per bucket: [0, 0.8): 0/3; [0.8, 0.9): 3/10; [0.9, 0.95): 0/4; [0.95, 0.99): 24/39; [0.99, 1.0]: 4/4

### heldout / llm-120b-groq: breakdowns

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

**Confidence analysis — LLM self-report; 60 rows**

* *action wrong*: right {'n': 51, 'min': 0.9, 'p25': 0.97, 'median': 0.99, 'max': 0.99, 'mean': 0.977} · wrong {'n': 9, 'min': 0.93, 'p25': 0.96, 'median': 0.97, 'max': 0.99, 'mean': 0.969} · P(conf right > conf wrong) = 0.687 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 0/9, right 0/51; t=0.85: wrong 0/9, right 0/51; t=0.9: wrong 0/9, right 0/51; t=0.95: wrong 1/9, right 7/51; t=0.99: wrong 7/9, right 20/51
  * right/n per bucket: [0, 0.8): 0/0; [0.8, 0.9): 0/0; [0.9, 0.95): 7/8; [0.95, 0.99): 13/19; [0.99, 1.0]: 31/33
* *any dimension wrong*: right {'n': 35, 'min': 0.9, 'p25': 0.98, 'median': 0.99, 'max': 0.99, 'mean': 0.981} · wrong {'n': 25, 'min': 0.93, 'p25': 0.96, 'median': 0.97, 'max': 0.99, 'mean': 0.968} · P(conf right > conf wrong) = 0.69 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 0/25, right 0/35; t=0.85: wrong 0/25, right 0/35; t=0.9: wrong 0/25, right 0/35; t=0.95: wrong 6/25, right 2/35; t=0.99: wrong 16/25, right 11/35
  * right/n per bucket: [0, 0.8): 0/0; [0.8, 0.9): 0/0; [0.9, 0.95): 2/8; [0.95, 0.99): 9/19; [0.99, 1.0]: 24/33

**Confidence analysis — combined score after rule penalties (what the demotion floor actually sees); 60 rows**

* *action wrong*: right {'n': 51, 'min': 0.73, 'p25': 0.97, 'median': 0.99, 'max': 0.99, 'mean': 0.962} · wrong {'n': 9, 'min': 0.64, 'p25': 0.93, 'median': 0.96, 'max': 0.99, 'mean': 0.919} · P(conf right > conf wrong) = 0.752 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 1/9, right 1/51; t=0.85: wrong 1/9, right 4/51; t=0.9: wrong 2/9, right 6/51; t=0.95: wrong 3/9, right 10/51; t=0.99: wrong 8/9, right 21/51
  * right/n per bucket: [0, 0.8): 1/2; [0.8, 0.9): 5/6; [0.9, 0.95): 4/5; [0.95, 0.99): 11/16; [0.99, 1.0]: 30/31
* *any dimension wrong*: right {'n': 35, 'min': 0.73, 'p25': 0.98, 'median': 0.99, 'max': 0.99, 'mean': 0.974} · wrong {'n': 25, 'min': 0.64, 'p25': 0.89, 'median': 0.96, 'max': 0.99, 'mean': 0.93} · P(conf right > conf wrong) = 0.746 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 1/25, right 1/35; t=0.85: wrong 4/25, right 1/35; t=0.9: wrong 7/25, right 1/35; t=0.95: wrong 10/25, right 3/35; t=0.99: wrong 18/25, right 11/35
  * right/n per bucket: [0, 0.8): 1/2; [0.8, 0.9): 0/6; [0.9, 0.95): 2/5; [0.95, 0.99): 8/16; [0.99, 1.0]: 24/31

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

## Reading these numbers

* **Two sets, two purposes.**
  - The original 100 is a regression set of known scenarios. The author wrote it together with the rules, so a high score shows consistency, not field accuracy.
  - The held-out 60 is the unseen set. A different model family (`qwen/qwen3.8-27b`) generated it from a prompt that contained no rules. The author labelled it before any run (commit d5752f0). Its labels are still **pending human review** (`heldout-review.csv`).
* **Which extractor model / provider.**
  - Production extractor: `openai/gpt-oss-20b` on **Groq**.
  - `llm-20b-nvidia` runs: the **production model** `openai/gpt-oss-20b`, but served by **NVIDIA** (`integrate.api.nvidia.com`, eval-only key, never used by the app or Render). The model is the same; the **provider differs from production**, so serving stack, quantisation and decoding defaults may differ. Treat these as production-model numbers, not as a replay of production.
  - `llm-120b-groq` runs: `openai/gpt-oss-120b` on Groq (same family, prompt and schema). This was used earlier because the Groq free-tier daily cap for 20b (200k tokens/day) had been used up. It is **not** the production model; kept for comparison. Side by side: [routing-model-comparison.md](routing-model-comparison.md).
  - Groq quota was deliberately not used for the 20b runs, so it stays available for the live app.
* **NVIDIA connection instability.** Both first 20b attempts were stopped by the abort-on-fallback guard after the server dropped the connection (`httpx.RemoteProtocolError`): original at R14 (38/100 done), held-out at H58 (57/60 done, kept as `routing-results-heldout-20b-attempt1-partial.{json,md}`). Scoring a keyword fallback as "llm" was refused, as intended. The transport then got a counted network retry (same request, same model, max 3, never a fallback), and both sets were **re-run from scratch** (not resumed, so duplicate detection sees the full sequence). Final runs: original 100/100 with 0 network retries; held-out 60/60 with 1 network retry; 0 fallbacks, 0 rate-limit 429s. Latency p50 ≈ 14–16 s per case on NVIDIA's free endpoint (two runs in parallel, 2 s delay), vs ≈ 1.3–1.5 s for 120b on Groq. NVIDIA latency says nothing about Groq production latency.
* **Run-to-run variance.** The partial held-out attempt 1 and the full run 2 of 20b chose a different action on 7 of the 57 rows they share (H12, H14, H31, H32, H41, H45, H48). Attempt 1 had 46/57 lenient correct; run 2 has 48/60. The same model, prompt and rules are not deterministic, so single-run numbers carry noise on top of the sampling CI. Only run 2 (complete) is reported as the result.
* **Was the held-out set used for tuning? No.**
  - The 0.2.0 rules were committed (a4ffee8) before any held-out run.
  - Nothing in the rules, prompt or keyword lists changed after the held-out results were seen. The held-out numbers here are the pre-change numbers (snapshot `routing-results-heldout-prechange.json`).
  - Caveat: the author read the 60 messages while labelling them, before writing the 0.2.0 rules. The rules follow the user's design, not specific messages, but this is a contamination risk. The next round needs a fresh held-out set no matter what.
  - Any rule change made in response to these errors (see "Remaining weaknesses" in the roadmap) turns this set into "used for tuning".
* **Small samples.** 60 cases is preliminary evidence, not proof:
  - A 51/60 action accuracy has a Wilson 95% interval of roughly 74–92%.
  - Even 60/60 would only bound the true rate at roughly ≥ 94%.
  - The held-out set has only 3 labelled supplier-task cases, so precision and recall of task creation are essentially unmeasured on unseen data.
  - The intervals are printed next to the key rates.
* **Confidence.** The self-report is uncalibrated, and it is used only to demote. The confidence analysis shows whether it separates right from wrong on these rows. Because the floor (0.90) sits below almost all self-reports, it almost never fires on the LLM path.
* **Keyword fallback.** Its confidence is capped at 0.85, below the 0.90 floor, so it can never perform an automatic action. Its action accuracy is low by design: it sends cases to people; it does not route them.
* **Label errata**: [heldout-label-errata.md](heldout-label-errata.md). Labels are never edited; the metrics use the frozen labels.
* **Duplicate metric, original LLM run (1/8).** The 1/8 is P08. Its twin P01 was *demoted* by confidence: the combined score was 0.89, because the keyword scan disagreed with the AI's DEFECT issue. P01 therefore never opened a task. When P08 arrived there was no open task to link to, so a first task was created, which is correct. The DB still holds 0 keys with more than one open task.
* **"Repair or replace" read as mixed.** gpt-oss-120b (and 20b: D04, D05, H48) flagged `mixed_goals` on "repair or replace" / 修理か交換 / reparieren oder ersetzen. This caused 4 of the 6 missed supplier tasks in the original set (D04, D05, D07, P05) and held-out H48. The miss is in the safe direction (it asks the customer). The prompt was deliberately **not** changed after seeing this, because a change would make the held-out set "used for tuning".

