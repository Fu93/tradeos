# Mixed orders and partial refunds

An order can have several line items that need different outcomes (for example 3 returned, 1 exchanged). TradeOS
handles this per line, and only **code** ever computes money.

> Principles: AI understands, rules decide, humans approve, PayPal proves. Sandbox only. No autonomy: a mixed order is
> never auto-approved, whatever the autonomy settings say. The AI never computes or sets an amount.

## Evidence tiers (read this first)

| Tier | What it covers | Status |
|---|---|---|
| **A. Unit / property / integration tests (offline, mock PayPal)** | amount math, ledger, gate, idempotency, recovery, UI | Done. See "Tests". |
| **B. Local mock run of `scripts/sandbox_verify.py --mixed-only --allow-mock`** | the whole HTTP flow end to end against the mock | Done. Output is labelled `[MOCK - not live proof]`. |
| **C. Live PayPal Sandbox** | PayPal accepting `items[]` + breakdown for the card capture, and one real partial refund whose PayPal-reported amount equals the computed one, with a `PayPal-Debug-Id` | **Done for Case M** (one partial refund) and **Case M2** (two partial refunds on one capture): `python scripts/sandbox_verify.py <url> --mixed` / `--multi-batch-only`. Nothing else is live-proven. |
| **D. Not built / not covered** | see "Known limits" | Not covered |

The mock enforces what PayPal documents (zero-decimal currencies, currency match, item/tax breakdown sums, cumulative
refund cap), but a mock is only my reading of the docs. Do not treat Tier A/B as proof that PayPal behaves this way.

## Flow

1. Each line gets a **proposal** (`RETURN`, `EXCHANGE`, `REJECT`, `NEEDS_HUMAN`). In this PR the proposals for the demo
   case are **seeded** (`DEMO_PROPOSALS`); a per-line LLM extractor is not built. Only the keys `line_no`, `action`,
   `reason`, `qty` are read; any other key (for example `amount`) is dropped and listed as ignored.
2. **Rules** (`app/lineitems.py`) turn proposal + policy into a resolution per line: return becomes `REFUND`, exchange
   becomes `EXCHANGE` (supplier replacement, no refund), a rejected or policy-blocked line becomes `REJECT`, anything
   uncertain becomes `NEEDS_HUMAN`. Final-sale items, expired return windows, injection-looking text and unknown
   actions never become refunds.
3. Code builds one **batch** = one PayPal partial refund, with a fingerprint (`items_hash`) of case, items, quantities,
   amounts and attempt number.
4. The approval screen shows every line decision and the exact total, e.g.
   `Refund 3 items = 161.69 USD; exchange 1 item, no refund`. The Approve button posts the total and fingerprint it
   displays; if either differs from the stored batch (stale screen, forged form) the approval is refused.
5. The human approval is written to the per-case audit hash chain (proposal, approval, supplier mock note, PayPal call
   and result each get an entry). The money gate re-reads the chain: it needs a chained proposal **and** a chained
   human approval for this exact batch id, fingerprint, amount and currency, and the chain must verify, and the amount
   is recomputed from item prices and must equal the stored amount.
6. One `refund_capture` call with `amount`, `PayPal-Request-Id`, `custom_id` (batch id) and `note_to_payer`.
   The reply's amount must equal the computed amount; a mismatch goes to a human instead of "COMPLETED".
7. Unknown outcome (timeout, 5xx): the batch becomes `UNKNOWN`; the existing reconcile mechanism asks PayPal
   (GET capture/refund) and resends the **same** request id at most once. Startup resume and the verified webhook
   (`PAYMENT.CAPTURE.REFUNDED`, matched by **refund id**) also settle it.
   A webhook with an unknown refund id or a different amount changes nothing.

## Money rules (all integer minor units)

