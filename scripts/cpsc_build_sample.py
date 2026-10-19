"""Build the real-text safety sample from CPSC's public SaferProducts.gov export (SPDB.zip -> IncidentReports.csv).

  python scripts/cpsc_build_sample.py /path/to/IncidentReports.csv --out docs/eval/cpsc_real_text_sample.jsonl

Source: "Download all recalls and unsafe product reports" on https://www.saferproducts.gov/PublicSearch (file SPDB.zip).
The copy used here is the Internet Archive capture of that official file taken 2026-02-24
(https://web.archive.org/web/20260224175618id_/https://www.saferproducts.gov/SPDB.zip, sha256
4d72f3fdfdf0db6e6e9691cdaa001e6d861807995b623db9adb9a9f7f0a68352), because saferproducts.gov refuses requests from
our build machine (HTTP 403 from its CDN). Terms: "Information publicly posted on Saferproducts.gov is considered
public information and may be distributed or copied" (https://www.saferproducts.gov/Business/Acknowledge, section 3).

Sampling is fixed in advance and does not look at what the Safety Gate does with a row:
consumer submitters only, narrative 60-500 characters (500 = the app's FREE_TEXT_MAX_CHARS default), deaths
excluded, then a seeded random draw of 35 injury reports, 35 "Incident, No Injury" and 30 "No Incident, No Injury".
Labels are added by hand afterwards (see docs/eval/cpsc_real_text.md for the rubric); this script writes label=null.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import random
import sys

SEED = 20261019
STRATA = (("injury", 35), ("incident_no_injury", 35), ("no_incident_no_injury", 30))


def stratum(sev: str) -> str | None:
    if sev.startswith("Injury"):
        return "injury"
    if sev == "Incident, No Injury":
        return "incident_no_injury"
    if sev == "No Incident, No Injury":
        return "no_incident_no_injury"
    return None  # Death, Unspecified: excluded


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    csv.field_size_limit(sys.maxsize)
    text = open(a.csv_path, encoding="utf-8-sig", errors="replace").read()
    body = text.split("\n", 1)[1]  # first line is CPSC's disclaimer, not the header
    pools: dict[str, list[dict]] = {s: [] for s, _ in STRATA}
    seen: set[str] = set()
    for r in csv.DictReader(io.StringIO(body)):
        msg = " ".join((r.get("Incident Description") or "").split())
        s = stratum(r.get("(Primary) Victim Severity") or "")
        if s is None or r.get("Category of Submitter") != "Consumer" or not 60 <= len(msg) <= 500:
            continue
        if msg.lower() in seen:
            continue
        seen.add(msg.lower())
        pools[s].append({"report_no": r["Report No."], "stratum": s, "severity": r["(Primary) Victim Severity"],
                         "product": (r.get("Product Description") or "").strip()[:120],
                         "product_category": (r.get("Product Category") or "").strip(),
                         "product_sub_category": (r.get("Product Sub Category") or "").strip(),
                         "message": msg})
    rng = random.Random(SEED)
    out = []
    for s, n in STRATA:
        pool = sorted(pools[s], key=lambda x: x["report_no"])
        out.extend(rng.sample(pool, n))
    with open(a.out, "w", encoding="utf-8") as f:
        for i, row in enumerate(out, 1):
            f.write(json.dumps({"id": i, **row, "label_escalate": None, "label_note": ""}, ensure_ascii=False) + "\n")
    print(f"wrote {len(out)} rows; pool sizes: " + ", ".join(f"{s}={len(p)}" for s, p in pools.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
