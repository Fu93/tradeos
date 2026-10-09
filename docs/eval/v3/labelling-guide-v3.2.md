# Labelling guide v3.1: supplier routing (taxonomy v3, v3.1 round)

**v3.1 changes (written before held-out v3 was generated; marked ★ below and summarised in section 11).**

Original status of v3: frozen together with held-out v2 (written **before** any v2 message was generated or labelled, and before any
v3 code existed). Source: `taxonomy-v3-draft.md` (definitions + decisions D1–D13, all adopted as recommended) plus the
clarifications in section 6, which the draft left open. Labels describe **what the customer wrote** and **what the
correct handling is**, judged by meaning, not by what any system would output.

## 1. What you label (per message)

| Field | Values | Notes |
|---|---|---|
| `speech_act` (+ evidence quote) | `QUESTION`, `REQUEST`, `COMPLAINT_ONLY`, `OTHER` | One per message (section 2) |
| `items[]` | one entry per product+problem that needs separate handling | Section 3 |
| `items[].issue_type` (+ quote) | `SIZE_MISMATCH`, `WRONG_ITEM_OR_VARIANT`, `CUSTOMER_ORDERED_WRONG`, `DEFECT`, `MISSING_ITEM`, `PART_NEED`, `NO_ISSUE`, `UNCLEAR` | Section 4 |
| `items[].goals[]` (+ quote each, ranked) | `REFUND`, `EXCHANGE_VARIANT`, `REPLACE_SAME`, `REPAIR`, `RESHIP`, `SEND_PART`, `INFORMATION` | May be empty. Section 5 |
| `items[].goal_relation` | `NONE`, `SINGLE`, `EITHER_ACCEPTABLE`, `UNDECIDED` | Section 5 |
| `negated_goals[]` | goal values the customer explicitly does **not** want | "I don't want a refund" |
| `safety` (+ quote) | `NONE`, `POSSIBLE`, `EXPLICIT` | Section 7 |
| `order_ref_as_written`, `order_ref_hedged` | the order reference exactly as written (never corrected), and whether the customer is unsure about it | Section 8 |
| `part_numbers_as_written[]` | part numbers exactly as written | |
| `required_action` | `DIRECT_WORKFLOW`, `CREATE_SUPPLIER_TASK`, `CLARIFY_WITH_CUSTOMER`, `HUMAN_REVIEW` | **Derived with the decision table (section 9)** from the fields above + the MOCK records. Do not label it by feel |
| `deciding_rule` | `V0`…`V12` | The first row of the table that matched |
| `acceptable_actions[]` | other actions that are genuinely defensible | `CREATE_SUPPLIER_TASK` is **never** acceptable on a message whose `required_action` is not a supplier task |

`mixed` is **not** labelled; it is computed from items and goals (section 9, V7).

## 2. `speech_act` (pragmatic, not formal)

Order of precedence when a message has several sentences:
1. Any sentence that **asks us to do something** (refund, exchange, repair, send, cancel) → `REQUEST`.
2. Otherwise any question (in any form) → `QUESTION`.
3. Otherwise a problem is described without a request or question → `COMPLAINT_ONLY`.
4. Otherwise (thanks, spam, unrelated) → `OTHER`.

Boundary cases:
- "Can you repair or replace it?" / "¿Me pueden enviar uno?" / "Können Sie das reparieren?" → `REQUEST` (polite request).
- **D9**: "Can I swap it for the black one?" / "Can I return it?" about a remedy **on the customer's own order** → `REQUEST`.
- "Do you have / sell / stock X?" / "Hättet ihr noch …?" / "¿Tienen …?" / "…ありますか" / "有沒有…" (availability) → `QUESTION`,
  unless the same message explicitly asks us to send / order it ("please send me one", "I'd like to order it").
- "Is it possible to buy the filter separately?" → `QUESTION`. "How do I return?" / "Do I send them together?" (process) → `QUESTION`.
- "What's better for me, exchange or refund?" → `QUESTION`, with both candidate goals listed (section 5).
- "It arrived broken. Unacceptable." → `COMPLAINT_ONLY`.

