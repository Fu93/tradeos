# Held-out label errata (written AFTER the first held-out run; labels NOT edited)

`heldout-labels.json` stays exactly as frozen in commit d5752f0. Every metric in `routing-results.md` is computed against
those frozen labels. This list records labels that, on re-reading the message against
[the labelling guide](heldout-labelling-guide.md), look clearly wrong. It is for the human reviewer, who decides.

| id | field | frozen label | probably correct per guide | why | effect on reported metrics |
| --- | --- | --- | --- | --- | --- |
| H60 | issue_type | NO_ISSUE_INQUIRY | MISSING_ITEM | 「デスクランタンプの白いのは届いていませんが…」 says the white lamp has **not arrived**. The guide's NO_ISSUE_INQUIRY means "no problem with a purchase", and a non-arrival is a problem even if the customer only asks a hypothetical question. customer_goal INFORMATION and required_action HUMAN_REVIEW are unaffected. | The LLM run's issue_type is counted as wrong on H60. With the errata applied it would be 49/60 instead of 48/60. Route metrics are unchanged. |

Rows where the system disagreed but the label is still defensible are **not** errata. They are pre-selected for the human spot-check in `heldout-review.csv` (`priority_review` = YES):

* H48: "repair or replace", which the guide convention treats as one REPAIR goal.
* H50: issue PART_NEED vs DEFECT.
* H45: issue UNCLEAR vs NO_ISSUE_INQUIRY.
* H07, H15: PART_NEED vs NO_ISSUE_INQUIRY.
* H44, H40: goal UNCLEAR.
