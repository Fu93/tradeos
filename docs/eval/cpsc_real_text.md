# Safety Gate on real consumer hazard reports (CPSC SaferProducts.gov): a recall check

**What this is:** 100 real, human-written incident narratives that consumers sent to the U.S. Consumer Product Safety
Commission, run through the Safety Gate code on `main`. No app logic was changed, and the keyword patterns were **not**
tuned on this set.
**What this is not:** merchant support traffic, a benign or false-positive measurement, or a rate to promise.

## Source and licence

* File: `SPDB.zip` → `IncidentReports.csv` (65,650 published reports), the "Download all recalls and unsafe product
  reports" export on <https://www.saferproducts.gov/PublicSearch>.
* saferproducts.gov returns HTTP 403 (CDN block) to our build machine, and its OData API needs a registered key, which we did
  not request. So the copy used is the **Internet Archive capture of that official file taken 2026-02-24**:
  <https://web.archive.org/web/20260224175618id_/https://www.saferproducts.gov/SPDB.zip>
  (sha256 `4d72f3fdfdf0db6e6e9691cdaa001e6d861807995b623db9adb9a9f7f0a68352`). Reports published after that date are not included.
* Terms: "Information publicly posted on Saferproducts.gov is considered public information and may be distributed or
  copied. This does not include personally identifiable information"
  ([SaferProducts.gov terms, section 3](https://www.saferproducts.gov/Business/Acknowledge)). CPSC publishes the
  reports without submitter or victim contact details and with `[REDACTED]` marks; we copy only the report number, a
  120-character product description, the product category, the severity field and the narrative.
* CPSC's own disclaimer applies: CPSC does not guarantee the accuracy, completeness or adequacy of the database,
  particularly for information submitted by people outside CPSC.

## Sample (fixed before any gate was run)

`scripts/cpsc_build_sample.py`: consumer submitters only; narrative 60–500 characters (500 = the app's
`FREE_TEXT_MAX_CHARS` default, so every row would fit in the demo's message box); deaths and "Unspecified" excluded;
duplicates removed; then a seeded random draw (seed 20261019) of **35 injury reports, 35 "Incident, No Injury" and 30
"No Incident, No Injury"**. Product and category come from the report and are passed to the gate as the product.

## Labels and rubric

The labels were written by hand **before** either layer was run on the set. They were committed on their own
(`docs/eval/cpsc_real_text_sample.jsonl`, first commit of this branch) before the results file existed. The rubric is
the one used for the 165-row set (`scripts/safety_eval_data.py`):

* **1 (escalate):** the text reports or credibly suggests physical harm or a hazard (fire, smoke, overheating, melting,
  sparks, shock, gas or chemical leak, burn, cut, choking or small parts, entrapment, tip-over or collapse, a fall
  caused by the product, allergic or chemical reaction, toxic material), **or** any fault on a mains-powered,
  electric-heating, gas or battery product.
* **0 (do not escalate):** an ordinary service message with nothing to escalate.

Result: **all 100 rows are label 1**. This is expected. CPSC publishes only reports that describe a harm or a risk of
harm (16 CFR 1102.10(d)), so the database has no benign controls. Each row also has a `label_basis`: `harm_reported`
29, `hazard_no_harm` 63, `energised_product_fault_rule` 8 (a fridge that stops cooling, a washer that "walks": rubric
rule, no hazard words). **10 rows are marked borderline**, for example a trampoline net torn loose, bed-frame hardware
falling off, or a toy that tested positive for lead. One labeller (the same author as the gate) did all of this. A
40-row blind relabel by a second person has been prepared, and its result is not in yet.

## Results (one run, 19 Oct 2026)

`python scripts/eval_cpsc_real_text.py --base-url https://integrate.api.nvidia.com/v1 --model openai/gpt-oss-20b --key-env NVIDIA_API_KEY`
Per-row output: `cpsc_real_text_results.json`. The AI layer used the same model id as the app default, served by NVIDIA,
not Groq (the hosted demo's Groq free-tier quota was not used). Temperature 0, 0 AI errors. The keyword layer got no
intent-LLM reading (`llm_reason=None`), as in the 165-row eval; on the live path a `DEFECTIVE`-type reading can add a
gated-product fault flag, so the keyword miss rate here may be slightly higher than live.

| Layer | Miss (label 1, not escalated) | 95 % Wilson interval | Excluding the 10 borderline rows |
|---|---|---|---|
| **Keyword only (what the hosted demo runs)** | **34 / 100** | 25.5–43.7 % | 25 / 90 |
| AI alone (diagnostic) | 4 / 100 | 1.6–9.8 % | 3 / 90 |
| Keyword + AI (escalate-only OR; opt-in, off on the demo) | 3 / 100 | 1.0–8.5 % | 2 / 90 |

*Note (2026-10-25):* the keyword rows above, and `cpsc_real_text_results.json`, are the frozen run. After the plural-category
fix to the product class (`docs/safety-gate.md`), the offline keyword layer flags one more row (id 33, a gasoline can: category
"Fuel, Lighters and Fireworks" -> `GAS`), i.e. 33 / 100 missed. The frozen file is not rescored; `tests/test_cpsc_eval_data.py` pins that difference.

Keyword misses by stratum: injury 12/35, incident without injury 10/35, no incident 12/30. By label basis:
`harm_reported` 8/29, `hazard_no_harm` 19/63, `energised_product_fault_rule` 7/8. 29 of the 34 keyword misses are on
products the gate's class rule does not treat as risky (`NONE` class: furniture, baby gear, bicycles, glassware, ...).

What the keyword layer missed (real wording, for example):
* Harm in words the patterns do not have: "the mop head flew off releasing a large amount of steam which **scolded** my
  leg" (misspelt scald), "spilling hot coffee on my wife", "one of the four straps broke and he fell forward and hit his
  head", "I got a cut using the Onion chopper".
* Structural failures without harm words: a stroller cross-bar broke, a chair base separated from the weld, a bicycle
  steer-tube crack, an infant's leg entrapped in crib slats.
* Chemical or toxic material: fibreglass from a mattress, VOC off-gassing, lidocaine cream in a non-childproof tube, lead in a toy.
* Appliance faults with no hazard words (fridges that stop cooling, a washer that "walks", oven or dryer door glass that
  shattered). Some of these products are not recognised as mains-powered by the class rule from CPSC's product wording, so the
  "any fault on a mains product" rule does not apply to them.

The three rows **both layers** missed: a desk chair that broke so that a child fell, bed-frame hardware falling off
(borderline), and a child-safety cabinet lock that broke when a child pulled the drawer.

## How to read this honestly

* **Recall only.** There are no label-0 rows, so a layer that escalated everything would score 0 misses here. The AI
  layer's 3–4 % must be read together with the 165-row set, where AI alone flagged 0/82 benign rows (with the prompt
  overlap caveat in `docs/safety-gate.md`). **False positives on real text are not measured.** A clean, licence-clear
  source of real benign customer messages was not found: CPSC has none by design, and the CFPB complaint API refused
  our requests (HTTP 403) and is a different domain anyway.
* **Regulator reports, not support tickets.** People writing to a safety regulator describe the hazard on purpose, at
  length, in English. A customer asking a shop for a refund may mention it in passing, in another language, or not at
  all. This set says nothing about other languages.
* **Keyword-only is what the hosted demo runs.** About one in three real hazard reports in this sample would not be routed
  to safety review by the keyword layer alone. They are not auto-refunded: they fall back to the normal path (policy
  plus a human approval for any money), but nobody is told to look at the hazard. This is the strongest evidence so far
  for turning on the second layer, and also for keeping the human approval step.
* Small sample: one row is 1 percentage point, and the intervals above are wide. One run, one model, one host.
* **No tuning.** The misses listed above are tempting to fix with new keywords. Doing it on this set would turn it into
  training data and void the number, so the patterns were left unchanged. Any future pattern change must be measured on a fresh sample.