## 3. `items[]`

One item = one product (or one thing the customer describes) + one problem. Two unrelated problems with the same product
are two items. Several symptoms of one problem are one item. A product only mentioned in passing (no problem) is not an
item. A pure policy question with no product problem may have zero items or one `NO_ISSUE` item.

## 4. `issue_type`

| Value | Definition | Signals |
|---|---|---|
| `SIZE_MISMATCH` | received exactly what was ordered, but it does not fit | "too small", "sleeves too short"; no claim that it differs from the order |
| `WRONG_ITEM_OR_VARIANT` | **seller sent** a different product / size / colour / accessory than ordered | "you sent 43 instead of 42", "wrong colour clamp", "not what I ordered" |
| `CUSTOMER_ORDERED_WRONG` | the customer chose wrong, or changed their mind | "I ordered the wrong size by mistake", "me equivoqué", "I'd prefer black after all" |
| `DEFECT` | product or a component is broken, faulty, poor quality, damaged in transit | broken, doesn't work, cracked, leaks, flickers, "feels like cardboard". **A broken component is DEFECT** (put it in `component`) |
| `MISSING_ITEM` | an item / part of the order never arrived or was missing from the box | "never arrived", "only one of two", "box had no lid" |
| `PART_NEED` | needs a spare part **without** claiming a defect | part lost, normal wear, consumable used up ("filter is used up"), wants a spare |
| `NO_ISSUE` | no problem with a purchase | pre-sale question, policy question, order status, praise, "it's not broken at all" |
| `UNCLEAR` | some problem is implied but cannot be classified | "something's off with my order", delivery delay (D12) |

Contrasts: "sent me 43, I ordered 42" → WRONG_ITEM_OR_VARIANT; "42 feels tight" → SIZE_MISMATCH; "I picked black by
mistake" → CUSTOMER_ORDERED_WRONG; "the lid broke, I want to order a new one" → DEFECT + SEND_PART; "the limescale filter is
used up" → PART_NEED; "is it normal that it clicks?" → DEFECT with speech_act QUESTION.

## 5. `goals[]` and `goal_relation`

| Goal | Meaning | Not this |
|---|---|---|
| `REFUND` | money back; "return it" with no other outcome also counts | "return it for a bigger size" → EXCHANGE_VARIANT |
| `EXCHANGE_VARIANT` | swap for a **different** size / colour / model, or for the variant that was actually ordered (wrong item) | same item again because it broke → REPLACE_SAME |
| `REPLACE_SAME` | a new unit of the same item (because of a defect) | |
| `REPAIR` | fix the existing item | "can I fix it myself?" → INFORMATION |
| `RESHIP` | send again what did not arrive | |
| `SEND_PART` | send a part to the customer (free or paid is decided by rules, not by you) | "do you sell the lid separately?" → INFORMATION |
| `INFORMATION` | only wants an answer | |

- No outcome stated → `goals = []`, `goal_relation = NONE`. There is no "UNCLEAR" goal.
- **D1**: "repair or replace (either is fine)" → `[REPAIR, REPLACE_SAME]`, `EITHER_ACCEPTABLE`. Shown as REPAIR_OR_REPLACE, not a separate value.
- `UNDECIDED` = two or more goals and the customer has not chosen ("not sure if I should exchange or just return").
- Information plus one action ("does DL-LED-7W fit? can you get one for me?") → `[INFORMATION, SEND_PART]`; not mixed.

Remedy families (used by the table): REFUND={REFUND}; WARRANTY_REMEDY={REPAIR, REPLACE_SAME, SEND_PART};
EXCHANGE={EXCHANGE_VARIANT}; FULFILMENT={RESHIP}; INFO={INFORMATION}.

## 6. Clarifications beyond the draft (decided before any v2 message existed)

