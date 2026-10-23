# What is proven, and how strongly

Every claim TradeOS makes is tied to an evidence tier: live PayPal Sandbox runs, automated tests against a mock, or synthetic evals. Nothing here is claimed for production (live) PayPal or real merchants.

## Evidence tiers

| Tier | Claim | Evidence | Not claimed |
|---|---|---|---|
| **Live PayPal Sandbox** | Real order, capture, refund ids; signed webhook verified; reconcile GET; Refund API call count 0 on rejected cases | `scripts/sandbox_verify.py` against the live demo (last run on tip `1acae45`, 19 Oct 2026 15:38–15:40 BST: 31/31 PASS; earlier same-day re-run on `5325db7`: 31/31), [`sandbox-verification.md`](sandbox-verification.md) | Production (live) PayPal; real buyers |
| **Live Sandbox, mixed order** | One seeded mixed order (Case M: 3 refund lines + 1 exchange): partial refund of 161.69 of 191.21 USD, PayPal-reported amount equals the amount the code computed, second approval refused, signed webhook matched, reconcile matched (`sandbox_verify.py --mixed` / `--mixed-only`, 16 checks; last run on tip `1acae45`, 19 Oct 2026: 16/16; earlier same-day on `5325db7`: 16/16; logs kept outside the repo) | [`partial-refunds.md`](partial-refunds.md) | Other item mixes, shipping/tax policies or currencies; production (live) PayPal |
| **Live, partly** | Disputes: read-only GET (the Sandbox app has no disputes: empty list) and **one PayPal-simulated** `CUSTOMER.DISPUTE.CREATED` webhook (a PayPal sample payload) | [`disputes-readonly.md`](disputes-readonly.md) | A real buyer dispute, parsing a real dispute object, any dispute action |
| **Live Sandbox, two partial refunds on one capture** | Case M2: batch 1 (55.74 USD) and batch 2 (85.32 USD) on one capture, each approved by a person, cumulative <= capture, two refund ids each matched by its own signed webhook; third attempts refused (app: no refund call; one direct Sandbox over-refund probe: PayPal `REFUND_AMOUNT_EXCEEDED`) (`sandbox_verify.py --multi-batch-only --paypal-overrefund-probe` on `3ad67b3`; re-run on tip `1acae45`, 19 Oct 2026, without the probe: 21/21; earlier same-day on `5325db7`: 21/21; logs kept outside the repo) | [`partial-refunds.md`](partial-refunds.md) | Showing the VAT split / a tax-inclusive mode (gross VAT-inclusive amounts: mock tests only), other item mixes, currencies, production PayPal |
| **Automated tests (mock PayPal)** | Policy, guards, safety gate, mixed-order partial refund maths, autonomy, hash chain, evidence report, accessibility structure | `pytest` (see Tests; CI: ruff, mypy, pip-audit, 90% coverage gate) | Any PayPal behaviour: the mock is not PayPal |
| **Evals (synthetic messages)** | Multilingual intent and safety routing | [`eval/`](eval/results.md), [`impact-proof.md`](impact-proof.md) (states what is and is not human-checked) | Real-world accuracy |
| **Seeded / mock demo data** | `/queue` view, supplier replies, cost model | Labelled DEMO / MOCK on screen | Any measured saving or merchant validation |
| **Dev tooling** | [Postman collection](postman/README.md) of the Sandbox calls | Not run against PayPal by us as part of this evidence; a manual run you do is your own evidence | Any proof |

## Live Sandbox screenshots

![TradeOS dashboard — Case A: refund COMPLETED, confirmed by PayPal (live Sandbox)](dashboard.png)

