# Model comparison — 20b (production model, via NVIDIA) vs 120b (via Groq)

Rules `supplier-routing-rules/0.2.0 (MVP 1 experiment, round 2)` and frozen labels identical for every run. Rates are `correct/n (%)`, key rates with a Wilson 95% CI. Sets are reported separately.

* **20b** = `openai/gpt-oss-20b`, the production extractor model, but served by **NVIDIA** (integrate.api.nvidia.com, eval-only key) because the Groq free-tier daily token cap for 20b was used up and Groq quota is kept for the live app. Same model, **different provider** than production (Groq): serving stack / decoding defaults can differ, so this is the production model, not a production replay.
* **120b** = `openai/gpt-oss-120b` via Groq (the earlier round-2 run). Not the production model.
* The held-out set was **not** used for tuning: rules 0.2.0 were committed before any held-out run, and nothing was changed after seeing either model's results.

## Original 100 — regression set of known scenarios (author-written)

| Metric | 20b via NVIDIA (production model) | 120b via Groq | keyword fallback |
| --- | --- | --- | --- |
| issue_type (after text checks) | 88/100 (88.0%) [95% CI 80.2–93.0%] | 96/100 (96.0%) [95% CI 90.2–98.4%] | 73/100 (73.0%) [95% CI 63.6–80.7%] |
| customer_goal (after text checks) | 90/100 (90.0%) [95% CI 82.6–94.5%] | 93/100 (93.0%) [95% CI 86.3–96.6%] | 77/100 (77.0%) [95% CI 67.8–84.2%] |
| mixed flag | 98/100 (98.0%) | 96/100 (96.0%) | 98/100 (98.0%) |
| required_action strict | 90/100 (90.0%) [95% CI 82.6–94.5%] | 91/100 (91.0%) [95% CI 83.8–95.2%] | 46/100 (46.0%) [95% CI 36.6–55.7%] |
| required_action lenient | 91/100 (91.0%) [95% CI 83.8–95.2%] | 92/100 (92.0%) [95% CI 85.0–95.9%] | 49/100 (49.0%) [95% CI 39.4–58.7%] |
| all three dimensions right | 79/100 (79.0%) | 85/100 (85.0%) | 27/100 (27.0%) |
| supplier-task precision | 29/29 (100.0%) [95% CI 88.3–100%] | 30/30 (100.0%) [95% CI 88.6–100%] | n/a (0/0) |
| supplier-task recall (automatic) | 29/36 (80.6%) [95% CI 65.0–90.2%] | 30/36 (83.3%) [95% CI 68.1–92.1%] | 0/36 (0.0%) [95% CI 0–9.6%] |
| false trigger on non-task cases | 0/64 (0.0%) [95% CI 0–5.7%] | 0/64 (0.0%) [95% CI 0–5.7%] | 0/64 (0.0%) [95% CI 0–5.7%] |
| should be human/clarify but automated | 0/52 (0.0%) [95% CI 0–6.9%] | 0/52 (0.0%) [95% CI 0–6.9%] | 0/52 (0.0%) [95% CI 0–6.9%] |
| duplicate rows that created a new task | 0/8 (0.0%) | 1/8 (12.5%) | 0/8 (0.0%) |
| task draft completeness | 23/23 (100.0%) | 24/24 (100.0%) | n/a (0/0) |
| automatic actions demoted by confidence | 2/100 (2.0%) | 2/100 (2.0%) | 33/100 (33.0%) |
| latency p50 per case (ms) | 13786.35 | 1268.5 | 13.5 |

**Every 20b required_action outside acceptable_actions — original**