* **An unanswered partial refund is re-sent only while PayPal can replay it.** A batch whose refund call got no answer
  is recovered by re-sending the same `PayPal-Request-Id` (PayPal returns the refund it already made). PayPal documents
  no retention window for refund request ids (it documents 6 hours for Orders), so TradeOS re-sends only within 6 hours
  of the first call that carried the id, whether by a retry click, a webhook, a reconcile or startup. After that the
  batch stays UNKNOWN and the timeline says to check the capture's refunds in PayPal by hand: past the window, the
  same id could be taken as a new refund. (A single-item refund has no amount, so a late re-send of a refund PayPal
  already made is refused by PayPal as a second full refund: `CAPTURE_FULLY_REFUNDED`,
  [PayPal: Refund a payment](https://developer.paypal.com/checkout/refund-payment).)
* **A mixed order is never refunded as a whole.** The whole-case approve and the single-refund guard refuse any case
  whose scenario is `M`, whatever its decision says, and "Retry the policy check" after a PayPal read failure
  evaluates the order line by line again. Before 2026-10-24 that retry ran the single-item flow: with a refund
  reading, the whole capture (191.21 USD, the exchanged item included) became approvable
  (`tests/test_mixed_retry.py`).
* Amounts are `int` minor units, converted with exact `Decimal` parsing. Extra decimals are an error (never rounded
  silently), as are negatives, exponents, NaN, and a decimal point on JPY/HUF/TWD.
  Currency exponent: JPY, HUF, TWD = 0; the other PayPal-supported codes = 2 (PayPal's currency table).
* Refund of a line = `unit price x qty` + `that unit's own tax x qty` (+ shipping share, below). Tax is therefore
  proportional to the items refunded, using the per-unit tax recorded on the PayPal order.
* **Shipping policy** (`TRADEOS_SHIPPING_POLICY`; default `WITHDRAWAL_FULL`; unknown values fail closed to `NEVER`):

  | Policy | Shipping is refunded when... |
  |---|---|
  | `NEVER` | never (items + their tax only) |
  | `MERCHANT_ERROR` | a line is refunded for a merchant-error reason (damaged / wrong item / not as described) and its **last unit** is refunded |
  | **`WITHDRAWAL_FULL`** (default) | the `MERCHANT_ERROR` case, **or** this refund completes a **whole-order return**: every unit of every line is refunded (across batches), nothing exchanged, rejected or still open. Then the order's whole shipping is released. A partial return of an order refunds no delivery. |

  The order's shipping is split over lines with the largest-remainder method so the shares always sum to the shipping
  total; a share is released once; on the batch that completes a whole-order return, the shares of lines refunded in
  earlier batches that never got one are added to that batch. Shipping refunded in total never exceeds shipping charged.
  The demo order (3 returned, 1 exchanged) is **not** a whole-order return, so only the merchant-error lines' shipping
  is refunded; its amounts are identical under `MERCHANT_ERROR` and `WITHDRAWAL_FULL`.

  **Why this default (research, 2026-10-18):**
  * UK Consumer Contracts Regulations 2013 reg 34(2)-(3): on cancellation the trader must reimburse the delivery
    payment, except the part above the least expensive common standard delivery the consumer chose; the BIS guidance
    para 15 adds the return postage need not be refunded unless the trader agreed to bear it.
    <https://www.legislation.gov.uk/uksi/2013/3134/regulation/34> and
    <https://assets.publishing.service.gov.uk/media/5a817b92ed915d74e33fe73a/bis-13-1368-consumer-contracts-information-cancellation-and-additional-payments-regulations-guidance.pdf>
  * EU Directive 2011/83/EU art 13(1)-(2): same rule (all payments "including, if applicable, the costs of delivery";
    not the supplementary cost of a non-standard delivery). <https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX%3A02011L0083-20220528>
    Your Europe summary: <https://europa.eu/youreurope/business/selling-in-eu/selling-goods-services/ecommerce-distance-selling/index_en.htm>
  * Partial return: the legal text speaks of withdrawing from "the contract". For a partial return of one order, common
    EU practice is no delivery refund (e.g. one withdrawal-flow vendor documents "a partial withdrawal refunds no
    delivery at all"). This is practice, not a statute; it is the conservative reading and is the default here.
    <https://docs.mageme.com/eu-withdrawal/customer-flow>
  * Platform behaviour: Shopify makes shipping an explicit, separate merchant choice on the refund page, capped at what
    was charged, with item tax refunded with the item. <https://help.shopify.com/en/manual/fulfillment/managing-orders/refunding-orders>
  * PayPal's refund API only takes a total (`amount`); the split is the merchant's business logic, which is why TradeOS
    computes it in code and records it in the audit chain. <https://developer.paypal.com/docs/api/payments/v2/#captures_refund>

  **Limits (not claimed):** this is a defensible default, not legal advice, and not jurisdiction detection. TradeOS does
  not know whether the buyer chose express delivery, so it treats the order's shipping as standard delivery (an express
  upgrade should be reviewed by the human approver; use `MERCHANT_ERROR` if you do not want to refund shipping on
  withdrawal). Return postage is never refunded. Shipping tax is not modelled, and there is no "prices include tax" mode
  (the sandbox order carries tax per item only). A VAT-inclusive order sent with gross prices and no item tax is
  refunded at the right amount (see "VAT-inclusive prices" below), but the VAT part is not shown. The 14-day statutory refund deadline and "goods diminished in value" deductions are
  not modelled. Withdrawal rights are statutory for UK/EU consumers; outside them this is merchant policy.
* **Cumulative cap:** `refunded or reserved (all batches that are not DECLINED/FAILED) + this batch <= captured`.
  The check is made when proposing, when approving, and again at send time against PayPal's own capture amount.
  `sum(refunded) + remaining == captured` always (property-tested).
* A line quantity can never be refunded or exchanged twice (units used by earlier batches are subtracted).
* **Request id:** `tos-mx-<case>-<10 hex of sha256(case, attempt, items, qty, amounts)>`. The same batch always yields
  the same id (safe retry); a different item set or a new attempt after `DECLINED`/`FAILED` yields a new id, so PayPal
  cannot answer a new refund with an old one. Refusals that moved no money (`ERROR`) retry with the same id.

## Research takeaways (sources)

* **Partial refund = `amount` on the refund call; no amount = refund the remainder in full.**
  Multiple partial refunds are allowed until the captured amount is used up.
  <https://developer.paypal.com/docs/api/payments/v2/#captures_refund>
  The partial amount must never be omitted by mistake (that would refund everything); a test and a mutation cover this.
* **Idempotency:** the same `PayPal-Request-Id` returns the original result. PayPal documents limited retention of keys
  (and a different request with a reused key is a trap), so the id is bound to the exact items.
  <https://developer.paypal.com/api/rest/reference/idempotency/>
* **Item breakdown:** Orders v2 `items[]` carry `unit_amount` and per-unit `tax`; `amount.breakdown` must equal the
  sums. TradeOS uses the per-unit tax as the proportional tax source. The refund API itself takes only a total
  (plus optional `invoice_id`, `custom_id`, `note_to_payer`), so the per-item split lives in TradeOS' audit chain.
  <https://developer.paypal.com/docs/api/orders/v2/>
* **Currencies:** JPY, HUF, TWD take no decimals; sending a decimal is an error.
  <https://developer.paypal.com/api/rest/reference/currency-codes/>
* **Line-item modelling:** Shopify separates return lines and exchange lines and has an explicit process step, so
  returns, exchanges and refunds are decided per line and money is settled once. TradeOS follows that shape.
  <https://shopify.dev/docs/api/admin-graphql/latest/mutations/returnCreate>
* The searched PayPal specs are saved under `/workspace/research` on the dev box (not in the repo).

## Tests

* `tests/test_lineitems.py` (pure math, seeded-random property/fuzz without extra dependencies):
  `sum(item refunds) + remaining == capture`; never over-refund; allocation loses no minor unit; JPY/TWD whole numbers;
  multi-batch sequences consume units once; request-id determinism; LLM-supplied amounts are ignored.
* `tests/test_mixed_orders.py` (offline, mock PayPal): code-computed proposal calls no refund API; approval sends the
  partial amount with the deterministic id; double and concurrent approval refund once; forged/stale approval refused;
  tampered DB amount refused; no chained approval, broken chain, over-refund (also at PayPal), partial then second
  partial; timeout then reconcile with the same id; webhook by refund id; JPY end to end; screen contents; legacy
  single-refund paths refuse a mixed case; single-item flow unchanged.
* `scripts/mutation_sanity.py` (dev tool): applies the deliberate money bugs one at a time. Result on this head: 37 mutants, 33 killed, 4 equivalent, 0 survived. The
  first run had 7 survivors; they exposed 5 test gaps (now covered). Four mutants are reported as **equivalent** (a second independent guard already catches the same bug), not
  hidden.
* `scripts/sandbox_verify.py`: the original 31 checks are untouched. `--mixed` adds the mixed-order live check;
  `--mixed-only --allow-mock` runs only that and is for local mock runs (labelled not live proof). `--multi-batch-only` / `--multi-batch`
  runs Case M2 (two batches on one capture, third attempts refused, one webhook per refund id); `--paypal-overrefund-probe` adds one direct Sandbox over-refund call using `PAYPAL_CLIENT_ID/SECRET` from the environment (PayPal's own refusal, outside the app). There is no tax-inclusive pricing mode. VAT-inclusive gross prices with no item tax are covered by mock tests only (`tests/test_tax_inclusive.py`, see below), not live. Per-item tax is what Case M / M2 send.

Screens: `docs/img/mixed-approval-desktop.png`, `docs/img/mixed-approval-mobile-390.png` (headless Chrome, mock data,
DEMO-DATA badge visible).

## Known limits (NOT covered)

* Live Sandbox proof exists for **two** seeded scenarios only. Case M2 (two-step, 2026-10-18, main `3ad67b3`, `sandbox_verify.py --multi-batch-only --paypal-overrefund-probe`, 23 checks, log kept outside the repo): two partial refunds on ONE capture (55.74 USD then 85.32 USD, each approved by a person; cumulative 141.06 of 191.21 USD, 50.15 remaining), two different PayPal refund ids, two PayPal-Debug-Ids, each PayPal-reported amount equal to the computed one, each refund id matched by its own verified signed `PAYMENT.CAPTURE.REFUNDED` webhook; third attempts (re-approving either batch, re-returning a refunded line, asking for another batch, the legacy refund endpoint) were refused by the app with no third refund call, and one direct Sandbox over-refund of 50.16 USD (probe outside the app, not a TradeOS path) was refused by PayPal with `REFUND_AMOUNT_EXCEEDED` (HTTP 422). Re-run 2026-10-19 on main `5325db7` (`--multi-batch-only`, without the probe): 21/21 PASS, same amounts. Re-run again 2026-10-19 15:40 BST on tip `1acae45` (`--multi-batch-only`): 21/21 PASS, same amounts.
* Case M (2026-10-18, `sandbox_verify.py --mixed`; re-run 2026-10-19 on main `5325db7` with `--mixed-only`, 16/16 PASS; again on tip `1acae45` 15:39 BST, 16/16 PASS: partial refund
  161.69 of 191.21 USD, PayPal-reported amount equal to the computed amount, PayPal-Debug-Id captured, signed webhook and
  reconcile matched; run logs are kept outside the repo). Other item mixes, shipping policies and currencies are covered by
  mock tests only.
* Per-line request reading by the LLM is not built; demo proposals are seeded.
* The supplier contact for exchanges is a **mock** audit entry; nothing is sent to a supplier.
* A refund made outside TradeOS (PayPal dashboard) is not in the ledger; it surfaces only when PayPal rejects with an
  amount-exceeded error, which is recorded as "no money moved".
* PayPal's idempotency-key retention window is limited; a resend after a long outage could create a second refund.
  The cumulative cap at PayPal still bounds the loss to the captured amount.
* A partial refund blocked by an open dispute (`TRANSACTION_DISPUTED`) is handled generically (batch `ERROR`, nothing
  moved, human decides).
* No `invoice_id` is sent (it would have to be unique per refund; `custom_id` carries the batch id instead).

## Decisions for the merchant

1. **Shipping:** the default `WITHDRAWAL_FULL` follows the UK/EU withdrawal norm (see above). Set
   `TRADEOS_SHIPPING_POLICY=MERCHANT_ERROR` or `NEVER` for a stricter merchant policy. (Decided as the default by the
   delegated owner on 2026-10-18; changeable by env var, no code change.)
2. Tax is refunded in proportion to the returned units using the order's per-unit tax. Confirm that matches your tax
   rules (it does not cover tax-inclusive pricing, shipping tax or tax rounding differences vs. PayPal's per-line rounding; per-unit tax is the exact amount recorded on the order, so no rounding is introduced by TradeOS).
3. Is "last unit of a line" the right trigger for refunding a merchant-error line's shipping share? (It is conservative: a partly-returned line never releases shipping.)

## VAT-inclusive prices (worked example; mock tests only)

Many UK/EU shops show prices that already include VAT. With PayPal Orders v2 such an order is sent as the **gross**
`unit_amount` with **no** item `tax`. Only tax that is not already in the price goes into `tax_total`, and PayPal checks
`amount = item_total + tax_total + shipping + ...` ([Orders v2](https://developer.paypal.com/docs/api/orders/v2/#orders_create)).
Sending the included VAT again as item tax would count it twice. TradeOS refunds `unit x qty + tax_unit x qty
(+ shipping share)`, so for such an order **every refund is the gross price x the returned units**. The VAT goes back
inside that amount, at the rate of the original sale, without any rounding by TradeOS.

Example: GBP, prices include 20 % VAT, no item tax.

| Line | Gross price | Qty | Resolution |
|---|---|---|---|
| Trainers | 49.99 | 1 | return (wrong size) |
| Rain jacket | 79.00 | 1 | open (a person decides) |
| Wool socks | 6.00 | 3 | return 1 pair (changed mind) |
| T-shirt | 24.00 | 1 | exchange |
| Shipping (VAT-inclusive) | 4.99 | | |

* PayPal order: `item_total` 170.99, shipping 4.99, no `tax_total`, total **175.98**.
* Refund batch (shipping policy `NEVER`): 49.99 + 1 x 6.00 = **55.99 GBP**, exactly what the customer paid for those
  units. The VAT inside it is 55.99 x 1/6 = **9.33** (trainers 8.33 + socks 1.00), which is what the shop's books need.
  **TradeOS does not show that 9.33**: the approval screen shows "+ tax 0.00 each" and "Tax refunded 0.00", and the stored quote has `tax_minor` 0, because the order carries no item tax. A merchant would have to work out the VAT part in their own books.
* With the default `WITHDRAWAL_FULL` and damaged trainers (merchant error), the trainers' share of the VAT-inclusive
  shipping (1.46 of 4.99, by item value) is added. On mock PayPal the refund call sent is `57.45 GBP` (49.99 + 1.46 + 6.00).
* A return of everything over three batches refunds exactly 175.98 (no penny drift), and a fourth attempt is refused.
* A shop that sends net + per-unit VAT that adds back up to the gross price (e.g. 41.66 + 8.33 = 49.99) gets the same
  refund amounts. Drift can only come from a split that does not add back up, and TradeOS does not make one.

Proven by `tests/test_tax_inclusive.py` (13 tests: pure maths plus one end-to-end run on mock PayPal). **Not proven
live** on PayPal Sandbox. **Not claimed:** showing the VAT part, a VAT rate per line, changes of VAT rate between sale
and refund, shipping-tax rules, or PayPal's own per-line rounding.

## Rollback

Revert the PR. Mixed orders live in their own table (`case_batches`) and the legacy single-refund code path is
untouched (it refuses a mixed case), so there is no data migration to undo.
