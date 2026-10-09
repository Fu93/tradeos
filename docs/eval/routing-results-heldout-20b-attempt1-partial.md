# Supplier routing eval — round 2 (rules `supplier-routing-rules/0.2.0 (MVP 1 experiment, round 2)`)

Two sets, reported **separately** (never pooled). Every rate is `correct/n (%)`; key rates carry a Wilson 95% confidence interval. Extractor model: `openai/gpt-oss-20b` (Groq). All operational data is MOCK.
**The LLM runs below used `openai/gpt-oss-120b`, NOT the production extractor `openai/gpt-oss-20b` (Groq free-tier daily token cap for 20b was exhausted on 2026-10-09). The 20b held-out run is still to do, with the same frozen labels. Held-out set NOT used for tuning: rules 0.2.0 unchanged since before the run.**
Round-1 history: [routing-results-round1-rules011.md](routing-results-round1-rules011.md), [routing-results-run1.md](routing-results-run1.md).

## Held-out 60 — unseen, blind-generated (qwen/qwen3.8-27b), author-labelled, pending human review

* **llm: PARTIAL RUN** — 57/60 cases, stopped at H58 (Groq free-tier tokens-per-day cap). Metrics below cover only the completed rows.
* **llm** run 2026-10-09T11:16:59+00:00 UTC · extractor `llm:openai/gpt-oss-20b` · 429 retries 0 · LLM fallbacks 0 · keys with >1 open task 0

| Metric | llm |
| --- | --- |
| issue_type accuracy (after text checks) | 46/57 (80.7%) [95% CI 68.7–88.9%] |
| issue_type accuracy (raw AI output) | 47/57 (82.5%) |
| customer_goal accuracy (after text checks) | 42/57 (73.7%) [95% CI 61.0–83.4%] |
| customer_goal accuracy (raw AI output) | 41/57 (71.9%) |
| mixed flag accuracy | 50/57 (87.7%) |
| required_action strict | 46/57 (80.7%) [95% CI 68.7–88.9%] |
| required_action lenient (acceptable_actions) | 46/57 (80.7%) [95% CI 68.7–88.9%] |
| all three dimensions right (strict) | 29/57 (50.9%) |
| supplier-task precision | 3/4 (75.0%) [95% CI 30.1–95.4%] |
| supplier-task recall (automatic) | 3/3 (100.0%) [95% CI 43.8–100%] |
| supplier-task recall incl. human-confirm proposal | 3/3 (100.0%) |
| false trigger on non-task cases | 1/54 (1.9%) [95% CI 0.3–9.8%] |
| should be human/clarify but automated | 2/41 (4.9%) [95% CI 1.3–16.1%] |
| duplicate rows that created a new task | n/a (0/0) |
| task draft completeness | 4/4 (100.0%) |
| automatic actions demoted by confidence | 4/57 (7.0%) |
| latency p50 per case (ms) | 21065.7 |

### heldout / llm: breakdowns

| Slice | n | issue_type | customer_goal | action lenient | tasks created | false triggers |
| --- | --- | --- | --- | --- | --- | --- |
| clear_request | 8 | 6/8 (75.0%) | 7/8 (87.5%) | 8/8 (100.0%) | 3 | 0 |
| inquiry_about_problem | 5 | 2/5 (40.0%) | 4/5 (80.0%) | 4/5 (80.0%) | 0 | 0 |
| insufficient_info | 9 | 9/9 (100.0%) | 8/9 (88.9%) | 9/9 (100.0%) | 0 | 0 |
| mixed | 9 | 6/9 (66.7%) | 5/9 (55.6%) | 4/9 (44.4%) | 0 | 0 |
| mixed_safety | 1 | 1/1 (100.0%) | 0/1 (0.0%) | 1/1 (100.0%) | 0 | 0 |
| negation | 4 | 4/4 (100.0%) | 2/4 (50.0%) | 4/4 (100.0%) | 0 | 0 |
| part_inquiry | 8 | 5/8 (62.5%) | 3/8 (37.5%) | 6/8 (75.0%) | 1 | 1 |
| pre_purchase | 2 | 2/2 (100.0%) | 2/2 (100.0%) | 2/2 (100.0%) | 0 | 0 |
| refund_only | 11 | 11/11 (100.0%) | 11/11 (100.0%) | 8/11 (72.7%) | 0 | 0 |

