"""[ROUND 1 / rules 0.1.x, kept for history. It uses the old complaint_type schema and does not run on rules
0.2.0. Use scripts/eval_routing.py.]

Evaluation of supplier routing (experiment, MVP 1): real pipeline, hand-labelled cases.

    python scripts/eval_routing.py --mode both          # LLM (Groq, throttled) + keyword fallback
    python scripts/eval_routing.py --mode keyword       # no API key needed
    python scripts/eval_routing.py --rescore            # recompute metrics/markdown from the saved JSON

Reads docs/eval/routing-dataset.json (labels written before the first run), runs every case IN ORDER
through app.routing.RoutingService (the same code the dashboard uses) against a fresh SQLite DB per
mode, and writes docs/eval/routing-results.json + docs/eval/routing-results.md.

Metrics
  auto-trigger precision   of the cases routed to SUPPLIER_REQUIRED automatically, share labelled SUPPLIER_REQUIRED
  necessary-case recall    of the cases labelled SUPPLIER_REQUIRED, share routed there automatically
  ambiguous false-trigger  of the 'ambiguous' rows, share routed to SUPPLIER_REQUIRED
  duplicate task rate      of the 'duplicate' rows, share that created a NEW task (should be 0)
  task completeness        of the tasks created, share whose draft holds every field its type needs
  route accuracy           final route == label (strict) / in acceptable_routes (lenient)
  latency                  wall time per case for the whole pipeline (LLM call + rules + SQLite)
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from app.config import Settings  # noqa: E402
from app.routing import (RULE_VERSION, SUPPLIER_REQUIRED, CaseContext, RoutingConfig, RoutingService,  # noqa: E402
                         RoutingStore, task_complete)
from app.routing_extract import KeywordRoutingExtractor, LLMRoutingExtractor  # noqa: E402

DATASET = ROOT / "docs" / "eval" / "routing-dataset.json"
OUT_JSON = ROOT / "docs" / "eval" / "routing-results-round1-rules011.json"  # history
OUT_MD = ROOT / "docs" / "eval" / "routing-results-round1-rules011.md"
FAMILIES = ("EXCHANGE", "RESHIP", "DEFECT", "PART_REPLACEMENT")
LANGS = ("en", "zh-Hant", "es", "de", "ja")
S = SUPPLIER_REQUIRED


class RetryTransport(httpx.BaseTransport):
    """Retries 429 (so throttling never silently becomes a keyword fallback) and counts retries."""

    def __init__(self) -> None:
        self.inner = httpx.HTTPTransport()
        self.retries_429 = 0
        self.tokens = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        for _ in range(8):
            resp = self.inner.handle_request(request)
            resp.read()
            if resp.status_code != 429:
                break
            self.retries_429 += 1
            time.sleep(min(float(resp.headers.get("retry-after", "10") or 10), 60) + 1)
        try:
            usage = json.loads(resp.content).get("usage") or {}
            if usage:
                self.tokens.append(usage.get("total_tokens", 0))
        except ValueError:
            pass
        return resp


def run_mode(mode: str, cases: list[dict], delay: float, settings: Settings) -> dict:
    db = Path(tempfile.mkdtemp()) / f"eval-{mode}.db"
    store = RoutingStore(str(db))
    store.init(reset=True)
    transport = None
    if mode == "llm":
        transport = RetryTransport()
        extractor = LLMRoutingExtractor(settings.llm_api_key, settings.llm_base_url, settings.llm_model,
                                        transport=transport)
    else:
        extractor = KeywordRoutingExtractor()
    svc = RoutingService(store, extractor, RoutingConfig())
    rows = []
    for i, c in enumerate(cases):
        if mode == "llm" and i:
            time.sleep(delay)
        t0 = time.perf_counter()
        rid = svc.triage(c["message"], CaseContext(customer=c["customer"], linked_order_id=c.get("linked_order")),
                         source="eval")
        wall = round((time.perf_counter() - t0) * 1000, 1)
        rc = store.get_case(rid)
        ex = rc["extraction"] or {}
        task = store.get_task(rc["task_id"]) if rc["task_id"] else None
        new_task = bool(task) and not rc["duplicate_of_task"]
        rows.append({
            "id": c["id"], "family": c["family"], "lang": c["lang"], "tag": c["tags"][0],
            "expected": c["expected_route"], "acceptable": c["acceptable_routes"],
            "expected_new_task": c["expected_new_task"],
            "final": rc["route"], "proposed": rc["proposed_route"], "status": rc["status"],
            "supplier_status": rc["supplier_status"], "confidence": rc["confidence"], "band": rc["band"],
            "llm_confidence": ex.get("llm_confidence"), "extractor": ex.get("extractor"),
            "type": (ex.get("fields") or {}).get("complaint_type"), "kind": (ex.get("fields") or {}).get("request_kind"),
            "new_task": new_task, "duplicate_of": rc["duplicate_of_task"],
            "task_complete": task_complete(task) if new_task else None,
            "stopped_at": next((f"G{g['gate']}: {g['reason']}" for g in (rc["decision"] or {}).get("gates", [])
                                if not g["passed"]), None),
            "latency_ms": wall, "llm_latency_ms": ex.get("latency_ms"),
        })
        print(f"[{mode}] {c['id']} exp={c['expected_route']:<20} got={rc['route']:<20} conf={rc['confidence']} "
              f"{'NEW TASK' if new_task else ''}", flush=True)
    with store.connect() as conn:
        dup_open = conn.execute("SELECT COUNT(*) FROM (SELECT dedup_key FROM supplier_tasks WHERE status='DRAFT_READY' "
                                "GROUP BY dedup_key HAVING COUNT(*) > 1)").fetchone()[0]
    meta = {"mode": mode, "extractor": extractor.name if hasattr(extractor, "name") else mode,
            "run_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "keys_with_more_than_one_open_task": dup_open,
            "retries_429": transport.retries_429 if transport else 0,
            "tokens_p50": statistics.median(transport.tokens) if transport and transport.tokens else None,
            "llm_fallbacks": sum("unavailable" in (r["extractor"] or "") for r in rows),
            "delay_s": delay if mode == "llm" else 0}
    return {"meta": meta, "rows": rows}


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}% ({n}/{d})" if d else "n/a (0/0)"


def q(values, p):
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    k = (len(v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 1)


def score(rows: list[dict]) -> dict:
    trig = [r for r in rows if r["final"] == S]
    need = [r for r in rows if r["expected"] == S]
    amb = [r for r in rows if r["tag"] == "ambiguous"]
    non = [r for r in rows if r["expected"] != S]
    dups = [r for r in rows if r["tag"] == "duplicate"]
    tasks = [r for r in rows if r["new_task"]]
    return {
        "n": len(rows),
        "auto_triggers": len(trig),
        "precision": [sum(r["expected"] == S for r in trig), len(trig)],
        "false_triggers": [r["id"] for r in trig if r["expected"] != S],
        "recall": [sum(r["final"] == S for r in need), len(need)],
        "safe_recall": [sum(r["final"] == S or r["proposed"] == S for r in need), len(need)],
        "missed": [r["id"] for r in need if r["final"] != S],
        "ambiguous_false_trigger": [sum(r["final"] == S for r in amb), len(amb)],
        "non_supplier_false_trigger": [sum(r["final"] == S for r in non), len(non)],
        "duplicate_new_task": [sum(r["new_task"] for r in dups), len(dups)],
        "duplicates_linked": [sum(bool(r["duplicate_of"]) for r in dups), len(dups)],
        "tasks_created": len(tasks),
        "task_precision": [sum(r["expected_new_task"] for r in tasks), len(tasks)],
        "completeness": [sum(bool(r["task_complete"]) for r in tasks), len(tasks)],
        "route_strict": [sum(r["final"] == r["expected"] for r in rows), len(rows)],
        "route_lenient": [sum(r["final"] in r["acceptable"] for r in rows), len(rows)],
        "latency_p50": q([r["latency_ms"] for r in rows], .5), "latency_p95": q([r["latency_ms"] for r in rows], .95),
        "bands": dict(Counter(r["band"] for r in rows)),
        "confusion": {f"{e} -> {g}": n for (e, g), n in sorted(Counter((r["expected"], r["final"]) for r in rows).items())},
    }


def breakdown(rows: list[dict], key: str, values) -> dict:
    return {v: score([r for r in rows if r[key] == v]) for v in values}


def p(x) -> str:
    return pct(*x)


def write(result: dict) -> None:
    for m in result["modes"].values():
        m["overall"] = score(m["rows"])
        m["by_family"] = breakdown(m["rows"], "family", FAMILIES)
        m["by_lang"] = breakdown(m["rows"], "lang", LANGS)
        m["by_tag"] = breakdown(m["rows"], "tag", ("needed", "duplicate", "not_needed", "missing", "ambiguous",
                                                   "similar_order"))
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    OUT_MD.write_text(markdown(result))


def markdown(res: dict) -> str:
    modes = res["modes"]
    L = ["# Supplier routing eval — EXPERIMENT (MVP 1)", "",
         f"Rules `{RULE_VERSION}` · dataset [routing-dataset.json](routing-dataset.json) (100 hand-labelled cases, "
         "25 per type, 20 per language; labels written before the first run) · script `scripts/eval_routing.py`.",
         "All order / inventory / logistics / supplier data is MOCK (`app/routing_data.py`). "
         "Thresholds are initial assumptions (auto ≥ 0.90, human-confirm 0.70–0.89).", ""]
    for name, m in modes.items():
        L.append(f"* **{name}** run {m['meta']['run_at']} · extractor `{m['meta']['extractor']}` · "
                 f"429 retries {m['meta']['retries_429']} · LLM fallbacks {m['meta']['llm_fallbacks']} · "
                 f"delay {m['meta']['delay_s']} s")
    L += ["", "## Headline vs product acceptance targets (targets, not claims)", "",
          "| Metric | Target | " + " | ".join(modes) + " |", "| --- | --- | " + " | ".join("---" for _ in modes) + " |"]
    rows = [("Auto-trigger precision", "≥ 95%", lambda o: p(o["precision"])),
            ("Necessary-case recall (auto)", "—", lambda o: p(o["recall"])),
            ("Necessary-case recall incl. human-confirm", "—", lambda o: p(o["safe_recall"])),
            ("Ambiguous false-trigger rate", "< 2%", lambda o: p(o["ambiguous_false_trigger"])),
            ("False trigger on all non-supplier cases", "—", lambda o: p(o["non_supplier_false_trigger"])),
            ("Duplicate rows that created a new task", "0", lambda o: p(o["duplicate_new_task"])),
            ("Keys with >1 open task (DB)", "0", None),
            ("Task completeness", "100%", lambda o: p(o["completeness"])),
            ("Route accuracy strict / lenient", "—", lambda o: f"{p(o['route_strict'])} / {p(o['route_lenient'])}"),
            ("Latency p50 / p95 per case", "—", lambda o: f"{o['latency_p50']} / {o['latency_p95']} ms")]
    for label, target, fn in rows:
        if fn is None:
            vals = [str(m["meta"]["keys_with_more_than_one_open_task"]) for m in modes.values()]
        else:
            vals = [fn(m["overall"]) for m in modes.values()]
        L.append(f"| {label} | {target} | " + " | ".join(vals) + " |")
    for name, m in modes.items():
        o = m["overall"]
        L += ["", f"## {name}: details", "",
              f"False triggers: {', '.join(o['false_triggers']) or 'none'} · missed necessary: "
              f"{', '.join(o['missed']) or 'none'} · confidence bands: {o['bands']}", "",
              "| Type | n | precision | recall | recall incl. confirm | ambiguous false-trigger | dup → new task | completeness | route strict | lenient |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for k, s in m["by_family"].items():
            L.append(f"| {k} | {s['n']} | {p(s['precision'])} | {p(s['recall'])} | {p(s['safe_recall'])} | "
                     f"{p(s['ambiguous_false_trigger'])} | {p(s['duplicate_new_task'])} | {p(s['completeness'])} | "
                     f"{p(s['route_strict'])} | {p(s['route_lenient'])} |")
        L += ["", "| Language | n | precision | recall | recall incl. confirm | false triggers | route strict | lenient | p50 ms |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for k, s in m["by_lang"].items():
            L.append(f"| {k} | {s['n']} | {p(s['precision'])} | {p(s['recall'])} | {p(s['safe_recall'])} | "
                     f"{len(s['false_triggers'])} | {p(s['route_strict'])} | {p(s['route_lenient'])} | {s['latency_p50']} |")
        L += ["", "| Slice (tag) | n | route strict | lenient | auto triggers |", "| --- | --- | --- | --- | --- |"]
        for k, s in m["by_tag"].items():
            L.append(f"| {k} | {s['n']} | {p(s['route_strict'])} | {p(s['route_lenient'])} | {s['auto_triggers']} |")
        L += ["", "Confusion (label → final route):", ""]
        L += [f"* {k}: {v}" for k, v in o["confusion"].items()]
        wrong = [r for r in m["rows"] if r["final"] not in r["acceptable"]]
        L += ["", f"Rows outside the acceptable routes ({len(wrong)}):", "",
              "| id | lang | label | final | conf | extracted | stopped at |", "| --- | --- | --- | --- | --- | --- | --- |"]
        for r in wrong:
            L.append(f"| {r['id']} | {r['lang']} | {r['expected']} | {r['final']} | {r['confidence']} | "
                     f"{r['type']}/{r['kind']} | {(r['stopped_at'] or '').replace('|', '/')[:140]} |")
    L += ["", "## Reading these numbers", "", res.get("notes", "")]
    return "\n".join(L) + "\n"


NOTES = """* **Run history.** Run 1 (rules 0.1.0, [routing-results-run1.md](routing-results-run1.md)) exposed two code bugs,
  both in deterministic rules, not in the labels: (1) the safety-word regex matched substrings, so German
  "brauche" (contains "rauch" = smoke) sent P04 and P19 to a human as a "safety issue"; (2) when the model picked
  one part number, a second part number in the same message was ignored (P19). Both fixed in rules 0.1.1 with
  regression tests; the labels were not changed. This page is the re-run on 0.1.1. Run 1 LLM headline:
  precision 100% (35/35), auto recall 97.2% (35/36), ambiguous false-trigger 0/16, duplicates 0/8, completeness 27/27.
