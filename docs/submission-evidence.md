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

**Current tip (PR #100):** `a196741`. Local Sandbox run on the owner's machine (8 Nov 2026): 62 pass / 0 fail /
6 webhook SKIP; ERROR-retry 4/4; UNKNOWN recovery 2/2. **Hosted redeploy of this tip is still pending** — do not cite
31/31 on the public URL until `/healthz` `version` matches and `sandbox_verify.py` is re-run there. Video URL still TBD.

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
   Optional: `python scripts/sandbox_verify.py https://<demo-host> --ai-e2e-only` (live LLM intent path; **1** chat
   completion; target must already have `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`).
4. Record the video on the same deployment using [the short script](demo-video-script.md). Match each spoken claim to
   a visible result; show the actual AI extractor and intent; label the scripted MCP client and every edit that skips
   a wait. Keep a backup clip of the same run.
5. Check the final submission page: video URL opens, demo URL opens, source commit matches `/healthz`, the README's
   evidence links open, and all Sandbox/mock/estimated claims are labelled accurately. Re-run the read-only preflight
   if the deployment changes. A new deployment invalidates the previous live verification until rechecked.

The shared hosted demo has an ephemeral database and can be reset by another visitor. Prefer a private Sandbox copy
for recording and avoid the public reset during judging. If the public demo is temporarily busy, show the recorded
flow and link the exact verification log for the named commit. This is a fallback, not a claim of current uptime.

## Review residuals (medium / low) — status at tip `a196741`

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
| B8 | Low | README test count drift | **Fixed** (1,811 at `a196741`) |
| B9 | Low | README PR count | **Fixed** (85 merged) |
| B13 | Low | Preflight ignored safety AI / persistence | **Fixed** (requires `safety_ai_layer=false`, `persistence=ephemeral`) |
| — | — | SQLite ResourceWarnings; webhook SKIP; docs 27→31 | **Fixed** |