| Language | n | issue_type | customer_goal | action lenient | false triggers |
| --- | --- | --- | --- | --- | --- |
| en | 20 | 16/20 (80.0%) | 17/20 (85.0%) | 17/20 (85.0%) | 0 |
| zh-Hant | 8 | 8/8 (100.0%) | 5/8 (62.5%) | 6/8 (75.0%) | 0 |
| es | 10 | 8/10 (80.0%) | 8/10 (80.0%) | 7/10 (70.0%) | 0 |
| de | 10 | 9/10 (90.0%) | 6/10 (60.0%) | 7/10 (70.0%) | 1 |
| ja | 9 | 5/9 (55.6%) | 6/9 (66.7%) | 9/9 (100.0%) | 0 |

Confusion (label → system action): CLARIFY_WITH_CUSTOMER -> CLARIFY_WITH_CUSTOMER: 14; CLARIFY_WITH_CUSTOMER -> DIRECT_WORKFLOW: 1; CLARIFY_WITH_CUSTOMER -> HUMAN_REVIEW: 4; CREATE_SUPPLIER_TASK -> CREATE_SUPPLIER_TASK: 3; DIRECT_WORKFLOW -> DIRECT_WORKFLOW: 10; DIRECT_WORKFLOW -> HUMAN_REVIEW: 3; HUMAN_REVIEW -> CLARIFY_WITH_CUSTOMER: 2; HUMAN_REVIEW -> CREATE_SUPPLIER_TASK: 1; HUMAN_REVIEW -> HUMAN_REVIEW: 19


**False triggers (supplier task created, label says no task) (1)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| H13 | de | PART_NEED/INFORMATION → HUMAN_REVIEW | DEFECT/BUY_PART → CREATE_SUPPLIER_TASK | 0.95 | gates 1-4 passed: KL-170-LID (Lid assembly) compatible but 0 in stock; Kettleworks Ltd. (MOCK supplier) supplies parts: confirm availability and lead time. |

**Missed triggers (label says task, none created) (0)**

none

**Should have gone to a human / clarification but was automated (2)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| H13 | de | PART_NEED/INFORMATION → HUMAN_REVIEW | DEFECT/BUY_PART → CREATE_SUPPLIER_TASK | 0.95 | gates 1-4 passed: KL-170-LID (Lid assembly) compatible but 0 in stock; Kettleworks Ltd. (MOCK supplier) supplies parts: confirm availability and lead time. |
| H32 | es | DEFECT/REFUND/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/REFUND → DIRECT_WORKFLOW | 0.95 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. |

**Other required_action errors (outside acceptable_actions) (9)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| H08 | zh-Hant | SIZE_MISMATCH/INFORMATION → HUMAN_REVIEW | SIZE_MISMATCH/EXCHANGE/mixed → CLARIFY_WITH_CUSTOMER | 0.85 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H19 | de | DEFECT/REFUND → DIRECT_WORKFLOW | DEFECT/REFUND → HUMAN_REVIEW | 0.6 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.6 < 0.9) |
| H20 | es | UNCLEAR/REFUND → DIRECT_WORKFLOW | UNCLEAR/REFUND → HUMAN_REVIEW | 0.8 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.8 < 0.9) |
| H27 | en | SIZE_MISMATCH/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | SIZE_MISMATCH/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue SIZE_MISMATCH): a question, not a request to act; support answers it. No supplier task. |
| H28 | en | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. |
| H30 | zh-Hant | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/INFORMATION → HUMAN_REVIEW | 0.9 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. |
| H31 | es | UNCLEAR/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. |
| H45 | en | UNCLEAR/REFUND → DIRECT_WORKFLOW | UNCLEAR/REFUND → HUMAN_REVIEW | 0.8 | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.8 < 0.9) |
| H53 | de | PART_NEED/INFORMATION → HUMAN_REVIEW | PART_NEED/BUY_PART → CLARIFY_WITH_CUSTOMER | 0.95 | gate 2 (matches_order): No order number in the message and no linked order: ask for it. |

