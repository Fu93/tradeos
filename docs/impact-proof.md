# Impact proof: what the evals show, and what they do not

> **Status: evidence summary, no new claims.** Every number below is copied or summed from the committed eval
> artifacts named in each table. Nothing was re-run for this document. The supplier-routing experiment is on **MOCK
> data** (mock catalogue and mock suppliers) and is **not on `main`**: its artifacts are on branch `exp/supplier-routing-mvp1`, commit
> `95d45f1`, and are linked by commit below so the links do not drift.

## Three validation levels (do not mix them up)

| Level | What it is | Where it stands |
|---|---|---|
| **1. Test / automated eval results** | A frozen pipeline run once on a labelled message set and scored against the labels. Labels came from the design plus two LLM judges (nemotron-3-super "N", gemma-4-31b-it "G"). | **Done**, numbers below. |
| **2. Human adjudication of specific disputed labels** | The author and the user ruled on individual labels where judges and design disagreed or a guide rule changed. | **Done only for the specific items listed in section 4**: 8 author adjudications in v4 (4 of them reviewed by the user), plus a 40-row user spot-check on the earlier held-out v2 set. |
| **3. Full human audit of every label and every outcome** | A person independently labelling or re-checking all 308 messages. | **NOT done.** In `heldout-v4-review.csv` (44 rows pre-selected for review: 22 safety, 18 errors, 4 low-risk) only 4 rows carry a human label. |

So "290/308" means "290 of 308 outputs match labels that were produced by model judges plus design and only partly
human-checked". It is **not** a measured real-world accuracy.

## 1. Headline: held-out v4 (308 synthetic messages, 5 languages)

