* **Two sets, two purposes.**
  - The original 100 is a regression set of known scenarios. The author wrote it together with the rules, so a high score shows consistency, not field accuracy.
  - The held-out 60 is the unseen set. A different model family (`qwen/qwen3.8-27b`) generated it from a prompt that contained no rules. The author labelled it before any run (commit d5752f0). Its labels are still **pending human review** (`heldout-review.csv`).
* **Which extractor model.** The app's default extractor is `openai/gpt-oss-20b`. On 2026-10-09 the Groq free-tier daily cap for that model (200,000 tokens per day) had already been used up by the round-1 runs and an aborted round-2 start. Because of that, both round-2 LLM runs used `openai/gpt-oss-120b`, which is the same family, has a separate quota, and gets the same prompt and schema. **These are therefore not production-model numbers.** The `gpt-oss-20b` held-out run is still to do, with the same frozen labels. A 20b attempt was stopped automatically after 1 row by the daily cap. The script refuses to fall back silently to keywords on a daily-cap 429.
* **Was the held-out set used for tuning? No.**
  - The 0.2.0 rules were committed (a4ffee8) before any held-out run.
  - Nothing in the rules, prompt or keyword lists changed after the held-out results were seen. The held-out numbers here are the pre-change numbers (snapshot `routing-results-heldout-prechange.json`).
  - Caveat: the author read the 60 messages while labelling them, before writing the 0.2.0 rules. The rules follow the user's design, not specific messages, but this is a contamination risk. The next round needs a fresh held-out set no matter what.
  - Any rule change made in response to these errors (see "Remaining weaknesses" in the roadmap) turns this set into "used for tuning".
* **Small samples.** 60 cases is preliminary evidence, not proof:
  - A 51/60 action accuracy has a Wilson 95% interval of roughly 74–92%.
  - Even 60/60 would only bound the true rate at roughly ≥ 94%.
  - The held-out set has only 3 labelled supplier-task cases, so precision and recall of task creation are essentially unmeasured on unseen data.
  - The intervals are printed next to the key rates.
* **Confidence.** The self-report is uncalibrated, and it is used only to demote. The confidence analysis shows whether it separates right from wrong on these rows. Because the floor (0.90) sits below almost all self-reports, it almost never fires on the LLM path.
* **Keyword fallback.** Its confidence is capped at 0.85, below the 0.90 floor, so it can never perform an automatic action. Its action accuracy is low by design: it sends cases to people; it does not route them.
* **Label errata**: [heldout-label-errata.md](heldout-label-errata.md). Labels are never edited; the metrics use the frozen labels.
* **Duplicate metric, original LLM run (1/8).** The 1/8 is P08. Its twin P01 was *demoted* by confidence: the combined score was 0.89, because the keyword scan disagreed with the AI's DEFECT issue. P01 therefore never opened a task. When P08 arrived there was no open task to link to, so a first task was created, which is correct. The DB still holds 0 keys with more than one open task.
* **"Repair or replace" read as mixed.** gpt-oss-120b flagged `mixed_goals` on "repair or replace" / 修理か交換 / reparieren oder ersetzen. This caused 4 of the 6 missed supplier tasks in the original set (D04, D05, D07, P05) and held-out H48. The miss is in the safe direction (it asks the customer). The prompt was deliberately **not** changed after seeing this, because a change would make the held-out set "used for tuning".