| id | lang | label issue/goal → action | 20b issue/goal → action | conf | kind | deciding rule (decided_by) | 120b action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D03 | es | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.8 | MISSED TRIGGER | gate 1 (intent_rules): R7 issue DEFECT but no requested outcome: ask what the customer wants. | CREATE_SUPPLIER_TASK |
| D04 | de | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | DEFECT/REPAIR/mixed → CLARIFY_WITH_CUSTOMER | 0.95 | MISSED TRIGGER | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. | CLARIFY_WITH_CUSTOMER |
| D05 | ja | DEFECT/REPAIR → CREATE_SUPPLIER_TASK | DEFECT/REPAIR/mixed → CLARIFY_WITH_CUSTOMER | 0.95 | MISSED TRIGGER | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. | CLARIFY_WITH_CUSTOMER |
| D10 | en | DEFECT/REPAIR → DIRECT_WORKFLOW | DEFECT/UNCLEAR → CLARIFY_WITH_CUSTOMER | 0.8 | wrong manual route | gate 1 (intent_rules): R7 issue DEFECT but no requested outcome: ask what the customer wants. | DIRECT_WORKFLOW |
| P01 | en | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | DEFECT/BUY_PART → HUMAN_REVIEW | 0.85 | MISSED TRIGGER | gate 4 (confidence_and_duplicates): Supplier task proposed, but confidence 0.85 < 0.9: demoted; a human confirms or rejects the proposal. | HUMAN_REVIEW |
| P05 | ja | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | NO_ISSUE_INQUIRY/INFORMATION → HUMAN_REVIEW | 0.95 | MISSED TRIGGER | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue NO_ISSUE_INQUIRY): a question, not a request to act; support answers it. No supplier task. | CLARIFY_WITH_CUSTOMER |
| P08 | ja | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | DEFECT/EXCHANGE → CLARIFY_WITH_CUSTOMER | 0.75 | MISSED TRIGGER | gate 2 (matches_order): No description of the fault: ask. | CREATE_SUPPLIER_TASK |
| P09 | en | PART_NEED/BUY_PART → CREATE_SUPPLIER_TASK | MISSING_ITEM/RESHIP → HUMAN_REVIEW | 0.85 | MISSED TRIGGER | gate 3 (supplier_necessary): Carrier shows the item delivered in full; the claim conflicts with our data. A human investigates before anyone reships. | CREATE_SUPPLIER_TASK |
| P10 | zh-Hant | PART_NEED/BUY_PART → DIRECT_WORKFLOW | DEFECT/BUY_PART → HUMAN_REVIEW | 0.85 | wrong manual route | gate 3 (supplier_necessary): BP-BUCKLE-25 (25 mm buckle) compatible and 30 in stock: ship it. -> demoted (confidence 0.85 < 0.9) | HUMAN_REVIEW |

Cases where the two models chose a different action: 8/100 (D03, D07, D08, D10, D18, P05, P08, P09). Wrong for both models: D04, D05, P01, P05, P10.

## Held-out 60 — unseen, blind-generated (qwen/qwen3.8-27b), author-labelled, pending human review

| Metric | 20b via NVIDIA (production model) | 120b via Groq | keyword fallback |
| --- | --- | --- | --- |
| issue_type (after text checks) | 48/60 (80.0%) [95% CI 68.2–88.2%] | 48/60 (80.0%) [95% CI 68.2–88.2%] | 42/60 (70.0%) [95% CI 57.5–80.1%] |
| customer_goal (after text checks) | 45/60 (75.0%) [95% CI 62.8–84.2%] | 49/60 (81.7%) [95% CI 70.1–89.4%] | 42/60 (70.0%) [95% CI 57.5–80.1%] |
| mixed flag | 51/60 (85.0%) | 52/60 (86.7%) | 51/60 (85.0%) |
| required_action strict | 47/60 (78.3%) [95% CI 66.4–86.9%] | 50/60 (83.3%) [95% CI 72.0–90.7%] | 30/60 (50.0%) [95% CI 37.7–62.3%] |
| required_action lenient | 48/60 (80.0%) [95% CI 68.2–88.2%] | 51/60 (85.0%) [95% CI 73.9–91.9%] | 35/60 (58.3%) [95% CI 45.7–69.9%] |
| all three dimensions right | 31/60 (51.7%) | 35/60 (58.3%) | 20/60 (33.3%) |
| supplier-task precision | 3/4 (75.0%) [95% CI 30.1–95.4%] | 3/4 (75.0%) [95% CI 30.1–95.4%] | n/a (0/0) |
| supplier-task recall (automatic) | 3/3 (100.0%) [95% CI 43.8–100%] | 3/3 (100.0%) [95% CI 43.8–100%] | 0/3 (0.0%) [95% CI 0–56.2%] |
| false trigger on non-task cases | 1/57 (1.8%) [95% CI 0.3–9.3%] | 1/57 (1.8%) [95% CI 0.3–9.3%] | 0/57 (0.0%) [95% CI 0–6.3%] |
| should be human/clarify but automated | 1/44 (2.3%) [95% CI 0.4–11.8%] | 2/44 (4.5%) [95% CI 1.3–15.1%] | 0/44 (0.0%) [95% CI 0.0–8.0%] |
| duplicate rows that created a new task | n/a (0/0) | n/a (0/0) | n/a (0/0) |
| task draft completeness | 4/4 (100.0%) | 4/4 (100.0%) | n/a (0/0) |
| automatic actions demoted by confidence | 4/60 (6.7%) | 1/60 (1.7%) | 18/60 (30.0%) |
| latency p50 per case (ms) | 15712.0 | 1548.25 | 13.55 |

**Every 20b required_action outside acceptable_actions — heldout**

