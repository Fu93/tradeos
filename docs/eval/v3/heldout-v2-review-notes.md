# Held-out v2: user spot-check (completed review)

Source: `heldout-v2-review-completed.csv` (the user's completed copy of `heldout-v2-review.csv`).

## Result
- **40/40 rows reviewed. 39 agree, 1 proposed correction.**
- **What 39/40 means:** it is the user's agreement rate with the existing (author-adjudicated) labels on a priority
  sample. It is **not** model accuracy and **not** an independent evaluation.
- The frozen held-out v2 labels (`heldout-v2-labels.json`) and the reported held-out v2 scores
  (`heldout-v2-results.md`, `heldout-v2-summary.json`) are **unchanged**.

## Errata (pending correction; NOT applied to the frozen labels or scores)
| id | frozen label | proposed | reason |
|---|---|---|---|
| V137 | DIRECT_WORKFLOW (acceptable: DIRECT/HUMAN) | HUMAN_REVIEW | The customer says they ordered white and received black, but the order record says black. The customer's claim conflicts with the order data, so a human reconciles it. A seller-error claim is never accepted on the customer's word alone. |

## Reviewer notes recorded as guidance (applied to the v3.1 dev rules and guide, validated only on fresh data)
- **V153, V211** (kettle smells of burnt plastic; power base fault): safety, so human review.
- **V140–V146**: when the product the customer describes conflicts with the order record, resolve the data conflict
  first. Never create a task from the multi-item complaint.
- **MP07B, MP10B**: when the customer explicitly switches to a refund, use the last stated intent. Clarify if the system
  cannot reliably tell.
- **V154, V156–V158**: a complaint with no explicit remedy request must not create a supplier task.