- ★ **C1 wrong item (v3.1)**: a seller-error claim is **never accepted on the customer's word alone**. It is only
  eligible when it is consistent with the order record: the variant the customer says they ordered is the recorded one
  and the variant they say they received is a different, stated one. If the customer says they ordered something other
  than the record shows, or says they received exactly what the record shows, or gives no checkable detail → V3
  `HUMAN_REVIEW` (data conflict). (A pure refund wish on a wrong-item claim still goes to the refund flow.) When consistent:
  Remedy = exchange to the ordered variant (or refund). Supplier-dropshipped product → the supplier shipped it →
  `CREATE_SUPPLIER_TASK` (confirm what was sent, send the right one). Merchant warehouse product → `DIRECT_WORKFLOW` if the
  ordered variant is in stock, `CREATE_SUPPLIER_TASK` if out of stock and the supplier restocks on request, else `HUMAN_REVIEW`.
- **C2 customer ordered wrong** (D3): after rules V0–V7, always `DIRECT_WORKFLOW` (return/exchange policy), never a supplier task.
- **C3 changed mind** counts as CUSTOMER_ORDERED_WRONG.
- **C4 SEND_PART** always needs exactly one part number (written by the customer). The broken-component case (DEFECT + SEND_PART)
  follows the DEFECT warranty table, not the parts-sales table, once the part number is known.
- **C5 hedged order that verifies** (exists, belongs to this customer, contains the product): treat like a normal order reference.
- **C6 safety by meaning**: a hazard word that is clearly negated ("no smoke, it just doesn't heat") does not by itself make
  safety POSSIBLE. (A system may still escalate on the word; that is a safe-direction system error, not the label.)
- **C7** an order with ≥2 units of the product, where the message is about one component but asks to exchange "it" → clarify which.
- **C8** a part number whose prefix belongs to another product than the one in the order → `HUMAN_REVIEW`.

## 7. Safety (only escalates)

`safety` is the most severe of:
- **S1 hazard words** with real meaning: fire, smoke, sparks, burnt / burnt smell, melted, electric shock, gas leak / smell,
  injury; quemó / quemado, humo, chispas; durchgebrannt, verbrannt, Rauch, Funken, Stromschlag, Gasgeruch; 燒壞, 燒焦, 冒煙, 火花,
  觸電, 漏氣, 瓦斯味; 焼けた, 焦げ, 煙, 発火, 感電, ガス漏れ → `EXPLICIT`.
- **S3 gas appliance** (catalog hazard class `GAS_APPLIANCE`, e.g. the camping gas stove): **any** DEFECT, PART_NEED or MISSING_ITEM
  (valve, knob, ignition, hose…; no leak needs to be mentioned) → `POSSIBLE` (D6).
- **S4 mains electric** (hazard class `MAINS_ELECTRIC`, e.g. kettle, desk lamp): DEFECT/PART_NEED where the fault is burning,
  scorching, melting, abnormal heat, sparks, water inside the power part, **or** the part is the power base / cable / plug /
  battery → `POSSIBLE` (D5). "Doesn't heat", "doesn't switch on", "flickers", "lid broke", "leaks from the spout" → no.

- ★ **S5 electrical (v3.1)**, any product: burnt / melted / hot-plastic smell; a power base / electrical base fault
  (e.g. the kettle base no longer powers it, loose base contacts, part KL-170-BASE); a blown fuse / tripped breaker /
  `Sicherung` / `fusible` / 保險絲 / 跳電 / ヒューズ (also `fuseが飛んで`) → `POSSIBLE` at least.
- ★ **S3 gas (v3.1)**: a gas-appliance problem of any kind (valve, knob, ignition, hose…) is `POSSIBLE` even when the
  customer only asks for a refund → V1 HUMAN (refund wish kept for the human).
- A desk-lamp **stand** base that is loose/wobbly is not a power base.

## 8. Order references

- Valid format: `TO-` + 4–6 digits (case/width/space variants like `to 50101`, `ＴＯ－５０１０１` are the same format).
  ★ Any Unicode hyphen or dash variant (non-breaking hyphen U+2011, en dash, minus sign, full-width hyphen) is the same `-`.