Source: [`docs/eval/v3/heldout-v4-results.md`](https://github.com/Fu93/tradeos/blob/95d45f1/docs/eval/v3/heldout-v4-results.md), [`docs/eval/v3/heldout-v4-summary.json`](https://github.com/Fu93/tradeos/blob/95d45f1/docs/eval/v3/heldout-v4-summary.json). Set frozen before the run; each pipeline run once; build frozen.

| Run | Correct / 308 | Wilson 95% | Safety cases routed to a human | Over-triggered supplier tasks (of 235 non-supplier) | Own acceptance bar |
|---|---|---|---|---|---|
| v3.2 k1 (primary) | 290/308 | 91.0–96.3% | 85/85 | 2/235 | not met |
| v3.2 k3 | 286/308 | 89.4–95.2% | 85/85 | 0/235 | MET |
| v3.2 k5 | 279/308 | 86.8–93.4% | 85/85 | 0/235 | MET |
| v3.1 ba8e60e (k1) | 233/308 | 70.6–80.1% | 39/85 | 23/235 | not met |
| rules 0.2.0 | 183/308 | 53.8–64.8% | 35/85 | 43/235 | not met |

* **85/85 safety cases were routed to human review** by v3.2 (all three vote settings); 0 were automated. Previous
  version v3.1: 39/85. The results file's own caveat: "a pass on this test, not a proof of real-world safety".
* **k1 vs multi-vote.** k1 is a single extraction (primary run). k3 and k5 are the multi-vote reruns (method: see the source file). In these numbers, voting trades recall for precision: tasks created correctly / true tasks = 63/73 at k1,
  58/73 at k3, 51/73 at k5, while over-triggers fall from 2 (k1) to 0 (k3, k5).
  The primary run (k1) is the one marked **"bar: not met"** in the source; only the k3/k5 reruns are marked MET.
* Human share (cases sent to a human): all 0.451, non-safety 0.242 at k1 (source: results file, "Notes").

### By language (k1; same files)
| Language | en | zh-Hant | es | de | ja |
|---|---|---|---|---|---|
| v3.2 k1 | 58/65 | 53/56 | 59/62 | 58/62 | 62/63 |
| v3.1 | 48/65 | 42/56 | 50/62 | 48/62 | 45/63 |

## 2. Outcomes by case category (held-out v4, correct / total)

Source: `slices` in [`docs/eval/v3/heldout-v4-summary.json`](https://github.com/Fu93/tradeos/blob/95d45f1/docs/eval/v3/heldout-v4-summary.json) (same table in [`docs/eval/v3/heldout-v4-results.md`](https://github.com/Fu93/tradeos/blob/95d45f1/docs/eval/v3/heldout-v4-results.md)). A slice is a category of case defined in the dataset design.

| Category | What it is | v3.2 k1 | v3.2 k3 | v3.2 k5 | v3.1 | rules 0.2.0 |
|---|---|---|---|---|---|---|
| `safety` | Safety: gated product class (kettle/lamp/stove) + reported malfunction | 76/76 | 76/76 | 76/76 | 38/76 | 33/76 |
| `unmapped` | Malfunction on a product that cannot be identified | 9/9 | 9/9 | 9/9 | 1/9 | 2/9 |
| `low_risk_malfunction` | Malfunction on a low-risk product | 26/31 | 26/31 | 25/31 | 28/31 | 24/31 |
| `gated_no_malfunction` | Gated product, no malfunction | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 |
| `buyer_vs_seller` | Buyer error vs seller error (who caused the problem) | 33/38 | 30/38 | 26/38 | 27/38 | 4/38 |
| `order_conflict` | Message conflicts with the order record | 25/27 | 26/27 | 26/27 | 21/27 | 14/27 |
| `intent_revision` | Customer changes their request mid-message | 12/13 | 12/13 | 12/13 | 12/13 | 10/13 |
| `complaint_only` | Complaint without a remedy request | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |
| `normalisation` | Order id / text normalisation (e.g. Unicode hyphens) | 8/8 | 8/8 | 8/8 | 7/8 | 1/8 |
| `normal_task` | Ordinary supplier-task requests | 38/43 | 36/43 | 34/43 | 37/43 | 36/43 |
| `other` | Everything else (status questions etc.) | 52/52 | 52/52 | 52/52 | 51/52 | 48/52 |

The slices partition the 308 messages (the totals sum to 308; the k1 correct counts sum to 290).

## 3. Remaining errors at v3.2 k1 (18 of 308) and why

Source: "Errors, v3.2 k1 (primary)" in [`docs/eval/v3/heldout-v4-results.md`](https://github.com/Fu93/tradeos/blob/95d45f1/docs/eval/v3/heldout-v4-results.md); the "why" is the rule and reason text the pipeline itself recorded
plus the file's own "Known v3.2 errors" note. The set is frozen: these were **not fixed**.

| Rule | Count | Message ids | Direction of the error | Why |
|---|---|---|---|---|
| V2 | 4 | X021, X031, X172, X170 | HUMAN_REVIEW vs label CLARIFY_WITH_CUSTOMER; HUMAN_REVIEW vs label CREATE_SUPPLIER_TASK | Evidence quote not found in the message, so a human reads it (cautious; costs labour). |
| V3 | 3 | X012, X011, X015 | HUMAN_REVIEW vs label CREATE_SUPPLIER_TASK | Customer's stated size/variant disagrees with the order, so a human verifies instead of creating the supplier task (cautious; labelled task). |
| V12b | 3 | X003, X052, X301 | CLARIFY_WITH_CUSTOMER vs label CREATE_SUPPLIER_TASK | No explicit remedy request in the text, so it asks the customer instead of creating a task (cautious). |
| V11 | 2 | X062, X159 | CLARIFY_WITH_CUSTOMER vs label CREATE_SUPPLIER_TASK; CLARIFY_WITH_CUSTOMER vs label DIRECT_WORKFLOW | Part requested without exactly one part number, so it asks (part models are never guessed). |
| V12 | 2 | X177, X199 | CREATE_SUPPLIER_TASK vs label DIRECT_WORKFLOW; CREATE_SUPPLIER_TASK vs label HUMAN_REVIEW | Created a supplier task where the label wanted the normal flow or a human (X177) / typo conflict auto-tasked because the extractor gave no variant quotes and the text-scan fallback still guessed (X199). **Not cautious.** |
| SG | 1 | X040 | HUMAN_REVIEW vs label CLARIFY_WITH_CUSTOMER | Safety Gate over-block: a lost lamp (reship) was gated as a malfunction. |
| V7 | 1 | X059 | CLARIFY_WITH_CUSTOMER vs label CREATE_SUPPLIER_TASK | Two items in one message need separate handling, so it asks which first. |
| V10 | 1 | X193 | DIRECT_WORKFLOW vs label HUMAN_REVIEW | Conflict misread as buyer error: went to the policy flow where the label wanted a human. **Not cautious**: the one kind of error that is an automation miss. |
| V4b | 1 | X223 | CLARIFY_WITH_CUSTOMER vs label DIRECT_WORKFLOW | Customer revised towards a refund, extracted intent disagrees, so it asks which outcome (cautious). |

Reading: 15 of the 18 errors are the pipeline being more cautious than the label (it sent the case to a human or asked the customer; labour cost, no wrong action taken). 3 errors took an automated step the label did not want
(X193 (DIRECT_WORKFLOW), X177 (CREATE_SUPPLIER_TASK), X199 (CREATE_SUPPLIER_TASK)). Two of these (X177, X199) are the
"false triggers" in section 1; the third (X193) is a conflict case routed to the policy flow, where refunds are human-approved on `main`.
None of the 18 is a safety case routed away from a human.

## 4. Human adjudication of specific disputed labels (Level 2) and what is not audited (Level 3)

| Item | What a human decided | Source |
|---|---|---|
| X068, X069, X071, X284 | Author: order id written with a Unicode hyphen variant maps to a valid order after normalisation; the design label stands (judges failed to normalise). | [`docs/eval/v3/heldout-v4-author-adjudication.json`](https://github.com/Fu93/tradeos/blob/95d45f1/docs/eval/v3/heldout-v4-author-adjudication.json) |
| X148, X149, X150, X152 | Author override to `HUMAN_REVIEW` (malfunction on an unidentifiable product, guide v3.2 SG-2); the user reviewed and kept `HUMAN_REVIEW`. The 4 are the only rows with a human label in the review CSV. | [`docs/eval/v3/heldout-v4-author-adjudication.json`](https://github.com/Fu93/tradeos/blob/95d45f1/docs/eval/v3/heldout-v4-author-adjudication.json), [`docs/eval/v3/heldout-v4-review.csv`](https://github.com/Fu93/tradeos/blob/95d45f1/docs/eval/v3/heldout-v4-review.csv), "User review notes" in [`docs/eval/v3/heldout-v4-results.md`](https://github.com/Fu93/tradeos/blob/95d45f1/docs/eval/v3/heldout-v4-results.md) |
| Held-out v2 spot-check | User checked 40 priority rows: 39 agree, 1 proposed correction (V137), **not applied** to frozen labels. The file states this is the user's agreement rate with existing labels, not model accuracy. | [`docs/eval/v3/heldout-v2-review-notes.md`](https://github.com/Fu93/tradeos/blob/95d45f1/docs/eval/v3/heldout-v2-review-notes.md) |
| Label provenance in v4 | 240 of 308 judges and design agree; 54 are 2-of-3; 6 judges agree against design; 4 + 4 author-adjudicated. | "Adjudication" in [`docs/eval/v3/heldout-v4-results.md`](https://github.com/Fu93/tradeos/blob/95d45f1/docs/eval/v3/heldout-v4-results.md) |

**Judge agreement is not human agreement.** The kappa of **0.74** (raw agreement 250/308) for
`required_action` is between the two LLM judges N and G. Others: speech_act 0.917, issue_type 0.911, safety flag 0.836; N vs partial muse
judge (n=130) 0.619; N vs design 0.703, G vs design 0.925. The results file says it directly: "Kappa is
judge agreement, not accuracy." There is **no** human inter-annotator figure.

**Level 3, a full human audit, was NOT done.** In particular: the 308 messages are synthetic (generated by three
models), not real customer traffic; the labels are partly model-produced; only a handful of labels have a human ruling.

## 5. Earlier eval on `main`: intent extraction on 52 hand-labelled messages

Source: [`docs/eval/results.md`](eval/results.md), [`docs/eval/results.json`](eval/results.json) (these are on `main`).
This is a different, older eval (intent extraction, pre-exchange policy; the file carries its own staleness caveat).
LLM exact match 73% (38/52) vs keyword fallback 15% (8/52); intent alone 94% (49/52); 7 prompt-injection messages, 0 unwarranted accepts.
Labels by one author, no inter-annotator check (its own "Limits").

## What this does NOT show
* No real-money or live-customer outcomes. Everything here is tests on synthetic or hand-written messages and the PayPal Sandbox.
* No claim that the numbers will hold on real traffic, other languages, or other models.
* The supplier-routing experiment (mock suppliers, mock catalogue) is not part of the deployed app on `main`.
* The 85/85 is "0 automated on this set", not a safety guarantee.
* Refund amounts never come from the LLM; that rule is enforced in code and covered by the tests in the repo, which is a separate matter from the eval numbers above.
