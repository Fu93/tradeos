# Submission evidence checklist

This is a procedure for a **future published version**. It records what the judges actually see; it does not turn
historical checks into evidence for a newer build. No result is claimed until the commands have run against that build.

The [official challenge](https://paypalaihackathon.devpost.com/) and [rules](https://paypalaihackathon.devpost.com/rules)
require a public open-source repository with a visible license, an English description and tool attribution, a working
demo accessible to judges, and a **public YouTube video under three minutes** that shows the product functioning.
Judges may evaluate from the text, images and video alone. The five scoring criteria — technological implementation,
design, potential impact, innovation and presentation — are equally weighted. The submission deadline is 12 Nov 2026,
12:00 Pacific Time (20:00 in London); the working demo must remain accessible through the judging period ending
15 Dec 2026, 08:00 Pacific Time (16:00 in London). The [English submission draft](devpost-submission-draft.md) contains
only claims that the current evidence can support; fill its remaining placeholders from the final deployed version.

**Current tip (PR #100):** use `git rev-parse HEAD` on this branch. Local Sandbox on an isolated verification machine
for `9dafb70` (8 Nov 2026): 62 pass / 0 fail / 6 webhook SKIP; UNKNOWN 2/2; ERROR-retry 4/4; over-refund 422;
AI e2e 11/11. Same-day full LLM eval on `9dafb70` with Groq **`openai/gpt-oss-20b`** (52 cases, one run, all
HTTP 200): exact **41/52** (78.85%), lenient **47/52** (90.38%), intent 49/52, reason 45/52, action 48/52, policy
request-check **52/52**, `unwarranted_accept` **0**, `missed_accept` **0**, injections 7/7 policy-safe (0 unwarranted);
keyword **17/52** exact, unwarranted 0, missed_accept 25; tokens 39,637 in / 15,543 out (incl. 3 AI e2e) ≈ US$0.0076.
The HTTP 400 → `json_object` path is unit-tested and was **not hit** live in that eval. Tip now **1,838** tests /
~95% cov. Hosted cases record extractor `llm:openai/gpt-oss-20b`. **Hosted redeploy of this tip is still pending** —
do not cite 31/31 on the public URL until `/healthz` `version` matches and `sandbox_verify.py` is re-run there. Video
URL still TBD.

1. Freeze the candidate source and record its full Git SHA. The working tree must be clean, including the video/script
   changes that are part of the submission. Keep the public demo, README, video and verification on that same commit.
2. After an authorized deployment, run the read-only version/configuration check. Save its JSON with the commit:

   ```bash
   python scripts/submission_preflight.py https://<demo-host> --commit <40-character-sha> > preflight-<sha>.json
   ```

   It fails if `/healthz` reports a different commit, non-Sandbox PayPal, no LLM, no webhook, either
   auto-refund or auto-exchange autonomy on, `safety_ai_layer` on, or non-ephemeral persistence (public demo profile).
   A pass is **only** a deployment/configuration check, not a refund test. Do not edit the JSON after capture.
3. Run `python scripts/sandbox_verify.py https://<demo-host>` and save the full output, exit status, UTC timestamp and
   reported PayPal mode. The script creates new Sandbox orders/refunds. If a run fails, preserve that log too; explain
   any retry rather than replacing the failure. Do not cite 31/31 until the complete check passes on this commit.
   Optional: `python scripts/sandbox_verify.py https://<demo-host> --ai-e2e-only` (live LLM intent path; prints the
   measured `llm_chat_completions` count from case extraction metadata; target must already have `LLM_API_KEY` /
   `LLM_BASE_URL` / `LLM_MODEL`).
4. Record the video on the same deployment using [the short script](demo-video-script.md). Match each spoken claim to
   a visible result; show the actual AI extractor and intent; label the scripted MCP client and every edit that skips
   a wait. Keep a backup clip of the same run.
5. Check the final submission page: video URL opens, demo URL opens, source commit matches `/healthz`, the README's
   evidence links open, and all Sandbox/mock/estimated claims are labelled accurately. Re-run the read-only preflight
   if the deployment changes. A new deployment invalidates the previous live verification until rechecked.

The shared hosted demo has an ephemeral database and can be reset by another visitor. Prefer a private Sandbox copy
for recording and avoid the public reset during judging. If the public demo is temporarily busy, show the recorded
flow and link the exact verification log for the named commit. This is a fallback, not a claim of current uptime.

## Review residuals (medium / low) — status on this tip

| ID | Sev | Finding | Status |
|---|---|---|---|
| A1 | Med | Stale FAILED identity after retry | **Fixed** (clears `refund_id` / `refund_status`) |
| A2 / C1–C2 | Med→High | ERROR Request-Id reuse past 6h (single + mixed) | **Fixed** (`mint_retry_request_id`, ≤38 chars, repeated-expiry tests) |
| A3 / C6 | Low | Confirm-by-GET accepts FAILED | **Keep** — unlocks new-request retry after PayPal confirms FAILED |
| A4 | Low | Capture GET missing `id` matched | **Fixed** |
| C3 | High | Confirm accepts CANCELLED | **Fixed** (leave UNKNOWN) |
| C4 | Med | Open-demo MCP order-injection race (integrity only) | **Defer** — intentional open `/mcp`; no money/approval impact; ownership enforced when MCP tokens configured |
| C5 | Low | CSRF trusts `X-Forwarded-Host` | **Defer** — browsers cannot set that header; Render/CF edge sets it |
| B1 | Soft | Hosted service ≠ Blueprint (lockfile + health check) | **Documented** — operator action at redeploy; not claimed fixed on the live service |
| B6 | Low | README Scope said intake “not implemented” | **Fixed** earlier |
| B7 | Low | Preflight missed `auto_exchange_enabled` | **Fixed** |
| B8 | Low | README test count drift | **Fixed** (1,838 on this tip) |
| B9 | Low | README PR count | **Fixed** (85 merged) |
| B13 | Low | Preflight ignored safety AI / persistence | **Fixed** (requires `safety_ai_layer=false`, `persistence=ephemeral`) |
| — | — | SQLite ResourceWarnings; webhook SKIP; docs 27→31 | **Fixed** |
| D1 | Med | Keyword fallback missed common EN phrasings (eval m02–m09) under LLM outage | **Fixed** (deterministic patterns + tests; overall keyword exact now **17/52**, unwarranted 0, missed_accept 25) |
| D2 | Med | Judge guide hid steps 2–3 with no explanation during cold start | **Fixed** (muted “steps 2–3 appear…” until cases exist) |
| D3 | Low | README quick-start led with Sandbox secrets before zero-config mock | **Fixed** (`PAYPAL_MOCK=1` first) |
| D4 | Low | Docs still pinned tip `a196741` / “owner's machine” after `e1c510b` Sandbox | **Fixed** (isolated verification machine + `e1c510b`) |
| D5 | Med | Open `/mcp` order-injection race on shared demo | **Defer** — same as C4; no approve/refund tool; ownership when MCP tokens set |
| D6 | Low | Shared-demo approve can finish another judge's case | **Defer** — intentional shared Sandbox; reset is advanced+confirm; rate limits apply |
| D7 | Low | Full LLM eval re-run (`eval_intent` without `--keyword-only`) | **Measured** 2026-11-08 on tip `9dafb70` (Groq `openai/gpt-oss-20b`): exact 41/52, lenient 47/52, policy 52/52, unwarranted 0; all HTTP 200 (400 path unit-tested, not hit live). Judge docs updated; committed `docs/eval/results.json` per-case LLM rows still the 8 Oct artifact until a full JSON refresh is committed |
| D8 | Soft | Hosted tip ≠ published `dc2c6b5` until redeploy | **Defer** — owner redeploy + `sandbox_verify` / `--ai-e2e-only` |
| E1 | P1 | Agent finish CTA used `#agents` (MCP docs) not Approve | **Fixed** (`#pending` + blocked-case link) |
| E2 | P1 | Busy flash plain path; guide hid in-progress state | **Fixed** (flash link + guide watch status) |
| E3 | P1 | `.badge.warn` missing (LLM/webhook/ephemeral) | **Fixed** (CSS) |
| E4 | High | Public `POST /demo/reset` archives every judge's cases | **Fixed** (`TRADEOS_ALLOW_PUBLIC_RESET=0` on Blueprint) |
| E5 | Med | Unverified webhook wrote case audit + returned `case` id | **Fixed** (log-only; omit `case` unless verified) |
| E6 | Low | Verified webhook without `event_id` treated as duplicate | **Fixed** (`MISSING_EVENT_ID`) |
| E7 | Low | `approve_url` not host-allowlisted | **Fixed** (`paypal_browser_url`) |
| E8 | Med | Keyword misses m46/m48/m49/m51; SIZE beat DAMAGED | **Fixed** (patterns + DAMAGED-first; keyword exact 17/52) |
| E9 | Low | Eval Limits prose said refunds never automated | **Fixed** (`render_md`) |
| E10 | Soft | YouTube URL TBD | **Defer** — owner content |
| E11 | Med | Open MCP / shared approve (C4/D5/D6) | **Defer** — intentional shared demo; private = operator + MCP tokens |
| F1 | Low | `paypal_browser_url("https://[")` raised ValueError | **Fixed** (catch; return None) |
| F2 | Low | README/docs still cited keyword eval 8/52 | **Fixed** (17/52, unwarranted 0, missed_accept 25) |
| F3 | Med | `eval_intent` aborted on Groq `json_validate_failed` | **Fixed** (same ChatJSONClient retry + record per-case errors; intake already retried any 400) |
| F4 | Med | Local `TRADEOS_ALLOW_PUBLIC_RESET` default was 1 | **Fixed** (safe default `0`; Blueprint stays explicit `0`) |
