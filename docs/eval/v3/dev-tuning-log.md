# Routing v3: dev tuning log (DEV DATA ONLY)

Tuning used only: the original 100, the old held-out 60 (round-2 labels, pre-v3 taxonomy, so some "errors" are taxonomy
differences) and the 28 dev minimal pairs (56 messages, designed labels). **Held-out v2 was never run during tuning.**
All runs: NVIDIA, `openai/gpt-oss-20b` (production extractor model), strict json_schema, temperature 0 for the primary
extraction; agreement samples at temperature 0.6 (k−1 extra samples, only when the primary decision is a suggested task).

| change | dev evidence (id) | effect (offline re-decide on stored extractions) |
|---|---|---|
| Prompt: self-correction ("Actually … instead") keeps only the final goal | MP06B | fixed (dev pairs) |
| Prompt: "please send part X"/lost-by-customer = PART_NEED | MP03B | fixed |
| Prompt: evidence must be the customer's words, never a label name; V2 accepts a verified goal quote as speech-act evidence for a REQUEST and a verified component / variant / part quote as issue evidence | MP12B, MP35A | fixed (still verbatim, code-checked) |
| S4 now has the same narrow negation guard as S1; JA negation `〜なく/ず` | MP56A, MP60A ("No smoke or smell", 「煙も臭いもなく」) | fixed; positive hazards still fire (tests) |
| Goal normalisation by issue (C1 + table): WRONG_ITEM + REPLACE_SAME/RESHIP → EXCHANGE to ordered variant; MISSING_ITEM + REPLACE_SAME or SEND_PART without part number → RESHIP | MP65A, R08 | fixed |
| V7: several extracted items about ONE product with ONE remedy family are merged (not "separate handling") | agreement-sample splits MP16A/MP46A/MP56A | fewer spurious V7 clarifies |
| Hedge lexicon (`glaub ich`, `si no me equivoco`, …) | MP49B | fixed (V4 clarify instead of V3 conflict) |
| Part-request consistency (C4): MISSING_ITEM/UNCLEAR + exactly one catalogue part number in text + SEND_PART/REPLACE_SAME + no missing-delivery words → PART_NEED | P07, P08, MP62A | fixed; a real "missing from the box" claim still → human (test) |
| Every part number in the TEXT counts (model may extract one of two) | P19 (false trigger) | fixed → ASK_PART |
| V5 also checks the goal-evidence sentences (an unrelated "bestellt" elsewhere no longer masks an availability question) | H13 (false trigger in every earlier round) | fixed → HUMAN |
| Safety prompt: ordinary faults (flicker, not heating, leak) are NONE unless heat/smoke/sparks/shock/gas | D02 | prompt only; rules unchanged |
| ASK_ORDER_REF wording: "our order numbers have the format TO-12345" (ES translation had read it as a guess) | screenshot run | template text |

Offline re-decision with the final rules on the stored dev extractions: original 100: 86 → **90/100** (old labels);
dev pairs: 51 → **54/56**; old held-out 60: 45 → **46/60** (old labels). Supplier false triggers on dev after tuning: **0**
(P19, H13 fixed by deterministic rules).

Remaining dev "errors" are mostly deliberate v3 taxonomy differences vs the round-2 labels: changed-mind exchanges →
DIRECT (C3/D3), safety-first (KL-170-BASE power part, "quemó"), malformed / other-customer order refs → clarify / human,
information questions → human (V6), no requested outcome → ASK_GOAL.

## Agreement gate (V13) on dev, pre-registered choice

| set | k=1 tasks (TP / pred / true) | k=3 | k=5 | false triggers k1 → k3 → k5 |
|---|---|---|---|---|
| dev pairs (dev2, temp 0.6) | 21/21/24 | 17/17/24 | 15/15/24 | 0 → 0 → 0 |
| original 100 (dev3) | 25/26/36 | 22/22/36 | 21/21/36 | 1 → 0 → 0 |
| old held-out 60 (dev4) | 1/2/3 | 1/2/3 | 1/1/3 | 1 → 1 → 0 |

The two false triggers the gate caught (P19, H13) are now caught by deterministic rules; the gate costs 15–35% of task
recall. **Pre-registered for the frozen build: k=1 (no gate) is the primary result; k=3 and k=5 are computed from the
same held-out run (k−1 extra samples at temperature 0.6, only for suggested tasks) and reported as the trade-off.**
