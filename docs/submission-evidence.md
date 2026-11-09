# Submission evidence checklist

This records what the judges actually see on a named build. Historical checks stay labelled historical and do not
transfer to a newer commit until re-run.

The [official challenge](https://paypalaihackathon.devpost.com/) and [rules](https://paypalaihackathon.devpost.com/rules)
require a public open-source repository with a visible license (this repo: **MIT**, [`LICENSE`](../LICENSE)), an English
description and tool attribution, a working demo accessible to judges, and a **public YouTube video under three minutes**
that shows the product functioning. Judges may evaluate from the text, images and video alone. The five scoring
criteria — technological implementation, design, potential impact, innovation and presentation — are equally weighted.
The submission deadline is 12 Nov 2026, 12:00 Pacific Time (20:00 in London); the working demo must remain accessible
through the judging period ending 15 Dec 2026, 08:00 Pacific Time (16:00 in London).

English copy for the form: [`devpost-submission-final.md`](devpost-submission-final.md) (and the earlier
[`devpost-submission-draft.md`](devpost-submission-draft.md)).

## Latest verified hosted build — `49261e5` (8 Nov 2026)

**Commit:** `49261e5f46dd2fb879fc9b24513ae65cb9328645`  
**Demo:** https://tradeos-s33z.onrender.com (`/healthz` `version` matches this SHA; PayPal `sandbox`; LLM + webhook on;
autonomy off; ephemeral persistence; safety AI layer off). Differs from `1d5ab96` only in copy/templates (no money-path
logic change).

| Check | Result |
| --- | --- |
| Hosted `sandbox_verify.py` | **31/31** |
| AI end-to-end (`--ai-e2e-only`) | **11/11** |
| Signed webhooks | **3/3 VERIFIED** |
| GET reconciliation | **3/3** |
| Audits | **10/10** |
| UI checks | **10/10** |
| Malformed Origin / Referer | **403** (58/58); no 500 |
| Deterministic policy matrix | **582/582** (rules, not LLM requests) |
| Offline pytest (local source, this tip) | **1845** passed, coverage **95.09%**, ruff + mypy clean; mock PayPal (not hosted refund evidence) |

Sample refund IDs from this hosted run: `8J695063YN268980W`, `5T938247AP7025502`, `20907736BD190784X`.

**LLM intent eval** (historical measurement on tip `9dafb70`, 2026-11-08, still the committed
[`docs/eval/results.json`](eval/results.json)): on **52 author-written messages**, Groq `openai/gpt-oss-20b`, one run —
exact **41/52** vs keyword **17/52**; policy request-check **52/52** on this small set (not general accuracy).

**YouTube URL:** _TBD — placeholder; do not submit until a real public video under 3:00 exists._

### Historical (labelled)

- Hosted `1d5ab96` (8 Nov 2026): preflight 9/9, sandbox 31/31, AI e2e 11/11, 3 signed webhooks VERIFIED, GET
  reconciliation all match, malformed Origin/Referer 58/58 → 403, public reset → 403. Superseded for tip pinning by
  `49261e5` (copy/templates only).
- Published `dc2c6b5` (5–7 Nov 2026): hosted 31/31 — see [`docs/evidence/`](evidence/) and
  [`sandbox-verification.md`](sandbox-verification.md).
- Local Sandbox on `9dafb70` (8 Nov 2026, isolated machine): 62 pass / 0 fail / 6 webhook SKIP; UNKNOWN 2/2;
  ERROR-retry 4/4; over-refund 422; AI e2e 11/11 — not a substitute for the current hosted tip.

## Procedure for a future published version

1. Freeze the candidate source and record its full Git SHA. Keep the public demo, README, video and verification on
   that same commit.
2. After an authorized deployment, run the read-only version/configuration check:

   ```bash
   python scripts/submission_preflight.py https://tradeos-s33z.onrender.com --commit <40-character-sha> > preflight-<sha>.json
   ```

   It fails if `/healthz` reports a different commit, non-Sandbox PayPal, no LLM, no webhook, either auto-refund or
   auto-exchange autonomy on, `safety_ai_layer` on, or non-ephemeral persistence (public demo profile). A pass is only
   a deployment/configuration check, not a refund test.
3. Run `python scripts/sandbox_verify.py https://tradeos-s33z.onrender.com` and save the full output. Optional:
   `--ai-e2e-only` for the live LLM intent path.
4. Record the video on the same deployment using [`demo-video-script.md`](demo-video-script.md) (v9). Match each spoken
   claim to a visible result; label the scripted MCP client and every wait cut.
5. Check the final submission page: video URL opens, demo URL opens, source commit matches `/healthz`, MIT license is
   visible, evidence links open, and Sandbox/mock/estimated claims are labelled accurately.

The shared hosted demo uses an **ephemeral** database (restart/deploy may reseed or clear cases). Public
`POST /demo/reset` is **disabled by default** (`TRADEOS_ALLOW_PUBLIC_RESET=0` → 403) so another visitor cannot wipe
the demo; only an explicit private/operator opt-in can reset. Prefer a private Sandbox copy for recording. Do not
claim “no bugs”, “100% correct”, “fraud-proof”, or “production-ready”. The audit hash chain is **tamper-evident**,
not immutable.

## Review residuals — status on tip `f2c7430`

| ID | Sev | Finding | Status |
|---|---|---|---|
| A1 | Med | Stale FAILED identity after retry | **Fixed** |
| A2 / C1–C2 | Med→High | ERROR Request-Id reuse past 6h | **Fixed** |
| A3 / C6 | Low | Confirm-by-GET accepts FAILED | **Keep** — unlocks retry after PayPal confirms FAILED |
| A4 | Low | Capture GET missing `id` matched | **Fixed** |
| C3 | High | Confirm accepts CANCELLED | **Fixed** |
| C4 / D5 / E11 | Med | Open-demo MCP / shared approve | **Defer** — intentional shared Sandbox; no approve/refund tool |
| C5 | Low | CSRF trusts `X-Forwarded-Host` | **Defer** — browsers cannot set it |
| B1 | Soft | Hosted service ≠ Blueprint | **Documented** |
| B8 | Low | README test count drift | **Fixed** — tip count lives in this table (**1845**); avoid scattering stale counts elsewhere |
| D7 | Low | Full LLM eval refresh | **Done** — committed results from 2026-11-08 |
| D8 | Soft | Hosted tip ≠ `dc2c6b5` | **Done** — historical `f2c7430` / `1d5ab96` verifies; latest hosted verification is `49261e5` (8 Nov 2026) |
| E4 | High | Public reset archives all cases | **Fixed** (`TRADEOS_ALLOW_PUBLIC_RESET=0`) |
| E10 | Soft | YouTube URL TBD | **Open** — owner content |
| F1 / B01 | Low→Med | Malformed Origin/Referer → 500 | **Fixed** — 403 (58/58) on `f2c7430` |
| F2–F4 | Low–Med | Keyword eval / ChatJSONClient / reset default | **Fixed** |