**Dimension misclassifications (issue_type or customer_goal ≠ label; route may still be right) (24)**

| id | lang | label issue/goal/action | system issue/goal → action | conf | decided by |
| --- | --- | --- | --- | --- | --- |
| H01 | en | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/EXCHANGE → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R8 the text is question-form / negates a problem but the AI goal is EXCHANGE: a human answers (no automatic action on a question). |
| H05 | ja | DEFECT/INFORMATION → HUMAN_REVIEW | DEFECT/REPAIR → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R8 the text is question-form but the AI goal is REPAIR: a human answers (no automatic action on a question). |
| H06 | en | UNCLEAR/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | 0.85 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue NO_ISSUE_INQUIRY): a question, not a request to act; support answers it. No supplier task. |
| H07 | en | PART_NEED/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue NO_ISSUE_INQUIRY): a question, not a request to act; support answers it. No supplier task. |
| H08 | zh-Hant | SIZE_MISMATCH/INFORMATION → HUMAN_REVIEW | SIZE_MISMATCH/EXCHANGE/mixed → CLARIFY_WITH_CUSTOMER | 0.85 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H10 | de | DEFECT/INFORMATION → HUMAN_REVIEW | DEFECT/BUY_PART → HUMAN_REVIEW | 0.7 | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.7 < 0.9: demoted; a human confirms or rejects the proposal. |
| H11 | ja | SIZE_MISMATCH/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue NO_ISSUE_INQUIRY): a question, not a request to act; support answers it. No supplier task. |
| H12 | en | DEFECT/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue NO_ISSUE_INQUIRY): a question, not a request to act; support answers it. No supplier task. |
| H13 | de | PART_NEED/INFORMATION → HUMAN_REVIEW | DEFECT/BUY_PART → CREATE_SUPPLIER_TASK | 0.95 | gates 1-4 passed: KL-170-LID (Lid assembly) compatible but 0 in stock; Kettleworks Ltd. (MOCK supplier) supplies parts: confirm availability and lead time. |
| H14 | es | PART_NEED/INFORMATION → HUMAN_REVIEW | PART_NEED/BUY_PART → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R8 the text is question-form but the AI goal is BUY_PART: a human answers (no automatic action on a question). |
| H15 | ja | PART_NEED/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue NO_ISSUE_INQUIRY): a question, not a request to act; support answers it. No supplier task. |
| H26 | en | UNCLEAR/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | MISSING_ITEM/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.9 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H27 | en | SIZE_MISMATCH/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | SIZE_MISMATCH/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue SIZE_MISMATCH): a question, not a request to act; support answers it. No supplier task. |
| H28 | en | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. |
| H30 | zh-Hant | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/INFORMATION → HUMAN_REVIEW | 0.9 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. |
| H31 | es | UNCLEAR/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/INFORMATION → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. |
| H34 | de | DEFECT/UNCLEAR/mixed → HUMAN_REVIEW | DEFECT/INFORMATION → HUMAN_REVIEW | 0.85 | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. |
| H35 | ja | UNCLEAR/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | 0.9 | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. |
| H44 | ja | MISSING_ITEM/UNCLEAR → CLARIFY_WITH_CUSTOMER | MISSING_ITEM/RESHIP → CLARIFY_WITH_CUSTOMER | 0.99 | gate 2 (matches_order): Order TO-703031 not found (no fuzzy matching): ask the customer to confirm it. |
| H47 | zh-Hant | MISSING_ITEM/INFORMATION → HUMAN_REVIEW | MISSING_ITEM/RESHIP → HUMAN_REVIEW | 0.95 | gate 3 (supplier_necessary): Carrier shows the item delivered in full; the claim conflicts with our data. A human investigates before anyone reships. |
| H50 | ja | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | DEFECT/BUY_PART → CREATE_SUPPLIER_TASK | 0.95 | gates 1-4 passed: KL-170-LID (Lid assembly) compatible but 0 in stock; Kettleworks Ltd. (MOCK supplier) supplies parts: confirm availability and lead time. |
| H52 | es | PART_NEED/BUY_PART → CLARIFY_WITH_CUSTOMER | DEFECT/BUY_PART → CLARIFY_WITH_CUSTOMER | 0.85 | gate 2 (matches_order): No order number in the message and no linked order: ask for it. |
| H53 | de | PART_NEED/INFORMATION → HUMAN_REVIEW | PART_NEED/BUY_PART → CLARIFY_WITH_CUSTOMER | 0.95 | gate 2 (matches_order): No order number in the message and no linked order: ask for it. |
| H54 | ja | PART_NEED/INFORMATION → HUMAN_REVIEW | PART_NEED/BUY_PART → HUMAN_REVIEW | 0.95 | gate 1 (intent_rules): R8 the text is question-form but the AI goal is BUY_PART: a human answers (no automatic action on a question). |