| id | lang | label issue/goal → action | 20b issue/goal → action | conf | kind | deciding rule (decided_by) | 120b action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| H08 | zh-Hant | SIZE_MISMATCH/INFORMATION → HUMAN_REVIEW | SIZE_MISMATCH/EXCHANGE/mixed → CLARIFY_WITH_CUSTOMER | 0.85 | wrong manual route | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. | CLARIFY_WITH_CUSTOMER |
| H12 | en | DEFECT/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/INFORMATION/mixed → CLARIFY_WITH_CUSTOMER | 0.95 | wrong manual route | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. | CLARIFY_WITH_CUSTOMER |
| H13 | de | PART_NEED/INFORMATION → HUMAN_REVIEW | DEFECT/BUY_PART → CREATE_SUPPLIER_TASK | 0.95 | FALSE TRIGGER | gates 1-4 passed: KL-170-LID (Lid assembly) compatible but 0 in stock; Kettleworks Ltd. (MOCK supplier) supplies parts: confirm availability and lead time. | CREATE_SUPPLIER_TASK |
| H14 | es | PART_NEED/INFORMATION → HUMAN_REVIEW | NO_ISSUE_INQUIRY/INFORMATION/mixed → CLARIFY_WITH_CUSTOMER | 0.85 | wrong manual route | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. | CLARIFY_WITH_CUSTOMER |
| H19 | de | DEFECT/REFUND → DIRECT_WORKFLOW | DEFECT/REFUND → HUMAN_REVIEW | 0.6 | wrong manual route | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.6 < 0.9) | HUMAN_REVIEW |
| H20 | es | UNCLEAR/REFUND → DIRECT_WORKFLOW | UNCLEAR/REFUND → HUMAN_REVIEW | 0.85 | wrong manual route | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.85 < 0.9) | DIRECT_WORKFLOW |
| H27 | en | SIZE_MISMATCH/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | SIZE_MISMATCH/INFORMATION → HUMAN_REVIEW | 0.95 | wrong manual route | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue SIZE_MISMATCH): a question, not a request to act; support answers it. No supplier task. | CLARIFY_WITH_CUSTOMER |
| H28 | en | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/INFORMATION → HUMAN_REVIEW | 0.95 | wrong manual route | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. | HUMAN_REVIEW |
| H30 | zh-Hant | DEFECT/UNCLEAR/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/INFORMATION → HUMAN_REVIEW | 0.95 | wrong manual route | gate 1 (intent_rules): R4 customer_goal INFORMATION (issue DEFECT): a question, not a request to act; support answers it. No supplier task. | HUMAN_REVIEW |
| H32 | es | DEFECT/REFUND/mixed → CLARIFY_WITH_CUSTOMER | DEFECT/REFUND → HUMAN_REVIEW | 0.7 | wrong manual route | gate 1 (intent_rules): R5 customer_goal REFUND: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. -> demoted (confidence 0.7 < 0.9) | DIRECT_WORKFLOW |
| H48 | es | DEFECT/REPAIR → DIRECT_WORKFLOW | DEFECT/REPAIR/mixed → CLARIFY_WITH_CUSTOMER | 0.95 | wrong manual route | gate 1 (intent_rules): R3 mixed / undecided goals or several items: ask the customer to separate them. | CLARIFY_WITH_CUSTOMER |
| H53 | de | PART_NEED/INFORMATION → HUMAN_REVIEW | PART_NEED/BUY_PART → CLARIFY_WITH_CUSTOMER | 0.95 | wrong manual route | gate 2 (matches_order): No order number in the message and no linked order: ask for it. | HUMAN_REVIEW |

Cases where the two models chose a different action: 6/60 (H20, H27, H32, H40, H41, H53). Wrong for both models: H08, H12, H13, H14, H19, H28, H30, H32, H48.


## Round 3 (taxonomy v3), held-out v2 (300 messages, frozen c65eb83). Single run per pipeline, same model and provider

| | rules 0.2.0 · gpt-oss-20b@NVIDIA | **v3 k1** · gpt-oss-20b@NVIDIA | v3 k3 | v3 k5 |
|---|---|---|---|---|
| required_action lenient | 206/300 (63.2–73.7%) | **282/300 (90.7–96.2%)** | 277/300 (88.8–94.8%) | 271/300 (86.5–93.2%) |
| strict | 194/300 (59.1–69.9%) | 274/300 (87.6–94.0%) | 268/300 | 261/300 |
| supplier tasks correct / predicted / required | 55 / 63 / 106 | 103 / 108 / 106 | 97 / 99 / 106 | 89 / 90 / 106 |
| false triggers (of 194) | 8 | 5 | 2 | 1 |
| median latency | 9.8 s | 46.5 s (p90 130.6 s, NVIDIA queueing) | same samples | same samples |

v3 cost at Groq list prices (production provider), including agreement samples: about $0.001 per message (512k input +
847k output tokens for 300 messages). Production on Groq would need k separate requests for k>1, because Groq requires
n=1. Latency was measured on NVIDIA's shared endpoint under heavy load; earlier rounds measured Groq at about 1–3 s per
call.

Judge models used for labelling (NVIDIA; not used by the app):
- `nvidia/nemotron-3-ultra-550b-a55b`: median about 85 s per label.
- `z-ai/glm-5.3`: about 88 s per label, then account-throttled (HTTP 429).
- `meta/muse-glimmer-30b`: about 157 s per label; schema not enforced server-side, so outputs are validated in code.