- **Malformed**: an order-like code that is not `TO-#####` (e.g. `WO-40005`, `T0-40005` with a zero, `#A12345`, `TO-400005`
  that does not exist) → never corrected, never guessed.
- **Hedged**: "I think it's…", "creo que…", "glaube…", "だと思います", "可能是…？".
- The MOCK records give you, for each order reference that appears, whether it exists, whose it is, what it contains,
  how many days ago it was bought and its logistics status. Use them; do not assume anything else.

## 9. Decision table for `required_action` (first match wins; safety first)

| Rule | Condition | required_action |
|---|---|---|
| V0 | instructions aimed at the system / prompt injection | HUMAN_REVIEW |
| V1 | ★ safety POSSIBLE or EXPLICIT (section 7, incl. S5) — safety takes precedence over refund and every other flow — even if the customer only wants a refund (**D2**; the refund wish is kept for the human) | HUMAN_REVIEW |
| V3 | ★ data conflict (checked BEFORE multi-item handling): any described product that is not in the cited order; the customer's claim about item / colour / size / variant conflicts with the order record (C1 v3.1); the cited order (customer **not** unsure) belongs to another customer, or does not contain the product; carrier shows LOST / IN_TRANSIT / not delivered but the customer describes using the item; the customer says the size/colour they have differs from the order (except C1) | HUMAN_REVIEW |
| V4 | the order reference is malformed, or hedged **and** fails verification — for **every** speech act, including refunds and questions (**D8**) | CLARIFY_WITH_CUSTOMER (ask for the order number) |
| V4b | ★ intent revision: the customer changes their mind inside the message → use the LAST explicit intent; if the revision leaves them undecided or is ambiguous → CLARIFY | (continue with the last intent) / CLARIFY |
| V6 | speech_act QUESTION and every goal is INFORMATION (or there are none) | HUMAN_REVIEW (support answers; no task) |
| V6b | ★ speech_act COMPLAINT_ONLY (a problem with no explicit remedy request and no question) → never an action or task | CLARIFY_WITH_CUSTOMER (what would you like?) |
| V7 | mixed: ≥2 actionable items (issue ≠ NO_ISSUE with a non-INFORMATION goal, or issue ≠ NO_ISSUE with no goal), **or** one item whose action goals span ≥2 families (e.g. repair **or refund**) | CLARIFY_WITH_CUSTOMER (which item first / which outcome) (**D13**) |
| V8 | the only action family is REFUND | DIRECT_WORKFLOW (existing refund flow, unchanged) |
| V9 | no goals: issue ≠ NO_ISSUE → CLARIFY (what would you like?); issue NO_ISSUE (or OTHER) → HUMAN | CLARIFY / HUMAN |
| V10 | issue UNCLEAR + action goal → CLARIFY (describe the problem); NO_ISSUE + action goal → HUMAN; CUSTOMER_ORDERED_WRONG → DIRECT_WORKFLOW (C2) | CLARIFY / HUMAN / DIRECT |
| V11 | slots: no order reference at all (none written, none linked) or order not found → CLARIFY; EXCHANGE without a stated target size/colour, or target not valid for the product, or equal to the ordered one → CLARIFY; SEND_PART without exactly one part number → CLARIFY; C7 → CLARIFY; part number of another product → HUMAN; ≥2 different order numbers → HUMAN | CLARIFY / HUMAN |
| V12 | responsibility table (section 10) | DIRECT_WORKFLOW / CREATE_SUPPLIER_TASK / HUMAN_REVIEW |

(V2 "evidence invalid" and V5 "availability-question cross-check" are system safeguards, not labelling rules.)

## 10. Responsibility table (V12) — MOCK data, given per case

Return window: 30 days from purchase, if the product is returnable.

