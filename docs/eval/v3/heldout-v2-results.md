# Held-out v2 results (single final run)

Labels: `heldout-v2-labels.json` — status **LLM-generated, dual-LLM-labelled, author-adjudicated, pending human review**. Composition: {"n": 300, "by_required_action": {"CREATE_SUPPLIER_TASK": 106, "HUMAN_REVIEW": 85, "DIRECT_WORKFLOW": 48, "CLARIFY_WITH_CUSTOMER": 61}, "non_supplier": 194, "by_lang": {"zh-Hant": 67, "es": 62, "de": 59, "ja": 57, "en": 55}, "by_generator": {"z-ai/glm-5.3": 108, "nvidia/nemotron-3-super-120b-a12b": 98, "meta/muse-glimmer-30b": 94}, "by_source": {"all labels agree (judge B + design + C + A)": 57, "all labels agree (judge B + design + C)": 29, "all labels agree (judge B + design + A)": 14, "author-adjudicated": 21, "all labels agree (judge B + design)": 179}, "pairs": 84}

v3 build: supplier-routing-rules/3.0.0 (taxonomy v3 experiment) · extractor `openai/gpt-oss-20b` via NVIDIA · k=5 (extra samples temp 0.6) · tag `final` (run once). Baseline: rules 0.2.0, same model/provider, run once.

### v3, agreement gate k1 (pre-registered primary)

- lenient correct: **282/300** (94.0%, Wilson 95% CI 90.7–96.2); strict (= required action): 274/300 (CI 87.6–94.0)
- supplier tasks: predicted 108, correct 103 of 106 required → precision 0.954, recall 0.972
- false triggers (task where task is not acceptable): **5** of 194 non-supplier (V117, V138, V135, V137, V134)
- latency per message: median 46.5 s, p90 130.6 s

### v3, agreement gate k3 (trade-off)

- lenient correct: **277/300** (92.3%, Wilson 95% CI 88.8–94.8); strict (= required action): 268/300 (CI 85.3–92.3)
- supplier tasks: predicted 99, correct 97 of 106 required → precision 0.98, recall 0.915
- false triggers (task where task is not acceptable): **2** of 194 non-supplier (V117, V137)
- latency per message: median 46.5 s, p90 130.6 s

### v3, agreement gate k5 (trade-off)

- lenient correct: **271/300** (90.3%, Wilson 95% CI 86.5–93.2); strict (= required action): 261/300 (CI 82.7–90.3)
- supplier tasks: predicted 90, correct 89 of 106 required → precision 0.989, recall 0.84
- false triggers (task where task is not acceptable): **1** of 194 non-supplier (V137)
- latency per message: median 46.5 s, p90 130.6 s

### rules 0.2.0 baseline (same set)

- lenient correct: **206/300** (68.7%, Wilson 95% CI 63.2–73.7); strict (= required action): 194/300 (CI 59.1–69.9)
- supplier tasks: predicted 63, correct 55 of 106 required → precision 0.873, recall 0.519
- false triggers (task where task is not acceptable): **8** of 194 non-supplier (V113, V116, V134, V135, V138, V137, MP32B, MP33B)
- latency per message: median 9.8 s, p90 20.7 s

## Breakthrough bar

Bar: ≥36 auto/suggested supplier tasks with 0 errors and 0 false triggers on ≥183 non-supplier cases.

- k1: 103 correct tasks / 108 predicted, false triggers 5 on 194 → **NOT met**
- k3: 97 correct tasks / 99 predicted, false triggers 2 on 194 → **NOT met**
- k5: 89 correct tasks / 90 predicted, false triggers 1 on 194 → **NOT met**

Safety cells (gas stove, power base, mains burn, refund+safety, safety pairs) labelled HUMAN: v3 routed **19/21** to a human automatically (baseline 15/21); V1 fired on 24 messages in total (23 labelled HUMAN).

## Per-error list (v3, k1)

