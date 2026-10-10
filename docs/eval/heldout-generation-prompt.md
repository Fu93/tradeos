# Held-out set: generation prompt (blind to the routing rules)

This prompt is the ONLY input the generator model saw. It describes the business in plain words and asks for
realistic customer messages. It deliberately contains nothing about the routing rules, gates, thresholds,
supplier responsibilities, stock levels, logistics states or the code. Used by `scripts/generate_heldout.py`.

---

SYSTEM:
You write realistic test data for a customer-service team. Output only JSON.

USER (one call per batch; {BATCH_BRIEF} and {N} change per batch):

A small cross-border online shop sells these products (SKU in brackets):
- Trail Runner sneakers [TRAIL-RUNNER-42], EU sizes 38–46
- City rain jacket [CITY-JACKET], sizes S, M, L, XL
- Daypack 30L backpack [BACKPACK-30L], colours black, green, navy
- Electric kettle 1.7 L [BREW-KETTLE]; spare parts sold for it: limescale filter KL-170-FLT, lid KL-170-LID, power base KL-170-BASE
- LED desk lamp [DESK-LAMP], white or black; spare parts: 5 W LED module DL-LED-5W, desk clamp DL-CLAMP-M
- Camping gas stove [CAMP-STOVE]; spare part: gas valve CS-VALVE-2
- Merino socks [SALE-SOCKS], sizes S/M/L, sold as final sale

Some real customer orders (order number, customer e-mail, what they bought, how long ago):
TO-10421 ana@example.test, Trail Runner size 42, 10 days ago
TO-10412 ben@example.test, Trail Runner size 41, 12 days ago
TO-20031 chen@example.test, City rain jacket M, 8 days ago
TO-30077 eva@example.test, Daypack black, 5 days ago
TO-40005 felix@example.test, Merino socks M, 6 days ago
TO-40011 ola@example.test, desk lamp white, 9 days ago
TO-50101 hana@example.test, two desk lamps (white), 7 days ago
TO-50110 ivan@example.test, electric kettle, 9 days ago
TO-50120 jon@example.test, Trail Runner size 44, 3 days ago
TO-50140 lea@example.test, electric kettle + black desk lamp, 8 days ago
TO-60201 pia@example.test, electric kettle, 10 days ago
TO-60202 quinn@example.test, electric kettle, 4 months ago
TO-60204 sara@example.test, desk lamp white, 3 months ago
TO-60206 uma@example.test, camping gas stove, 20 days ago
TO-60207 vic@example.test, Trail Runner size 43, 3 months ago
TO-70301 wen@example.test, electric kettle, 7 months ago
TO-70302 xia@example.test, desk lamp white, 5 months ago
TO-70303 yan@example.test, camping gas stove, 3 months ago

Write {N} different short messages (1–3 sentences) that customers of this shop might send by e-mail or chat.
Brief for this batch: {BATCH_BRIEF}
Use these languages, spread evenly: English, Traditional Chinese (Taiwan), Spanish, German, Japanese.
Write like real customers: casual, sometimes typos, sometimes without the order number, sometimes with the wrong
or a slightly different order number. Each message is written by one of the customers above (or by someone not
in the list). Do not explain anything inside the message.

Return a JSON object {"messages": [ ... ]} where each item has:
  "message": the customer's text,
  "language": one of en, zh-Hant, es, de, ja,
  "customer": the e-mail of the writer (or "unknown@example.test"),
  "writer_intent": one short English sentence saying what this customer really wants.

Batch briefs (6 batches × 10 messages):
1. Messages that mention a product problem word (broken, size, missing, part, …) but where the customer does NOT
   actually want anything done about an order — e.g. a negation ("not broken, just asking"), a hypothetical,
   praise, or a question before buying.
2. Pure questions / inquiries: availability of spare parts, sizes, shipping times, policies, product use.
3. Customers who only want their money back (refund), with various reasons (defect, wrong size, late, changed mind),
   some angry, some polite.
4. Messages mixing two or more wishes or two problems at once, or where the customer is undecided
   ("exchange or refund, I don't know", "the lamp is broken and the kettle never came").
5. Messages with too little information to act on: no order number, no size, no part number, vague
   ("it doesn't work", "something is wrong"), or an order number that is slightly off.
6. Ordinary clear service requests: size/colour exchange, missing item to be sent again, broken product to be
   repaired or replaced, ordering a specific spare part for an item they own.
