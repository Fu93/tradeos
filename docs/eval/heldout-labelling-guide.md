# Labelling guide: issue_type / customer_goal / required_action (round 2)

Written from the user's design for supplier routing, **not from the code**. Its sources are:

* the round-1 brief (supplier involved only when needed; four gates; refund path untouched; AI only extracts);
* the round-2 brief (three dimensions; a defect ≠ supplier needed; a part mention ≠ complaint; REFUND → existing refund flow; inquiries are not complaints; mixed/negated → clarify/human);
* the business facts that the mock shop states. These are the "supplier responsibility table" in plain words, listed at the end.

The guide is used for both sets:

* the held-out set: `heldout-labels.json`;
* the original 100: `routing-dataset-dims.json`.

Every case gets three **separate** labels. No single label decides the route by itself.

## 1. issue_type: what problem the customer describes about something they bought

| Label | When |
| --- | --- |
| `SIZE_MISMATCH` | Wrong or ill-fitting size, colour or variant (received, or wanted different). |
| `DEFECT` | The item is broken, faulty, damaged, of poor quality, or behaves oddly. This includes "is this a defect?" questions. |
| `MISSING_ITEM` | An item, or part of an order, never arrived or is missing from the parcel. |
| `PART_NEED` | The customer needs or asks about a specific spare part for an item they own (worn, lost, broken part). |
| `NO_ISSUE_INQUIRY` | No problem with a purchase. This covers: pre-purchase questions, policy questions, order lookups, praise, hypotheticals, and an explicitly negated problem ("not broken at all, just asking"). |
| `UNCLEAR` | A problem is hinted but is none of the above (e.g. late delivery), cannot be told apart, or there are two different problems at once. |

The issue is labelled even when the customer only asks a question about it. The **goal** carries "only a question".

## 2. customer_goal: what outcome the customer asks for

| Label | When |
| --- | --- |
| `REFUND` | Money back. "Return it" / "send it back" / devolver / zurückgeben / 退貨 with no other outcome counts as REFUND, because return-for-refund is the existing refund flow. |
| `EXCHANGE` | Swap for a different size, colour or variant. |
| `RESHIP` | Send the missing or lost item (again). |
| `REPAIR` | Fix the defective item: "repair or replace", "please replace it" (same item), "please fix / handle / give me a solution", "what can you do?". |
| `BUY_PART` | Explicitly asks us to send or sell them a spare part ("please send me KL-170-LID", "I'd like to order one"). |
| `INFORMATION` | Only a question. Examples: "do you sell X separately?", "is it in stock?", "is this normal?", "can I buy only the part?", "what is your policy?", "where is my order?". |
| `UNCLEAR` | No outcome is requested (venting, "please help", "what's happening?"), or the customer is undecided between outcomes. |

`mixed` = true when the message contains more than one requested outcome, is undecided between outcomes, or covers two different items or problems that need separate handling.

## 3. required_action: decided in this order (first match wins)

1. Instruction-like text, or a **safety** issue → `HUMAN_REVIEW`. Safety means fire, smoke, sparks, burning, electric shock, gas leak or gas smell, or injury. A water leak or a "burned-out" bulb is not safety.
2. `mixed` → `CLARIFY_WITH_CUSTOMER`.
3. Goal `INFORMATION` (whatever the issue) → `HUMAN_REVIEW`. Support answers; no supplier task.
4. Goal `REFUND` → `DIRECT_WORKFLOW`. The existing refund policy flow does identification, eligibility, human approval and PayPal. **Never** a supplier task, even for a defect or a part.
5. Goal `UNCLEAR` (a problem but no outcome) → `CLARIFY_WITH_CUSTOMER`.
6. Goal is EXCHANGE / RESHIP / REPAIR / BUY_PART. The case must be identifiable:
   - the exact order number is in the message (held-out cases have no linked order; no fuzzy matching);
   - the order belongs to the writer, and the product is in it;
   - the needed detail is given: target size/colour for EXCHANGE, part number for BUY_PART, fault for REPAIR.

   If the order number or a detail is missing, or the order number does not exist → `CLARIFY_WITH_CUSTOMER`. If the order belongs to someone else, or the product is not in the order → `HUMAN_REVIEW`.
7. Only now, is the supplier needed (business facts below)? If yes → `CREATE_SUPPLIER_TASK`. If our own data or policy resolves it → `DIRECT_WORKFLOW`. If no data is found → `HUMAN_REVIEW`.

`acceptable_actions` lists a second action only where two readings of the guide are genuinely defensible. It is fixed together with the label. A supplier task is never an "acceptable" alternative for a non-task label.

## Business facts used in step 7 (the shop's own description; MOCK)

* **Return window**: 30 days. Socks are final sale.
* **Exchange**:
  - Sneakers and desk lamp are drop-shipped by the supplier, so the supplier confirms stock: supplier task.
  - Jacket, backpack and socks are in our warehouse. If we have the target variant in stock → direct. If the jacket is out of stock → supplier restock (task). If there is no stock record → human.
  - Outside the window or final sale → direct (policy decides).
* **Missing item**:
  - Parcel still in transit → direct (share tracking).
  - Carrier says delivered in full → human.
  - Lost or partial on a drop-shipped item → supplier task.
  - Lost or partial on a warehouse item with stock → direct.
* **Defect**:
  - Within 30 days → direct (existing return policy).
  - After that, inside the supplier warranty → supplier task. Supplier warranties: sneakers 180 d; kettle, stove 365 d; lamp 730 d.
  - Backpack: our own 365-day warranty → direct.
  - Otherwise → human.
* **Spare part**:
  - In our stock (KL-170-FLT, BP-BUCKLE-25) → direct.
  - Out of stock and the supplier supplies parts (kettle, lamp) → supplier task.
  - Stove valve: the supplier does not supply parts → human.

## Conventions decided before labelling (to keep labels consistent)

* "Do you sell X separately / is X in stock / can I buy only the part?" is `INFORMATION`, even when the customer clearly needs the part. Only an explicit "send me / I want to order X" is `BUY_PART`. This follows the user's regression example "Do you sell the LED module separately?" → no supplier task.
* A problem that is explicitly negated ("not broken at all") → issue `NO_ISSUE_INQUIRY`.
* "Repair or replace" offered as either/or is one remedy (`REPAIR`), not a mixed goal. "Exchange or refund?" is mixed.
* The generator's `language` tag was wrong for 3 English messages (H03, H18, H23). Labels record the actual language; the raw tag is kept as `generator_language_tag`.
* The generator's `writer_intent` was not used as a label.
