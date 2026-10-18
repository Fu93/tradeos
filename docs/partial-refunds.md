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
* **Shipping policy (default `MERCHANT_ERROR`, setting `TRADEOS_SHIPPING_POLICY`, alternative `NEVER`; unknown values
  fail closed to the default):** shipping is **not** refunded for a change-of-mind or ordinary return. It is refunded
  only for a line marked as a merchant error (damaged / wrong item / not as described) and only when the **last unit**
  of that line is refunded. The order's shipping is split over lines with the largest-remainder method so shares always
  sum to the shipping total. Each line's share is released once.
  **This is a business decision for the merchant** (see "Decisions").
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
* `scripts/mutation_sanity.py` (dev tool): applies 30 deliberate money bugs one at a time. Result on this head: 28 killed, 2 equivalent, 0 survived. The
  first run had 7 survivors; they exposed 5 test gaps (now covered). Two mutants are reported as **equivalent** (a second independent guard already catches the same bug), not
  hidden.
* `scripts/sandbox_verify.py`: the original 31 checks are untouched. `--mixed` adds the mixed-order live check;
  `--mixed-only --allow-mock` runs only that and is for local mock runs (labelled not live proof).

Screens: `docs/img/mixed-approval-desktop.png`, `docs/img/mixed-approval-mobile-390.png` (headless Chrome, mock data,
DEMO-DATA badge visible).

## Known limits (NOT covered)

* No live Sandbox proof yet (Tier C). Whether Sandbox accepts the `items[]`/breakdown order for the card source and the
  partial refund behaves as documented is unproven until the live run.
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

1. **Shipping:** keep `MERCHANT_ERROR` (default) or `NEVER`? Refunding shipping for change-of-mind returns is not offered.
2. Tax is refunded in proportion to the returned units using the order's per-unit tax. Confirm that matches your tax
   rules (it does not cover tax-inclusive pricing or tax rounding differences vs. PayPal's per-line rounding).
3. Is "last unit of a line" the right trigger for refunding that line's shipping share?

## Rollback

Revert the PR. Mixed orders live in their own table (`case_batches`) and the legacy single-refund code path is
untouched (it refuses a mixed case), so there is no data migration to undo.