**Confidence analysis — LLM self-report; 57 rows**

* *action wrong*: right {'n': 46, 'min': 0.75, 'p25': 0.95, 'median': 0.95, 'max': 0.99, 'mean': 0.937} · wrong {'n': 11, 'min': 0.8, 'p25': 0.9, 'median': 0.95, 'max': 0.95, 'mean': 0.918} · P(conf right > conf wrong) = 0.586 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 0/11, right 2/46; t=0.85: wrong 2/11, right 3/46; t=0.9: wrong 2/11, right 3/46; t=0.95: wrong 3/11, right 6/46; t=0.99: wrong 11/11, right 44/46
  * right/n per bucket: [0, 0.8): 2/2; [0.8, 0.9): 1/3; [0.9, 0.95): 3/4; [0.95, 0.99): 38/46; [0.99, 1.0]: 2/2
* *any dimension wrong*: right {'n': 29, 'min': 0.75, 'p25': 0.95, 'median': 0.95, 'max': 0.99, 'mean': 0.931} · wrong {'n': 28, 'min': 0.8, 'p25': 0.95, 'median': 0.95, 'max': 0.99, 'mean': 0.935} · P(conf right > conf wrong) = 0.512 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 0/28, right 2/29; t=0.85: wrong 2/28, right 3/29; t=0.9: wrong 2/28, right 3/29; t=0.95: wrong 5/28, right 4/29; t=0.99: wrong 27/28, right 28/29
  * right/n per bucket: [0, 0.8): 2/2; [0.8, 0.9): 1/3; [0.9, 0.95): 1/4; [0.95, 0.99): 24/46; [0.99, 1.0]: 1/2

**Confidence analysis — combined score after rule penalties (what the demotion floor actually sees); 57 rows**

* *action wrong*: right {'n': 46, 'min': 0.7, 'p25': 0.95, 'median': 0.95, 'max': 0.99, 'mean': 0.925} · wrong {'n': 11, 'min': 0.6, 'p25': 0.8, 'median': 0.95, 'max': 0.95, 'mean': 0.877} · P(conf right > conf wrong) = 0.638 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 1/11, right 3/46; t=0.85: wrong 3/11, right 4/46; t=0.9: wrong 4/11, right 7/46; t=0.95: wrong 5/11, right 10/46; t=0.99: wrong 11/11, right 44/46
  * right/n per bucket: [0, 0.8): 3/4; [0.8, 0.9): 4/7; [0.9, 0.95): 3/4; [0.95, 0.99): 34/40; [0.99, 1.0]: 2/2
* *any dimension wrong*: right {'n': 29, 'min': 0.75, 'p25': 0.95, 'median': 0.95, 'max': 0.99, 'mean': 0.931} · wrong {'n': 28, 'min': 0.6, 'p25': 0.85, 'median': 0.95, 'max': 0.99, 'mean': 0.9} · P(conf right > conf wrong) = 0.616 (0.5 = no separation)
  * below threshold t → demoted: t=0.8: wrong 2/28, right 2/29; t=0.85: wrong 4/28, right 3/29; t=0.9: wrong 8/28, right 3/29; t=0.95: wrong 11/28, right 4/29; t=0.99: wrong 27/28, right 28/29
  * right/n per bucket: [0, 0.8): 2/4; [0.8, 0.9): 1/7; [0.9, 0.95): 1/4; [0.95, 0.99): 24/40; [0.99, 1.0]: 1/2

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