| id | lang | kind | predicted | required (acceptable) | rule | v3 reason |
|---|---|---|---|---|---|---|
| V017 | zh-Hant | exch_jacket_L | CLARIFY_WITH_CUSTOMER | CREATE_SUPPLIER_TASK (CREATE_SUPPLIER_TASK) | V11 | Exchange requested but no valid target size stated: ask (never guessed). |
| V053 | en | part_kettle_lid | CLARIFY_WITH_CUSTOMER | CREATE_SUPPLIER_TASK (CREATE_SUPPLIER_TASK) | V11 | Part requested without exactly one part number: ask (part models are never guessed). |
| V091 | es | refund_only | HUMAN_REVIEW | DIRECT_WORKFLOW (DIRECT_WORKFLOW) | V10 | An action is requested but no problem is described: a human decides. |
| V096 | es | refund_only | HUMAN_REVIEW | DIRECT_WORKFLOW (DIRECT_WORKFLOW) | V10 | An action is requested but no problem is described: a human decides. |
| V104 | de | refund_hedged_bad | DIRECT_WORKFLOW | CLARIFY_WITH_CUSTOMER (CLARIFY_WITH_CUSTOMER) | V8 | Refund wish: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. |
| V128 | ja | backpack_warranty | DIRECT_WORKFLOW | HUMAN_REVIEW (HUMAN_REVIEW) | V12 | Inside our own 365-day warranty: merchant process. |
| V117 | ja | mains_burn | CREATE_SUPPLIER_TASK | HUMAN_REVIEW (HUMAN_REVIEW) | V12 | Outside our 30-day window, inside the 730-day supplier warranty: Lumina Lighting (MOCK supplier) decides. |
| V138 | de | customer_ordered_wrong | CREATE_SUPPLIER_TASK | DIRECT_WORKFLOW (DIRECT_WORKFLOW) | V12 | Drop-shipped by Stride Footwear Co. (MOCK supplier): the supplier confirms stock of 42. |
| V135 | en | customer_ordered_wrong | CREATE_SUPPLIER_TASK | DIRECT_WORKFLOW (DIRECT_WORKFLOW) | V12 | Drop-shipped by Stride Footwear Co. (MOCK supplier): the supplier confirms stock of 42 and what was shipped (C1). |
| V137 | es | customer_ordered_wrong | CREATE_SUPPLIER_TASK | DIRECT_WORKFLOW (DIRECT_WORKFLOW/HUMAN_REVIEW) | V12 | Drop-shipped by Lumina Lighting (MOCK supplier): the supplier confirms stock of white and what was shipped (C1). |
| V140 | es | multi_item | CLARIFY_WITH_CUSTOMER | HUMAN_REVIEW (HUMAN_REVIEW) | V7 | 2 items need separate handling (D13): ask which first. |
| V141 | de | multi_item | CLARIFY_WITH_CUSTOMER | HUMAN_REVIEW (HUMAN_REVIEW) | V7 | 2 items need separate handling (D13): ask which first. |
| V142 | ja | multi_item | CLARIFY_WITH_CUSTOMER | HUMAN_REVIEW (HUMAN_REVIEW) | V7 | 2 items need separate handling (D13): ask which first. |
| V146 | de | multi_item | CLARIFY_WITH_CUSTOMER | HUMAN_REVIEW (HUMAN_REVIEW) | V7 | 2 items need separate handling (D13): ask which first. |
| V134 | ja | customer_ordered_wrong | CREATE_SUPPLIER_TASK | DIRECT_WORKFLOW (DIRECT_WORKFLOW) | V12 | Drop-shipped by Stride Footwear Co. (MOCK supplier): the supplier confirms stock of 42. |
| V200 | es | part_in_stock | CLARIFY_WITH_CUSTOMER | DIRECT_WORKFLOW (DIRECT_WORKFLOW) | V11 | Part requested without exactly one part number: ask (part models are never guessed). |
| MP23B | es | pair:DIR_safety_catalog | DIRECT_WORKFLOW | HUMAN_REVIEW (HUMAN_REVIEW) | V8 | Refund wish: the existing refund policy flow (policy checks, human approval, PayPal) owns it. Never a supplier task. |
| MP63A | es | pair:DIR_part_need_vs_info | HUMAN_REVIEW | CREATE_SUPPLIER_TASK (CREATE_SUPPLIER_TASK) | V9 | No problem and no requested outcome: standard support reads it. |

## Per-error list (baseline 0.2.0)

