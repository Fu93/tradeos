# PayPal Sandbox technical recheck — 7 Nov 2026 (UTC)

Target: `https://tradeos-s33z.onrender.com`. Before and after the checks,
`/healthz` reported version `dc2c6b5cd40e19c2f859d54a71f06b593c350864`,
`paypal_mode=sandbox`, webhook configured, and autonomy off. This is the
**published commit**. The local working tree has unpublished modifications;
these live results do not verify those modifications.

The existing `scripts/sandbox_verify.py` default run returned **ALL PASS**.
Case A `A-60D33E00C5A94193` required human approval, then PayPal reported
refund `5CU31908FJ612894J` COMPLETED. The refund call carried a real
PayPal-Debug-Id `f907302d4438b`; a signed
`PAYMENT.CAPTURE.REFUNDED` webhook was verified locally (`self`), the PayPal
reconciliation matched, and the 28-entry case audit chain verified. Case B
`B-056FD80F62B046C0` made zero refund calls. Exchange
`F-B6CD35F488564ED7` made zero refund calls. Case R
`R-95CA3BD3BA2D43C8` first received a PayPal 422, then its retry completed
with the same PayPal-Request-Id.

The separate `--multi-batch-only` run also returned **ALL PASS**. Case
`M-FA8F88C5CE3A4CE5` made exactly two partial refunds on one capture:

| Batch | Computed and PayPal-reported amount | Refund ID | PayPal-Debug-Id |
| --- | --- | --- | --- |
| 1 | 55.74 USD | `83F68359C6326072F` | `f5513094f161e` |
| 2 | 85.32 USD | `2H170850LJ917432N` | `f294894c55779` |

Cumulative refund: 141.06 of 191.21 USD. Re-approvals and another attempted
return made no third refund call. The signed webhook matched each refund ID,
and the 44-entry audit chain verified. No direct over-refund probe was run.

These two checks created five test cases and four refunds in **PayPal Sandbox**
on the already published demo. They did not publish code or move real money.
The PayPal Developer Dashboard lookup of the recorded Debug-Ids remains a
manual cross-check. Validating the unpublished code against live Sandbox still
requires Sandbox credentials bound to this development environment, or a
deployment of that exact code version; neither was available or performed.
