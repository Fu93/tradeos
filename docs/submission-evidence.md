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

1. Freeze the candidate source and record its full Git SHA. The working tree must be clean, including the video/script
   changes that are part of the submission. Keep the public demo, README, video and verification on that same commit.
2. After an authorized deployment, run the read-only version/configuration check. Save its JSON with the commit:

   ```bash
   python scripts/submission_preflight.py https://<demo-host> --commit <40-character-sha> > preflight-<sha>.json
   ```

   It fails if `/healthz` reports a different commit, non-Sandbox PayPal, no LLM, no webhook, or autonomy on. A pass is
   **only** a deployment/configuration check, not a refund test. Do not edit the JSON after capture.
3. Run `python scripts/sandbox_verify.py https://<demo-host>` and save the full output, exit status, UTC timestamp and
   reported PayPal mode. The script creates new Sandbox orders/refunds. If a run fails, preserve that log too; explain
   any retry rather than replacing the failure. Do not cite 31/31 until the complete check passes on this commit.
4. Record the video on the same deployment using [the short script](demo-video-script.md). Match each spoken claim to
   a visible result; show the actual AI extractor and intent; label the scripted MCP client and every edit that skips
   a wait. Keep a backup clip of the same run.
5. Check the final submission page: video URL opens, demo URL opens, source commit matches `/healthz`, the README's
   evidence links open, and all Sandbox/mock/estimated claims are labelled accurately. Re-run the read-only preflight
   if the deployment changes. A new deployment invalidates the previous live verification until rechecked.

The shared hosted demo has an ephemeral database and can be reset by another visitor. Prefer a private Sandbox copy
for recording and avoid the public reset during judging. If the public demo is temporarily busy, show the recorded
flow and link the exact verification log for the named commit. This is a fallback, not a claim of current uptime.