| Family | Rule |
|---|---|
| EXCHANGE (SIZE_MISMATCH / WRONG variant) | product not returnable → DIRECT (policy says no); SIZE_MISMATCH older than 30 days → DIRECT (policy decides); merchant-warehouse product: target variant in stock → DIRECT; out of stock and supplier restocks on request → **TASK**; no inventory record or no restock → HUMAN. Supplier-dropshipped product: supplier confirms stock → **TASK**. WRONG_ITEM_OR_VARIANT: see C1 |
| FULFILMENT (RESHIP of MISSING_ITEM) | carrier IN_TRANSIT → DIRECT (share tracking); DELIVERED in full → HUMAN (claim conflicts with data); LOST or DELIVERED_PARTIAL: dropshipped + supplier reships → **TASK**; merchant warehouse with stock → DIRECT; otherwise HUMAN; no logistics record → HUMAN |
| WARRANTY_REMEDY on DEFECT (REPAIR / REPLACE_SAME / SEND_PART of a broken component) | ≤30 days and returnable → DIRECT (our return policy); supplier warranty and within its days → **TASK**; merchant warranty within its days → DIRECT; otherwise HUMAN |
| SEND_PART on PART_NEED | part known and in stock → DIRECT; known, 0 in stock, supplier supplies parts → **TASK**; known, 0 stock, supplier does not → HUMAN; unknown part number with the product's prefix and supplier answers compatibility → **TASK**; otherwise HUMAN |

A supplier task is a **suggested internal draft** that a human confirms; nothing is ever sent to a supplier.


## 11. ★ v3.1 summary (from the user's held-out v2 spot-check and the v2 error analysis)
1. Order-data conflict → HUMAN_REVIEW with a reason (V3), before multi-item handling. "You sent the wrong one" is never
   accepted on the customer's word alone (C1 v3.1).
2. Buyer error ("I ordered the wrong size/colour by mistake", "changed my mind") = CUSTOMER_ORDERED_WRONG → DIRECT
   (return policy), never the supplier. Seller error = WRONG_ITEM_OR_VARIANT, eligible only when consistent with the record.
3. Safety first, over refund and every other flow: S5 electrical (burnt/melted plastic smell, power base fault, fuse),
   S3 gas (any problem incl. valve + refund).
4. Intent revision → last explicit intent; ambiguous → CLARIFY. Complaint only (no explicit remedy) → CLARIFY, never a task.

## 12. v3.2 SAFETY GATE (supersedes earlier rules wherever they conflict). Evaluated right after the order/product is confirmed and BEFORE every other rule except injection (V0).

Catalogue safety classes (MOCK, `safety_class` per SKU): BREW-KETTLE = MAINS_HEATING, DESK-LAMP = MAINS_ELECTRIC, CAMP-STOVE = GAS; Trail Runner, City jacket, Daypack, socks = NONE.

- **SG-1 (gated class + malfunction):** if the product concerned is MAINS_HEATING, MAINS_ELECTRIC or GAS and the customer reports ANY malfunction or fault (defect, does not work / heat / switch on, flickers, cuts out, a functional part broken or needing replacement incl. part requests for that product), the label is **HUMAN_REVIEW (safety review)**. Wording does not matter: no smell/smoke/spark is needed. A refund wish NEVER overrides it (gas valve + refund = HUMAN). No supplier task, no refund flow. Complaint-only messages about a gated product's malfunction are also HUMAN.
- **SG-2 (unmappable product + malfunction):** if a malfunction is reported but the product cannot be identified from the order or catalogue (no order and no recognisable product, or a product the shop does not sell), label **HUMAN_REVIEW (verification)**.
- **Scope:** non-malfunction flows on gated products proceed normally (wrong colour sent, whole item lost/missing → reship, change-of-mind refund, availability/info questions). Low-risk-class (NONE) malfunctions proceed normally (shoe sole → warranty task, backpack zip → merchant warranty, refund flows, complaint-only → clarify).
- **Typos:** a variant written with a typo ("whte") that conflicts with the record, or is only fuzzily recognisable, → HUMAN_REVIEW (never auto).
