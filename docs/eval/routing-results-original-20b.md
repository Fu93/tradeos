# Supplier routing eval — round 2 (rules `supplier-routing-rules/0.2.0 (MVP 1 experiment, round 2)`)

Two sets, reported **separately** (never pooled). Every rate is `correct/n (%)`; key rates carry a Wilson 95% confidence interval. All operational data is MOCK. Rules and frozen labels are identical for every run.

**Models / providers.** Production extractor is `openai/gpt-oss-20b` on **Groq**. Runs named `llm-120b-groq` used `openai/gpt-oss-120b` on Groq (the Groq free-tier daily token cap for 20b was exhausted on 2026-10-09). Runs named `llm-20b-nvidia` used the production model `openai/gpt-oss-20b` served by **NVIDIA** (integrate.api.nvidia.com, eval-only key): same model weights as production, different provider (serving stack/sampling defaults may differ slightly from Groq). Held-out set NOT used for tuning: rules 0.2.0 unchanged since before any held-out run.

Round-1 history: [routing-results-round1-rules011.md](routing-results-round1-rules011.md), [routing-results-run1.md](routing-results-run1.md).

## Original 100 — regression set of known scenarios (author-written)

* **llm** run 2026-10-09T11:38:35+00:00 UTC · provider NVIDIA · model `openai/gpt-oss-20b` · extractor `llm:openai/gpt-oss-20b` · 429 retries 0 · network retries 0 · LLM fallbacks 0 · keys with >1 open task 0

| Metric | llm |
| --- | --- |
| issue_type accuracy (after text checks) | 88/100 (88.0%) [95% CI 80.2–93.0%] |
| issue_type accuracy (raw AI output) | 88/100 (88.0%) |
| customer_goal accuracy (after text checks) | 90/100 (90.0%) [95% CI 82.6–94.5%] |
| customer_goal accuracy (raw AI output) | 90/100 (90.0%) |
| mixed flag accuracy | 98/100 (98.0%) |
| required_action strict | 90/100 (90.0%) [95% CI 82.6–94.5%] |
| required_action lenient (acceptable_actions) | 91/100 (91.0%) [95% CI 83.8–95.2%] |
| all three dimensions right (strict) | 79/100 (79.0%) |
| supplier-task precision | 29/29 (100.0%) [95% CI 88.3–100%] |
| supplier-task recall (automatic) | 29/36 (80.6%) [95% CI 65.0–90.2%] |
| supplier-task recall incl. human-confirm proposal | 30/36 (83.3%) |
| false trigger on non-task cases | 0/64 (0.0%) [95% CI 0–5.7%] |
| should be human/clarify but automated | 0/52 (0.0%) [95% CI 0–6.9%] |
| duplicate rows that created a new task | 0/8 (0.0%) |
| task draft completeness | 23/23 (100.0%) |
| automatic actions demoted by confidence | 2/100 (2.0%) |
| latency p50 per case (ms) | 13786.35 |

### original / llm: breakdowns

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

## Reading these numbers

* **Two sets, two purposes.**
  - The original 100 is a regression set of known scenarios. The author wrote it together with the rules, so a high score shows consistency, not field accuracy.
  - The held-out 60 is the unseen set. A different model family (`qwen/qwen3.8-27b`) generated it from a prompt that contained no rules. The author labelled it before any run (commit d5752f0). Its labels are still **pending human review** (`heldout-review.csv`).
* **Which extractor model.** The app's default extractor is `openai/gpt-oss-20b`. On 2026-10-09 the Groq free-tier daily cap for that model (200,000 tokens per day) had already been used up by the round-1 runs and an aborted round-2 start. Because of that, both round-2 LLM runs used `openai/gpt-oss-120b`, which is the same family, has a separate quota, and gets the same prompt and schema. **These are therefore not production-model numbers.** The `gpt-oss-20b` held-out run is still to do, with the same frozen labels. A 20b attempt was stopped automatically after 1 row by the daily cap. The script refuses to fall back silently to keywords on a daily-cap 429.
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
* **"Repair or replace" read as mixed.** gpt-oss-120b flagged `mixed_goals` on "repair or replace" / 修理か交換 / reparieren oder ersetzen. This caused 4 of the 6 missed supplier tasks in the original set (D04, D05, D07, P05) and held-out H48. The miss is in the safe direction (it asks the customer). The prompt was deliberately **not** changed after seeing this, because a change would make the held-out set "used for tuning".