| id | predicted | required | reason |
|---|---|---|---|
| V004 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V007 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V008 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V010 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V011 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V009 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V012 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V014 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V013 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V017 | CLARIFY_WITH_CUSTOMER | CREATE_SUPPLIER_TASK |  |
| V031 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V033 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V040 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V042 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V043 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V045 | CLARIFY_WITH_CUSTOMER | CREATE_SUPPLIER_TASK |  |
| V044 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V049 | CLARIFY_WITH_CUSTOMER | CREATE_SUPPLIER_TASK |  |
| V047 | CLARIFY_WITH_CUSTOMER | CREATE_SUPPLIER_TASK |  |
| V051 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V052 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V054 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V053 | CLARIFY_WITH_CUSTOMER | CREATE_SUPPLIER_TASK |  |
| V055 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V050 | CLARIFY_WITH_CUSTOMER | CREATE_SUPPLIER_TASK |  |
| V058 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V056 | CLARIFY_WITH_CUSTOMER | CREATE_SUPPLIER_TASK |  |
| V061 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V064 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V063 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V066 | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| V065 | CLARIFY_WITH_CUSTOMER | CREATE_SUPPLIER_TASK |  |
| V046 | CLARIFY_WITH_CUSTOMER | CREATE_SUPPLIER_TASK |  |
| V097 | DIRECT_WORKFLOW | CLARIFY_WITH_CUSTOMER |  |
| V100 | DIRECT_WORKFLOW | CLARIFY_WITH_CUSTOMER |  |
| V099 | HUMAN_REVIEW | CLARIFY_WITH_CUSTOMER |  |
| V101 | HUMAN_REVIEW | CLARIFY_WITH_CUSTOMER |  |
| V102 | DIRECT_WORKFLOW | CLARIFY_WITH_CUSTOMER |  |
| V098 | HUMAN_REVIEW | CLARIFY_WITH_CUSTOMER |  |
| V103 | DIRECT_WORKFLOW | CLARIFY_WITH_CUSTOMER |  |
| V104 | HUMAN_REVIEW | CLARIFY_WITH_CUSTOMER |  |
| V108 | DIRECT_WORKFLOW | HUMAN_REVIEW |  |
| V105 | DIRECT_WORKFLOW | CLARIFY_WITH_CUSTOMER |  |
| V113 | CREATE_SUPPLIER_TASK | HUMAN_REVIEW |  |
| V116 | CREATE_SUPPLIER_TASK | HUMAN_REVIEW |  |
| V122 | HUMAN_REVIEW | DIRECT_WORKFLOW |  |
| V123 | HUMAN_REVIEW | DIRECT_WORKFLOW |  |
| V125 | HUMAN_REVIEW | DIRECT_WORKFLOW |  |
| V127 | HUMAN_REVIEW | DIRECT_WORKFLOW |  |
| V124 | HUMAN_REVIEW | DIRECT_WORKFLOW |  |
| V134 | CREATE_SUPPLIER_TASK | DIRECT_WORKFLOW |  |
| V135 | CREATE_SUPPLIER_TASK | DIRECT_WORKFLOW |  |
| V138 | CREATE_SUPPLIER_TASK | DIRECT_WORKFLOW |  |
| V136 | HUMAN_REVIEW | DIRECT_WORKFLOW |  |
| V137 | CREATE_SUPPLIER_TASK | DIRECT_WORKFLOW |  |
| V139 | HUMAN_REVIEW | DIRECT_WORKFLOW |  |
| V141 | CLARIFY_WITH_CUSTOMER | HUMAN_REVIEW |  |
| V142 | CLARIFY_WITH_CUSTOMER | HUMAN_REVIEW |  |
| V144 | CLARIFY_WITH_CUSTOMER | HUMAN_REVIEW |  |
| V140 | CLARIFY_WITH_CUSTOMER | HUMAN_REVIEW |  |
| V143 | CLARIFY_WITH_CUSTOMER | HUMAN_REVIEW |  |
| V146 | CLARIFY_WITH_CUSTOMER | HUMAN_REVIEW |  |
| V147 | HUMAN_REVIEW | CLARIFY_WITH_CUSTOMER |  |
| V173 | HUMAN_REVIEW | CLARIFY_WITH_CUSTOMER |  |
| V174 | HUMAN_REVIEW | CLARIFY_WITH_CUSTOMER |  |
| V200 | CLARIFY_WITH_CUSTOMER | DIRECT_WORKFLOW |  |
| V201 | HUMAN_REVIEW | DIRECT_WORKFLOW |  |
| V202 | HUMAN_REVIEW | DIRECT_WORKFLOW |  |
| V203 | CLARIFY_WITH_CUSTOMER | DIRECT_WORKFLOW |  |
| V145 | CLARIFY_WITH_CUSTOMER | HUMAN_REVIEW |  |
| V214 | HUMAN_REVIEW | DIRECT_WORKFLOW |  |
| MP01B | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| MP02B | CLARIFY_WITH_CUSTOMER | CREATE_SUPPLIER_TASK |  |
| MP04B | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| MP10A | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| MP13B | CLARIFY_WITH_CUSTOMER | CREATE_SUPPLIER_TASK |  |
| MP17A | CLARIFY_WITH_CUSTOMER | CREATE_SUPPLIER_TASK |  |
| MP22B | DIRECT_WORKFLOW | HUMAN_REVIEW |  |
| MP19A | CLARIFY_WITH_CUSTOMER | CREATE_SUPPLIER_TASK |  |
| MP20A | CLARIFY_WITH_CUSTOMER | CREATE_SUPPLIER_TASK |  |
| MP23B | DIRECT_WORKFLOW | HUMAN_REVIEW |  |
| MP25B | DIRECT_WORKFLOW | HUMAN_REVIEW |  |
| MP32A | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| MP32B | CREATE_SUPPLIER_TASK | DIRECT_WORKFLOW |  |
| MP33A | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| MP33B | CREATE_SUPPLIER_TASK | DIRECT_WORKFLOW |  |
| MP34B | HUMAN_REVIEW | DIRECT_WORKFLOW |  |
| MP15B | CLARIFY_WITH_CUSTOMER | CREATE_SUPPLIER_TASK |  |
| MP47B | HUMAN_REVIEW | CLARIFY_WITH_CUSTOMER |  |
| MP50B | HUMAN_REVIEW | CLARIFY_WITH_CUSTOMER |  |
| MP59A | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| MP58A | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| MP61A | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |
| MP63A | HUMAN_REVIEW | CREATE_SUPPLIER_TASK |  |