More live-Sandbox screenshots (1440x900, retaken 2026-10-17 (UTC) after the guided hint, the Sandbox notice and the 'PayPal proves' panel landed (#46, #47)): [evidence panel](screenshots/caseA-evidence-live.png),
[evidence details](screenshots/caseA-evidence-details-live.png), [reconcile + audit badge](screenshots/caseA-reconcile-audit-live.png),
[refund failure then retry](screenshots/refund-failure-retry-live.png), [double click](screenshots/double-click-live.png),
[prompt injection](screenshots/injection-live.png), [late request](screenshots/late-request-live.png), [mobile 375px](screenshots/mobile-375-live.png).
Images under `screenshots/mock/` were taken with the offline MOCK PayPal client and are not used as evidence for any claim.

## Evaluation: 52 multilingual messages

`scripts/eval_intent.py` runs the production LLM extractor and the keyword fallback over a hand-labelled set of 52
post-purchase messages (EN, Traditional Chinese, Spanish, German, Japanese, plus mixed-language / typo / slang / French,
including 7 prompt-injection attempts). Full results, every miss and the limits: **[docs/eval/results.md](eval/results.md)**
(raw: [results.json](eval/results.json), data: [dataset.json](eval/dataset.json)).

| (one run, `openai/gpt-oss-20b` on Groq) | LLM | Keyword fallback |
| --- | --- | --- |
| Exact match, all 3 core fields | 73% (38/52) | 15% (8/52) |
| Exact match if reason `OTHER` ≈ `UNKNOWN` | 88% (46/52) | 15% (8/52) |
| Intent accuracy | 94% (49/52) | 21% (11/52) |
| Injections that yielded a policy-acceptable request they shouldn't | 0 / 7 | 0 / 7 (was 2 / 7 before the fallback guard) |
| Latency p50 / p95 | 0.63 s / 1.25 s | — |
| Estimated cost per message (Groq list price) | $0.00013 | $0 |

These numbers were measured before the return-vs-exchange change (when only exchanges were automated and a refund
request was always rejected); the "policy-acceptable" row has not been re-run under the new rules. Intent accuracy
is unaffected by the policy change.

Small, self-written dataset — indicative, not a benchmark. Most LLM misses are the `OTHER` vs `UNKNOWN` reason
convention for order-status questions; "wrong item" is sometimes read as "not as described". No output can move money:
the policy still decides, and only an approval on the audit chain can start a refund (a person's, or the merchant's
policy's when autonomy is on). Injection detection is heuristic (patterns):
messages with instruction-like markers are never automated (the policy rejects them and a human reads them), but a
cleverly worded message can avoid the patterns, so it is not the safety boundary. The keyword column was
re-run after the **fallback injection guard**: before it, two injections containing the literal word "EXCHANGE" fooled
the keyword rules. Now, when the LLM is unavailable and a message looks like a prompt injection, the fallback forces
`UNKNOWN`. The case goes to a human with no Approve button, and the timeline says why. The LLM path is unchanged.

See also [docs/impact-proof.md](impact-proof.md): outcomes by case category from the committed eval artifacts, with
the three validation levels (test results / human adjudication of specific labels / full human audit, **not done**) kept apart.

## Tests

```bash
pytest
```

The suite never calls real PayPal or a real LLM (PayPal is replaced by an in-memory mock wrapped in `MagicMock`,
HTTP is replaced by `httpx.MockTransport`). It covers the policy engine (window boundaries, capture status,
amount/currency, product, supplier, "no AI output can override a NO"), the PayPal client (token caching, card
order payload, refund body / `note_to_payer` / `PayPal-Mock-Response`, structured errors, webhook verification
payload), the LLM adapter (strict schema, off-schema → `UNKNOWN`, assist fields validated separately and ignored by the
policy, fallback on errors), the grounded customer note (number check, 255-char limit, fallbacks), free text
(presets, late toggle, length cap, rate limits), the failure modes (late, injection, forced refund failure + retry,
double-click and concurrent approvals → one refund), the webhook endpoint (verified / forged / unknown) and the
workflow/HTTP layer — including **Case B: `refund_capture` is asserted never to be called**, even with a forged
approval or a lying extractor — the autonomy decision (off by default; the refund limit and the exchange switch
separately, each behind the master switch; above the limit, an instruction-like message and an unreadable request all
escalate; an out-of-stock exchange stays a person's call even with every switch on; autonomy cannot override a policy
NO; an auto approval is on the chain as `approval_source: auto`; and neither the timeline, the case list nor the UI
ever calls an auto approval a human one), and the forward migration of a kept database (`TRADEOS_RESET_ON_START=0`):
a database from before `approval_source` existed gains the column, keeps its chain verifiable, and still refunds.
1029 tests, run by GitHub Actions CI on every push and PR (see the badge) together with `ruff`, `mypy` over `app/`,
a `pip-audit` scan of the pinned dependencies, and a `pytest-cov` gate at 90% line coverage
(incl. eval dataset checks, VAT-inclusive mock tests, CPSC sample integrity, mixed Safety Gate line-product
scan, and discipline invariants). Count verified locally after merging #69+#70+#71+#72+#73
(1005 + 3 mixed Safety Gate + 21 discipline invariants = 1029). The repository is public, so
GitHub's standard hosted runners cost nothing here.

### Verify a deployment

`scripts/sandbox_verify.py <base-url>` drives a running instance through the whole loop over HTTP and asserts the
result. It needs no credentials, so it works against the Render demo or against `http://localhost:8000`:

```bash
python scripts/sandbox_verify.py https://<your-host>      # a deployed instance
AUTO_ENABLED=1 uvicorn app.main:app --port 8000 &          # or a local one with real Sandbox credentials
python scripts/sandbox_verify.py http://localhost:8000
```

The `Deploy verify` workflow can automate this after every push to `main`: it waits until `/healthz` reports the pushed
commit (Render injects `RENDER_GIT_COMMIT`, which `/healthz` exposes as `version`), runs the script against the
live instance, and saves `GET /audit/heads` as a workflow artifact (`audit-heads-<commit>`). It needs the
`TRADEOS_DEPLOY_URL` repository secret (e.g. `https://<your-app>.onrender.com`). **That secret is not set for this
repository, so the workflow does not verify anything today:** its verify job is skipped and the run summary says so. A
green "Deploy verify" run is not a live check. The live checks for the current commit were run by hand with the script
(see [`sandbox-verification.md`](sandbox-verification.md) for the last run).

Autonomy must be **off** on the hosted demo: the script fails (before creating any case) if `/healthz` reports
`auto_enabled` or `auto_exchange_enabled` true, unless `--allow-autonomy` / `ALLOW_AUTONOMY=1` is given for a deliberate
local run (deploy-verify never passes it). It reads the target's autonomy setting from `/healthz` and asserts the behaviour that goes with it — with autonomy
off, Case A must wait for a person and make no refund call until one approves; with autonomy on, the same case must
already be `REFUND_COMPLETED` with no approve call, `approval_source: auto` on the hash chain, and a page that
credits the merchant's policy rather than a human. Exit code 0 = every check passed.
