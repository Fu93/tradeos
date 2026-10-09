"""Generate held-out v3 messages with 4 non-gpt-oss model families via NVIDIA (generator sees only the situation brief).
Output docs/eval/v3/heldout-v3-raw.json (checkpointed). If a cell's generator fails 3 times (throttling / bad output) it is
reassigned to the next family and the reassignment is RECORDED (never silent). Normalisation-trap cells get their order id
rewritten with the designed hyphen / width variant after generation."""
import argparse, concurrent.futures as cf, json, re, sys, threading
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/v3"))
from nvclient import STATS, chat, content  # noqa: E402
from generate_heldout_v2 import LANG_NAME, SYSTEM, clean, lang_ok  # noqa: E402

DESIGN = json.loads((ROOT / "docs/eval/v3/heldout-v3-design.json").read_text())
OUT = ROOT / "docs/eval/v3/heldout-v3-raw.json"
GENS = ["nvidia/nemotron-3-super-120b-a12b", "deepseek-ai/deepseek-v4.1-flash", "meta/muse-glimmer-30b", "google/gemma-4-31b-it"]
SLOW = "google/gemma-4-31b-it"
lock = threading.Lock()
FW = str.maketrans("TO-0123456789", "ＴＯ－０１２３４５６７８９")


def check(text, c):
    m = c["cited_mode"]
    if m == "exact" and c["order"].lower() not in text.lower().replace(" ", "").replace("‐", "-"):
        return "order missing"
    if m in ("malformed", "hedged_bad", "other") and c["cited_other"].lower() not in text.lower():
        return "cited code missing"
    if m == "none" and re.search(r"TO[-\s]?\d{4,6}", text, re.I):
        return "order present"
    if c["kind"] == "safety_fuse" and c["lang"] == "ja" and "fuse" not in text.lower():
        return "fuse word missing"
    return None


def variant(text, c):
    v = c.get("id_variant")
    if not v:
        return text
    oid = c["cited_other"] if c["cited_mode"] == "hedged_bad" else c["order"]
    rep = oid.translate(FW) if v == "fullwidth" else oid.replace("-", v)
    return re.sub(re.escape(oid), rep, text, flags=re.I)


def gen(c):
    prompt = (f"Language: {LANG_NAME[c['lang']]}. Style: {c['style']}.\nSituation (you are the customer): {c['brief']}\n{c['ref']}\n"
              "Write only the message body the customer sends (no subject line, no explanation).")
    log = []
    order = [c["generator"]] + [g for g in GENS if g != c["generator"]]
    if c["generator"] == SLOW:  # deviation (recorded): gemma-4 timed out / took >150 s per call on the shared endpoint
        order = [GENS[int(c["id"][1:]) % 3]] + [g for g in GENS[:3] if g != GENS[int(c["id"][1:]) % 3]]
        log.append("gemma-4-31b-it skipped: endpoint too slow (recorded reassignment)")
    for model in order[:3]:
        for attempt in range(3):
            try:
                d = chat(model, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}], retries=4,
                         max_tokens=4000, temperature=0.9)
            except Exception as e:
                log.append(f"{model}: {str(e)[:80]}"); break
            t = clean(content(d))
            prob = (None if lang_ok(t, c["lang"]) else "language") or check(t, c) or (None if 15 <= len(t) <= 2600 else "length")
            if not prob:
                return {"id": c["id"], "message": variant(t, c), "generator": model, "attempts": attempt + 1,
                        "reassigned_from": c["generator"] if model != c["generator"] else None, "log": log}
            log.append(f"{model}: {prob}")
    return {"id": c["id"], "check_failed": "; ".join(log[-3:])}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=12); a = ap.parse_args()
    res = json.loads(OUT.read_text()) if OUT.exists() else {"cells": {}}
    todo = [c for c in DESIGN["cells"] if not res["cells"].get(c["id"], {}).get("message")]
    print("todo", len(todo), flush=True)
    with cf.ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(gen, c): c["id"] for c in todo}
        for f in cf.as_completed(futs):
            r = f.result()
            with lock:
                res["cells"][futs[f]] = r; res["stats"] = dict(STATS)
                OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1))
            print(futs[f], r.get("generator", "FAIL " + str(r.get("check_failed"))), flush=True)
    print("done", STATS, flush=True)


if __name__ == "__main__":
    main()