* **Do not read 100% as "solved".** The re-run scored every row correctly, but run 1 (same labels, same model,
  temperature 0) already differed on D22 (model read a vague remark as a POLICY_QUESTION: still a safe route) — the
  model is not perfectly deterministic, and a self-written, clean dataset cannot show how often real customers
  will be misread. It shows the gates do what they are specified to do on these 100 cases, in 5 languages.
* 100 cases is small: one case moves a per-type number by 4 points and a per-language number by 5.
* The dataset and the rules were written by the same person (the experiment author), so these are
  *consistency* numbers for this rule set on this MOCK data, not field accuracy. Real tickets will be messier.
* Precision/recall measure the full pipeline (LLM extraction + rules). The rules are deterministic, so most
  errors come from extraction (type / request kind / identifiers) or from the confidence band.
* The LLM confidence is a self-report. gpt-oss-20b returns 0.9–0.95 for almost everything, so the threshold
  bands do little on the LLM path; they matter mainly for the keyword fallback (capped at 0.85 => it can never
  auto-trigger) and when identifiers are discarded (−0.25 each). This is documented, not hidden.
* Keyword-fallback numbers are reported for completeness: the fallback is a degraded mode and by design never
  creates supplier tasks on its own (precision is therefore n/a and auto recall 0)."""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("llm", "keyword", "both"), default="both")
    ap.add_argument("--delay", type=float, default=6.0, help="seconds between LLM calls (Groq free tier)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--rescore", action="store_true")
    args = ap.parse_args()
    if args.rescore:
        res = json.loads(OUT_JSON.read_text())
        res["notes"] = NOTES
        write(res)
        return
    load_dotenv()
    settings = Settings.from_env()
    cases = json.loads(DATASET.read_text())["cases"][: args.limit or None]
    modes = ["llm", "keyword"] if args.mode == "both" else [args.mode]
    if "llm" in modes and not settings.llm_configured:
        sys.exit("LLM_API_KEY not set (use --mode keyword)")
    res = {"rule_version": RULE_VERSION, "model": settings.llm_model, "dataset": str(DATASET.relative_to(ROOT)),
           "notes": NOTES, "modes": {}}
    if OUT_JSON.exists() and args.mode != "both":
        res["modes"] = json.loads(OUT_JSON.read_text()).get("modes", {})
    for mode in modes:
        res["modes"][mode] = run_mode(mode, cases, args.delay, settings)
    write(res)
    print(json.dumps({k: v["overall"] for k, v in res["modes"].items()}, indent=1)[:3000])


if __name__ == "__main__":
    main()
