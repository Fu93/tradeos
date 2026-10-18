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
| **C. Live PayPal Sandbox** | PayPal accepting `items[]` + breakdown for the card capture, and one real partial refund whose PayPal-reported amount equals the computed one, with a `PayPal-Debug-Id` | **NOT done.** Runs only after the user approves merge + deploy: `python scripts/sandbox_verify.py <url> --mixed` |
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
  withdrawal). Return postage is never refunded. Shipping tax and tax-inclusive pricing are not modelled (the sandbox
  order carries tax per item only). The 14-day statutory refund deadline and "goods diminished in value" deductions are
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
  `--mixed-only --allow-mock` runs only that and is for local mock runs (labelled not live proof).

Screens: `docs/img/mixed-approval-desktop.png`, `docs/img/mixed-approval-mobile-390.png` (headless Chrome, mock data,
DEMO-DATA badge visible).

## Known limits (NOT covered)

* Live Sandbox proof exists for **one** seeded scenario only (Case M, 2026-10-18, `sandbox_verify.py --mixed`: partial refund
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

## Rollback

Revert the PR. Mixed orders live in their own table (`case_batches`) and the legacy single-refund code path is
untouched (it refuses a mixed case), so there is no data migration to undo.