## v3 (k1) by language

zh-Hant: 66/67 · es: 55/62 · de: 55/59 · ja: 53/57 · en: 53/55

## Cost / usage

- v3 run: {'calls': 408, 'prompt_tokens': 512420, 'completion_tokens': 846624} · counted retries 21 · wall 3312.5 s
- baseline run: retries counted by transport; wall 1017.6 s
- Cost estimate uses Groq list price for gpt-oss-20b (production provider): $0.075 / 1M input, $0.30 / 1M output tokens.
- v3 tokens for 300 messages (incl. agreement samples): $0.2924 total ≈ $0.00097/message at Groq prices.

## Error analysis (v3, k1). Documented, NOT fixed (fixing it would be tuning on held-out v2)

- **Safety misses: 2**, both of which should have been V1 human.
  - V117 (JA, mains lamp): 「ベースに水が入ってしまい…fuseが飛んで」. S4 missed it: the `\bfuse\b` boundary fails
    before が, and JA "water in the base" is not in the lexicon. The model said safety NONE. It became a supplier task:
    a false trigger.
  - MP23B (ES): the gas-stove valve broke and the customer wants a refund. The S3 gas-appliance rule did not fire, so it
    went to the refund flow (DIRECT) instead of a human (D2: refund + safety → human).
- **False triggers: 5.** V117 (above), plus V134, V135, V138 and V137: "customer ordered wrong" messages ("I ordered the
  wrong size by mistake") were extracted as WRONG_ITEM_OR_VARIANT, so guide C1 sent the drop-shipped product to the
  supplier. V137 was an author-adjudicated judgement call. A deterministic, demote-only "by mistake / me equivoqué /
  aus Versehen / 間違えて" cross-check is the obvious next step, and it must be validated on a NEW set.
- **The agreement gate trades recall for precision:** k3 removes V134, V135 and V138 and costs 6 true tasks; k5 leaves only V137
  and costs 14 true tasks. No setting reaches 0 false triggers.
- **Other errors: 13.** The direction is mostly safe (human or clarify instead of an action):
  - 4 multi-item cells (V140–V142, V146): the products are not in the order, the label is V3 HUMAN, and v3 asked which
    item first.
  - 3 slot asks (V017, V053, V200): the size or part number was in the text but not extracted, so v3 asked.
  - 2 refund-only messages (V091, V096) went to HUMAN (V10 "no issue") instead of the refund flow.
  - MP63A: a part request went to HUMAN (no goal extracted).
  - Unsafe direction:
    - V104: the order number is written `TO‑10421` with a non-breaking hyphen (U+2011), which the code scanner does not
      recognise, so V4 never asked. It went to the refund flow, which still does its own order checks.
    - V128: the customer's colour/size description conflicts with the order, the conflict was not detected, and v3 went
      DIRECT.
    - MP23B (above).
