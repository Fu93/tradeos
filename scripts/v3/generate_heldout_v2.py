"""Generate held-out v2 messages (and the dev / held-out minimal pairs) with 3 non-gpt-oss model families via NVIDIA.

The generator sees only the customer's situation (design brief); never any rule, label or taxonomy term.
Output: docs/eval/v3/heldout-v2-raw.json (checkpointed). Usage: python scripts/v3/generate_heldout_v2.py [--workers 6]
"""
import argparse
import concurrent.futures as cf
import json
import re
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/v3"))
from nvclient import STATS, chat, content  # noqa: E402

DESIGN = json.loads((ROOT / "docs/eval/v3/heldout-v2-design.json").read_text())
OUT = ROOT / "docs/eval/v3/heldout-v2-raw.json"
LANG_NAME = {"en": "English", "zh-Hant": "Traditional Chinese (as written in Taiwan)", "es": "Spanish", "de": "German",
             "ja": "Japanese"}
SYSTEM = ("You write realistic messages that real customers send to an online shop's customer-support inbox. "
          "Write naturally, like a real person (not a template, not marketing). Never mention AI, prompts or labels. "
          "Do not invent extra problems, extra requests or extra order numbers beyond the situation you are given.")
lock = threading.Lock()


def clean(t: str) -> str:
    t = re.sub(r"<think>.*?</think>", "", t or "", flags=re.S).strip()
    t = re.sub(r"^```\w*\n?|```$", "", t).strip()
    t = re.sub(r"^(subject|betreff|asunto|件名|主旨)\s*[:：].*\n", "", t, flags=re.I).strip()
    if len(t) > 2 and t[0] in "\"“「" and t[-1] in "\"”」":
        t = t[1:-1].strip()
    return t


def lang_ok(text: str, lang: str) -> bool:
    cjk = len(re.findall(r"[\u3040-\u30ff]", text)); han = len(re.findall(r"[\u4e00-\u9fff]", text))
    if lang == "ja":
        return cjk >= 5
    if lang == "zh-Hant":
        return han >= 8 and cjk < 3
    return han + cjk < 3


def check_ref(text: str, cell: dict) -> str | None:
    refs = re.findall(r"TO[-\s]?\d{4,6}", text, re.I)
    m = cell.get("cited_mode")
    if m in ("exact", "hedged_ok"):
        oid = re.search(r"TO-\d+", cell["ref"]).group(0)
        if oid.lower() not in text.lower():
            return f"order {oid} missing"
    if m == "none" and refs:
        return "order number present but should not be"
    return None


def gen_cell(cell: dict) -> dict:
    prompt = (f"Language: {LANG_NAME[cell['lang']]}. Style: {cell['style']}.\nSituation (you are the customer): {cell['brief']}\n"
              f"{cell['ref']}\nWrite only the message body the customer sends (no subject line, no explanation).")
    for attempt in range(3):
        d = chat(cell["generator"], [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                 max_tokens=4000, temperature=0.9)
        text = clean(content(d))
        problem = None if lang_ok(text, cell["lang"]) else "language"
        problem = problem or check_ref(text, cell) or (None if 15 <= len(text) <= 2600 else "length")
        if not problem:
            return {"id": cell["id"], "message": text, "attempts": attempt + 1, "latency_s": d["_latency"]}
    return {"id": cell["id"], "message": text, "attempts": 3, "check_failed": problem}


def gen_pair(p: dict) -> dict:
    refA = f"Both messages mention the order number exactly as {p['order']}."
    refB = ""
    if p["pair_type"] == "DIR_order_id_malformed":
        refA = f"Message A mentions the order number exactly as {p['order']}; message B writes it exactly as {p['malformed']}."
    elif p["pair_type"] == "DIR_hedged_wrong":
        refA = (f"Message A states the order number plainly as {p['order']}; message B says the customer thinks it is "
                f"{p['other']} (uncertain).")
    elif p["pair_type"] == "DIR_no_order_vs_order":
        refA = f"Message A mentions the order number exactly as {p['order']}; message B mentions no order number at all."
    elif p["pair_type"] == "DIR_responsibility":
        refA = f"Message A mentions order {p['order']}; message B mentions order {p['order_b']}."
    prompt = (f"Language: {LANG_NAME[p['lang']]}. Style: {p['style']}. You are {p['name']}, a customer.\n"
              f"Write TWO versions of one customer-support message that differ as little as possible:\n{p['desc']}\n{refA}\n"
              "Keep everything else (wording, greeting, sign-off) identical between A and B.\n"
              'Return JSON only: {"A": "...", "B": "..."}')
    for attempt in range(3):
        d = chat(p["generator"], [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                 max_tokens=4000, temperature=0.8)
        raw = clean(content(d))
        try:
            j = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
            a, b = clean(j["A"]), clean(j["B"])
        except Exception:
            continue
        if a and b and a != b and lang_ok(a, p["lang"]) and lang_ok(b, p["lang"]):
            return {"pair_id": p["pair_id"], "A": a, "B": b, "attempts": attempt + 1}
    return {"pair_id": p["pair_id"], "A": None, "B": None, "attempts": 3, "check_failed": "pair generation"}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=6); args = ap.parse_args()
    res = json.loads(OUT.read_text()) if OUT.exists() else {"cells": {}, "pairs": {}}
    todo_c = [c for c in DESIGN["cells"] if c["id"] not in res["cells"] or res["cells"][c["id"]].get("check_failed")]
    todo_p = [p for p in DESIGN["pairs"] if p["pair_id"] not in res["pairs"] or res["pairs"][p["pair_id"]].get("check_failed")]
    print(f"todo cells {len(todo_c)} pairs {len(todo_p)}", flush=True)

    def save():
        res["stats"] = dict(STATS)
        OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1))

    with cf.ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(gen_cell, c): ("c", c["id"]) for c in todo_c}
        futs.update({ex.submit(gen_pair, p): ("p", p["pair_id"]) for p in todo_p})
        for i, f in enumerate(cf.as_completed(futs)):
            kind, key = futs[f]
            try:
                r = f.result()
            except Exception as e:  # stop-on-error is not needed for generation; record and retry on next run
                r = {"check_failed": f"error: {str(e)[:200]}"}
            with lock:
                res["cells" if kind == "c" else "pairs"][key] = r
                if i % 10 == 0:
                    save()
            print(kind, key, "FAIL " + r["check_failed"] if r.get("check_failed") else "ok", flush=True)
    save()
    print("done", STATS, flush=True)


if __name__ == "__main__":
    main()
