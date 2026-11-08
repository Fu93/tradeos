# Merchant task study: measure value without inventing a saving

The [case economics](../README.md#case-economics) box is an illustrative model. This protocol is for collecting a
small, clearly labelled usability result before claiming that TradeOS saves merchants time. It contains **no results**.

## Participants and materials

Recruit at least five people who did not build TradeOS; identify how many actually handle merchant returns. Use
fictitious buyers and Sandbox orders only. Give each participant the same short task brief and the same order facts.
Do not disclose the expected decision in the brief. Record whether they have used PayPal merchant tools before.

Use three tasks: an eligible ordinary refund, a 45-day-old return outside the 30-day window, and an agent-originated
return that uses a prompt-injection message. Include a fourth multilingual exchange only if both the manual baseline
and TradeOS path can be completed comparably. For each participant, alternate which workflow comes first to reduce
learning effects. The manual baseline must use the same available policy and Sandbox order information as TradeOS;
do not make it artificially harder.

Start timing when the participant opens the customer request; stop when they record a decision and, if appropriate,
finish the Sandbox action. Do not count setup or coaching time. Note every hint and interruption. Collect per task:

| Field | Meaning |
| --- | --- |
| participant_id, merchant_experience | Anonymous identifier and prior experience |
| task, workflow, order | Scenario, `manual` or `tradeos`, and presentation order |
| elapsed_seconds, clicks, hints | Observed time and assistance |
| decision, expected_decision | Participant decision and prewritten policy result |
| refund_api_calls, amount | PayPal result, including zero for blocked cases |
| confidence_1_to_5, notes | Participant rating and observed friction |

Prewrite expected decisions before sessions. Report the raw count of participants and tasks, completion rate, median
time for each workflow and task, number of incorrect decisions, and any missing or excluded runs. Show individual
times or a range; with a tiny sample, do not imply population-wide accuracy or a reliable return on investment.
Calculate time difference as `manual median − TradeOS median` on comparable completed tasks. If it is negative,
report that too. Keep the illustrative $2.28 saving separate from observed time results until labour costs are
measured with a stated source. Obtain permission before quoting or naming a participant.

The final submission should link the anonymized observations and protocol, or say plainly that merchant validation
has not yet been done. Synthetic intent evals and PayPal Sandbox checks answer different questions; neither measures
merchant labour saved.
