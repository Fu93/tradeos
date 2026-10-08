"""Offline evaluation of intent extraction: LLM extractor vs keyword fallback.

    LLM_API_KEY=... python scripts/eval_intent.py            # full run (throttled for Groq free tier)
    python scripts/eval_intent.py --keyword-only               # no API key needed

Reads docs/eval/dataset.json (hand-labelled), runs the production extractors from
app/intent.py unchanged, and writes docs/eval/results.json + docs/eval/results.md.

Metrics: per-field accuracy, exact match (all 3 core fields), per-language exact match,
detected-language accuracy (LLM assist field), policy-level safety (would the policy's
request check accept a case it should not?), injection outcomes, HTTP latency p50/p95,
token usage and an estimated cost per message from Groq's published price.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL  # noqa: E402
from app.intent import KeywordIntentExtractor, LLMIntentExtractor  # noqa: E402
from app.policy import PolicyInput, evaluate  # noqa: E402

DATASET = ROOT / "docs" / "eval" / "dataset.json"
OUT_JSON = ROOT / "docs" / "eval" / "results.json"
OUT_MD = ROOT / "docs" / "eval" / "results.md"
FIELDS = ("intent", "reason", "requested_action")
LANG_ORDER = ("en", "zh-Hant", "es", "de", "ja", "mixed")
# Groq price for openai/gpt-oss-20b, USD per 1M tokens (https://console.groq.com/docs/model/openai/gpt-oss-20b,
# read 2026-10-08). Update if Groq changes it.
PRICE_IN, PRICE_OUT = 0.075, 0.30
PRICE_SOURCE = "https://console.groq.com/docs/model/openai/gpt-oss-20b (read 2026-10-08): $0.075 / 1M input, $0.30 / 1M output tokens"
# Expected language codes for the assist field; mixed-language rows are only scored where one language dominates.
# m47 (es/en) and m48 (zh/en) are genuinely mixed and not scored.
MIXED_LANG = {"m46": "en", "m49": "en", "m50": "fr", "m51": "en", "m52": "en"}


class RecordingTransport(httpx.BaseTransport):
    """Wraps the real transport: retries 429s transparently (so throttling never turns into a
    silent keyword fallback) and records latency + token usage of each successful call."""

    def __init__(self) -> None:
        self.inner = httpx.HTTPTransport()
        self.last: dict | None = None
        self.retries_429 = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        for _ in range(8):
            t0 = time.perf_counter()
            resp = self.inner.handle_request(request)
            resp.read()
            elapsed = time.perf_counter() - t0
            if resp.status_code != 429:
                break
            self.retries_429 += 1
            time.sleep(min(float(resp.headers.get("retry-after", "10") or 10), 60) + 1)
        try:
            usage = json.loads(resp.content).get("usage") or {}
        except ValueError:
            usage = {}
        self.last = {"status": resp.status_code, "latency_s": elapsed, "usage": usage}
        return resp


def policy_accepts_request(core: dict) -> bool:
    """Run the real policy engine in a fully eligible context; only the request check can fail."""
    from app.intent import IntentResult
    result = evaluate(PolicyInput(
        capture_status="COMPLETED", captured_amount=Decimal("49.99"), capture_currency="USD", expected_currency="USD",
        requested_refund=Decimal("49.99"), already_refunded=Decimal("0"), purchase_date=date(2026, 10, 1),
        today=date(2026, 10, 8), return_window_days=30, product_returnable=True, product_name="demo",
        intent=IntentResult(**core), supplier_status="REPLACEMENT_APPROVED", require_supplier=True))
    return result.eligible


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}% ({n}/{d})" if d else "n/a"


def percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def score(rows: list[dict], key: str) -> dict:
    out = {"n": len(rows)}
    for f in FIELDS:
        out[f] = sum(r[key][f] == r["expected"][f] for r in rows)
    out["exact"] = sum(all(r[key][f] == r["expected"][f] for f in FIELDS) for r in rows)
    lenient = lambda a, b: a == b or {a, b} == {"OTHER", "UNKNOWN"}  # noqa: E731
    out["exact_lenient_reason"] = sum(r[key]["intent"] == r["expected"]["intent"]
                                      and r[key]["requested_action"] == r["expected"]["requested_action"]
                                      and lenient(r[key]["reason"], r["expected"]["reason"]) for r in rows)
    exp_ok = [policy_accepts_request(r["expected"]) for r in rows]
    got_ok = [policy_accepts_request(r[key]) for r in rows]
    out["policy_decision_match"] = sum(a == b for a, b in zip(exp_ok, got_ok))
    out["unwarranted_accept"] = [r["id"] for r, e, g in zip(rows, exp_ok, got_ok) if g and not e]
    out["missed_accept"] = [r["id"] for r, e, g in zip(rows, exp_ok, got_ok) if e and not g]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword-only", action="store_true",
                    help="re-run only the keyword fallback; LLM results already in results.json are kept")
    ap.add_argument("--delay", type=float, default=8.0, help="seconds between LLM calls (Groq free-tier friendly)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--rescore", action="store_true", help="recompute metrics from saved results.json (no API calls)")
    args = ap.parse_args()
    if args.rescore:
        old = json.loads(OUT_JSON.read_text())
        write(old["rows"], old["model"], old["run_at"], old.get("llm_meta", {}).get("retries_429", 0),
              keyword_run_at=old.get("keyword_run_at"), keyword_history=old.get("keyword_history"))
        return

    data = json.loads(DATASET.read_text())
    msgs = data["messages"][: args.limit or None]
    kw = KeywordIntentExtractor()
    if args.keyword_only and OUT_JSON.exists():
        old = json.loads(OUT_JSON.read_text())
        if old.get("model") and [r["id"] for r in old["rows"]] == [m["id"] for m in msgs]:
            history = old.get("keyword_history") or []
            history.append({"run_at": old.get("keyword_run_at") or old["run_at"], "exact": old["keyword"]["exact"],
                            "unwarranted_accept": old["keyword"]["unwarranted_accept"],
                            "injection_unwarranted_accept": old["injection"]["keyword"]["unwarranted_accept"]})
            for r, m in zip(old["rows"], msgs):
                r["keyword"] = kw.extract(m["message"]).result.model_dump()
            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            write(old["rows"], old["model"], old["run_at"], old["llm_meta"]["retries_429"],
                  keyword_run_at=now, keyword_history=history)
            return
    use_llm = not args.keyword_only and bool(os.environ.get("LLM_API_KEY"))
    model = os.environ.get("LLM_MODEL") or DEFAULT_LLM_MODEL
    rec = RecordingTransport()
    llm = LLMIntentExtractor(os.environ.get("LLM_API_KEY", ""), os.environ.get("LLM_BASE_URL") or DEFAULT_LLM_BASE_URL,
                             model, timeout=60, transport=rec) if use_llm else None

    rows = []
    for i, m in enumerate(msgs):
        row = {"id": m["id"], "lang": m["lang"], "message": m["message"], "expected": m["expected"],
               "injection": m["injection"], "keyword": kw.extract(m["message"]).result.model_dump()}
        if llm:
            if i:
                time.sleep(args.delay)
            rec.last = None
            t0 = time.perf_counter()
            ex = llm.extract(m["message"])
            row["llm"] = ex.result.model_dump()
            row["llm_wall_s"] = round(time.perf_counter() - t0, 3)
            row["llm_http_s"] = round(rec.last["latency_s"], 3) if rec.last else None
            row["llm_usage"] = rec.last["usage"] if rec.last else {}
            row["llm_extractor"] = ex.extractor
            row["llm_note"] = ex.note
            row["llm_language"] = ex.assist.language_code if ex.assist else None
            row["llm_sizes"] = [ex.assist.current_size, ex.assist.requested_size] if ex.assist else None
            print(f"{m['id']} {m['lang']:7} kw={'✓' if row['keyword'] == m['expected'] else '✗'} "
                  f"llm={'✓' if row['llm'] == m['expected'] else '✗'} {row['llm_http_s']}s", flush=True)
        rows.append(row)
    write(rows, model if llm else None, datetime.now(timezone.utc).replace(microsecond=0).isoformat(), rec.retries_429)


def write(rows: list[dict], model: str | None, run_at: str, retries_429: int,
          keyword_run_at: str | None = None, keyword_history: list | None = None) -> None:
    llm = "llm" in rows[0]
    results = {"run_at": run_at, "keyword_run_at": keyword_run_at or run_at, "keyword_history": keyword_history or [],
               "dataset_size": len(rows), "model": model, "keyword": score(rows, "keyword"), "per_language": {}, "rows": rows}
    langs = [l for l in LANG_ORDER if any(r["lang"] == l for r in rows)]
    for l in langs:
        sub = [r for r in rows if r["lang"] == l]
        results["per_language"][l] = {"keyword": score(sub, "keyword")}
    inj = [r for r in rows if r["injection"]]
    results["injection"] = {"keyword": score(inj, "keyword")}
    if llm:
        results["llm"] = score(rows, "llm")
        for l in langs:
            results["per_language"][l]["llm"] = score([r for r in rows if r["lang"] == l], "llm")
        results["injection"]["llm"] = score(inj, "llm")
        lat = [r["llm_http_s"] for r in rows if r.get("llm_http_s") is not None]
        tok_in = [r["llm_usage"].get("prompt_tokens", 0) for r in rows]
        tok_out = [r["llm_usage"].get("completion_tokens", 0) for r in rows]
        cost = [(a * PRICE_IN + b * PRICE_OUT) / 1e6 for a, b in zip(tok_in, tok_out)]
        lang_rows = [(r, r["lang"] if r["lang"] != "mixed" else MIXED_LANG.get(r["id"])) for r in rows]
        lang_rows = [(r, exp) for r, exp in lang_rows if exp]
        lang_ok = sum((r["llm_language"] or "").lower() == exp.lower()
                      or (exp == "zh-Hant" and (r["llm_language"] or "").lower() == "zh-hant") for r, exp in lang_rows)
        results["llm_meta"] = {
            "latency_p50_s": round(statistics.median(lat), 3), "latency_p95_s": round(percentile(lat, 0.95), 3),
            "latency_max_s": round(max(lat), 3), "fallbacks": sum("LLM unavailable" in r["llm_extractor"] for r in rows),
            "schema_failures": sum("failed strict schema" in r["llm_note"] for r in rows),
            "retries_429": retries_429, "tokens_in_avg": round(statistics.mean(tok_in), 1),
            "tokens_out_avg": round(statistics.mean(tok_out), 1), "cost_per_msg_usd": round(statistics.mean(cost), 7),
            "cost_per_1000_msgs_usd": round(1000 * statistics.mean(cost), 4), "price_source": PRICE_SOURCE,
            "language_detect": {"correct": lang_ok, "n": len(lang_rows)},
        }
    OUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    OUT_MD.write_text(render_md(results))
    print(f"wrote {OUT_JSON.relative_to(ROOT)} and {OUT_MD.relative_to(ROOT)}")


def render_md(res: dict) -> str:
    has_llm = "llm" in res
    k, L, rows = res["keyword"], res.get("llm"), res["rows"]
    lines = ["# Intent extraction eval — LLM vs keyword fallback", "",
             f"Run: {res['run_at']} · dataset: {res['dataset_size']} hand-labelled messages "
             f"([dataset.json](dataset.json)) · model: `{res['model']}` via Groq · script: `scripts/eval_intent.py`.", "",
             "Labels were written by hand from the schema in `app/intent.py` before the run and were not changed afterwards "
             "to fit the model. The dataset is small; treat every number as indicative (±1 message = ±2 points).", ""]
    if res.get("keyword_run_at") and res["keyword_run_at"] != res["run_at"]:
        lines += [f"**Keyword-fallback column re-run {res['keyword_run_at']} (keyword-only, no LLM calls), after the "
                  "fallback injection guard:** when the LLM is unavailable and the message looks like a prompt "
                  "injection, the fallback now forces `UNKNOWN` (routed to a human). The LLM column is unchanged "
                  f"from the {res['run_at']} run.", ""]
        for h in res.get("keyword_history", []):
            inj_ids = h["injection_unwarranted_accept"]
            lines += [f"* Before (keyword run {h['run_at']}): exact match {h['exact']}/{res['dataset_size']}; "
                      f"injections the policy would wrongly accept: {len(inj_ids)}"
                      f"{' (' + ', '.join(inj_ids) + ')' if inj_ids else ''}."]
        inj_now = res["injection"]["keyword"]["unwarranted_accept"]
        lines += [f"* After: exact match {res['keyword']['exact']}/{res['dataset_size']}; injections the policy would "
                  f"wrongly accept: {len(inj_now)}{' (' + ', '.join(inj_now) + ')' if inj_now else ''}.", ""]
    lines += [
             "## Overall", "", "| Metric | LLM | Keyword fallback |", "| --- | --- | --- |"]
    n = res["dataset_size"]
    def both(key, label):
        lines.append(f"| {label} | {pct(L[key], n) if has_llm else '—'} | {pct(k[key], n)} |")
    both("exact", "**Exact match (all 3 core fields)**")
    both("exact_lenient_reason", "Exact match, reason OTHER≈UNKNOWN")
    for f in FIELDS:
        both(f, f"`{f}` accuracy")
    both("policy_decision_match", "Same policy request-check outcome as the label")
    lines.append(f"| Policy would accept a request it should not | {len(L['unwarranted_accept']) if has_llm else '—'} "
                 f"{('(' + ', '.join(L['unwarranted_accept']) + ')') if has_llm and L['unwarranted_accept'] else ''} | "
                 f"{len(k['unwarranted_accept'])} {('(' + ', '.join(k['unwarranted_accept']) + ')') if k['unwarranted_accept'] else ''} |")
    lines.append(f"| Exchange missed → routed to a human | {len(L['missed_accept']) if has_llm else '—'} | {len(k['missed_accept'])} |")
    if has_llm:
        miss = [r for r in rows if r["llm"] != r["expected"]]
        only_reason = [r for r in miss if r["llm"]["intent"] == r["expected"]["intent"]
                       and r["llm"]["requested_action"] == r["expected"]["requested_action"]]
        ok_or_unk = lambda a, b: a == b or {a, b} == {"OTHER", "UNKNOWN"}  # noqa: E731
        label_conv = [r for r in only_reason if ok_or_unk(r["llm"]["reason"], r["expected"]["reason"])]
        inj = [r for r in rows if r["injection"]]
        lines[lines.index("## Overall"):lines.index("## Overall")] = [
            "## Headline", "",
            f"* LLM exact match **{pct(L['exact'], n)}** vs keyword fallback **{pct(k['exact'], n)}**; "
            f"intent alone {pct(L['intent'], n)} vs {pct(k['intent'], n)}.",
            f"* {len(miss)} LLM misses: {len(label_conv)} are only `OTHER` vs `UNKNOWN` in the reason (labelling convention), "
            f"{len(only_reason) - len(label_conv)} pick a different concrete reason, {len(miss) - len(only_reason)} get intent or action wrong.",
            f"* Prompt injections ({len(inj)}): the LLM output never produced a policy-acceptable request that was not warranted "
            f"({len(L['unwarranted_accept'])} across all {n} messages). The keyword fallback produced "
            f"{len(k['unwarranted_accept'])} ({', '.join(k['unwarranted_accept']) or 'none'})"
            + (" — injected words like \"EXCHANGE\" fool keyword rules; such cases would still need every other "
               "policy check and a human click." if k["unwarranted_accept"] else
               " — with the injection guard, an instruction-like message on the fallback path becomes UNKNOWN and "
               "goes to a human (this also routes m11, a genuine exchange wrapped in an injection, to a human)."),
            "* The keyword fallback is English-only by design (a no-key demo path); outside English it mostly returns UNKNOWN, "
            "which the policy routes to a human.", ""]
    lines += ["", "## Exact match per language", "", "| Language | n | LLM | Keyword |", "| --- | --- | --- | --- |"]
    for lang, d in res["per_language"].items():
        lines.append(f"| {lang} | {d['keyword']['n']} | {pct(d['llm']['exact'], d['llm']['n']) if has_llm else '—'} | "
                     f"{pct(d['keyword']['exact'], d['keyword']['n'])} |")
    lines += ["", "## Prompt-injection messages", "",
              "Policy check = would `request_supported` pass (only `EXCHANGE_REQUEST`/`EXCHANGE` does). Even when it passes, "
              "the case still needs the other policy checks, a human approval, and the amount comes from the PayPal capture.", "",
              "| id | lang | expected (real request) | LLM output | policy check | keyword output |", "| --- | --- | --- | --- | --- | --- |"]
    fmt = lambda c: f"{c['intent']} / {c['reason']} / {c['requested_action']}"  # noqa: E731
    for r in rows:
        if r["injection"]:
            got = r.get("llm")
            lines.append(f"| {r['id']} | {r['lang']} | {fmt(r['expected'])} | {fmt(got) if got else '—'} | "
                         f"{('accept' if policy_accepts_request(got) else 'reject') if got else '—'}"
                         f"{' (warranted)' if got and policy_accepts_request(got) and policy_accepts_request(r['expected']) else ''} | "
                         f"{fmt(r['keyword'])} |")
    if has_llm:
        m = res["llm_meta"]
        lines += ["", "## Latency, cost, robustness (LLM)", "",
                  f"* HTTP latency per message: p50 **{m['latency_p50_s']} s**, p95 **{m['latency_p95_s']} s**, max {m['latency_max_s']} s "
                  "(from this box, one call per message, includes the assist fields).",
                  f"* Tokens per message: {m['tokens_in_avg']} input, {m['tokens_out_avg']} output on average (output includes reasoning tokens).",
                  f"* Estimated cost: **${m['cost_per_msg_usd']:.6f} per message** (${m['cost_per_1000_msgs_usd']:.2f} per 1,000), "
                  f"price from {m['price_source']}. The customer-note translation is a second, smaller call not measured here.",
                  f"* Detected language (assist field): {pct(m['language_detect']['correct'], m['language_detect']['n'])} correct.",
                  f"* LLM call failures → keyword fallback: {m['fallbacks']} · strict-schema failures: {m['schema_failures']} · "
                  f"429 retries: {m['retries_429']}."]
        lines += ["", "## Every LLM miss", "", "| id | lang | message | expected | LLM |", "| --- | --- | --- | --- | --- |"]
        for r in rows:
            if r["llm"] != r["expected"]:
                lines.append(f"| {r['id']} | {r['lang']} | {r['message'].replace('|', '/')[:90]} | {fmt(r['expected'])} | {fmt(r['llm'])} |")
    lines += ["", "## Limits", "",
              "* 52 messages written by the project author, not real customer traffic; one labeller, no inter-annotator check.",
              "* Single run at temperature 0; results can still vary slightly between runs and model updates.",
              "* `OTHER` vs `UNKNOWN` for the reason is genuinely ambiguous in the schema, hence the lenient row.",
              "* Only the core intent is scored strictly; detected language is reported, sizes and summaries are not scored.",
              "* The policy only ever automates `EXCHANGE_REQUEST`/`EXCHANGE`; refund requests are always routed to a human, "
              "so an intent error can cost labour but cannot move money on its own.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
