"""Build held-out v3 messages file, compute Cohen's kappa per field (judge N vs judge D, + each vs design), and adjudicate.
Adjudication rule (guide v3.2, fixed before labelling): judges agree -> label; judges disagree and design agrees with one ->
that 2-of-3 majority, recorded; all three differ -> author adjudication from docs/eval/v3/heldout-v4-author-adjudication.json
(reason required). CREATE_SUPPLIER_TASK is never acceptable for a non-task label.
  python scripts/v3/heldout_v4_labels.py messages | labels"""
import json, sys
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
E = ROOT / "docs/eval/v3"
T = "CREATE_SUPPLIER_TASK"


def kappa(a, b):
    n = len(a)
    if not n:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(a) | set(b)) / n / n
    return round((po - pe) / (1 - pe), 3) if pe < 1 else 1.0


def fields(j):
    it = (j.get("items") or [{}])[0]
    g = (it.get("goals") or [{}])[0].get("goal", "NONE") if it else "NONE"
    return {"required_action": j["required_action"], "speech_act": j["speech_act"],
            "safety_flag": "SAFETY" if j["safety"] != "NONE" else "NONE", "issue_type": it.get("issue_type", "NONE"),
            "first_goal": g, "order_ref_hedged": str(j.get("order_ref_hedged")), "deciding_rule": j.get("deciding_rule")}


def messages():
    design = json.loads((E / "heldout-v4-design.json").read_text())
    raw = json.loads((E / "heldout-v4-raw.json").read_text())["cells"]
    out, missing = [], []
    for c in design["cells"]:
        r = raw.get(c["id"]) or {}
        if not r.get("message"):
            missing.append(c["id"]); continue
        out.append({"id": c["id"], "message": r["message"], "customer": c["customer"], "linked_order": c["linked_order"],
                    "lang": c["lang"], "kind": c["kind"], "slice": c["slice"], "designed_action": c["designed_action"],
                    "generator": r["generator"], "reassigned_from": r.get("reassigned_from")})
    (E / "heldout-v4-messages.json").write_text(json.dumps({"status": "LLM-generated (non-gpt-oss families via NVIDIA); "
        "MOCK data", "n": len(out), "not_generated": missing, "messages": out}, ensure_ascii=False, indent=1))
    print(len(out), "messages; not generated:", missing)


def labels():
    msgs = json.loads((E / "heldout-v4-messages.json").read_text())["messages"]
    J = {k: json.loads((E / f"judge-heldout_v4-{k}.json").read_text())["labels"] for k in ("N", "G")}
    JM = json.loads((E / "judge-heldout_v4-M.json").read_text())["labels"]  # partial (muse-glimmer stalled), reported only
    auth_p = E / "heldout-v4-author-adjudication.json"
    auth = json.loads(auth_p.read_text()) if auth_p.exists() else {}
    final, dis, need = {}, [], []
    for m in msgs:
        i = m["id"]; n, d = J["N"].get(i), J["G"].get(i)
        des = m["designed_action"]
        if not n or not d:
            need.append(i); continue
        an, ad = n["required_action"], d["required_action"]
        if an == ad:
            req, src = an, "judges agree" + (" + design" if an == des else " (design differs)")
            acc = (set(n.get("acceptable_actions") or []) & set(d.get("acceptable_actions") or [])) | {req}
        elif des in (an, ad):
            req, src = des, "2 of 3 (design + one judge)"
            acc = {req}
            dis.append({"id": i, "N": an, "D": ad, "design": des, "final": req, "source": src})
        elif i in auth:
            req, src = auth[i]["required_action"], "author-adjudicated: " + auth[i]["reason"]
            acc = set(auth[i].get("acceptable_actions") or []) | {req}
            dis.append({"id": i, "N": an, "D": ad, "design": des, "final": req, "source": src})
        else:
            need.append(i); continue
        if req != T:
            acc.discard(T)
        final[i] = {"required_action": req, "acceptable_actions": sorted(acc), "source": src, "lang": m["lang"],
                    "kind": m["kind"], "slice": m["slice"], "designed_action": des, "judge_N": an, "judge_G": ad, "judge_M_partial": (JM.get(i) or {}).get("required_action"),
                    "safety_case": m["slice"] in ("safety", "unmapped") or req == "HUMAN_REVIEW" and (n.get("deciding_rule") in ("SG", "V1") or d.get("deciding_rule") in ("SG", "V1")) or n["safety"] != "NONE" or d["safety"] != "NONE",
                    "flag_for_human_review": m["slice"] in ("safety", "unmapped", "low_risk_malfunction", "gated_no_malfunction") or an != ad}
    ids = [m["id"] for m in msgs if m["id"] in J["N"] and m["id"] in J["G"]]
    F = {k: [fields(J[k][i]) for i in ids] for k in ("N", "G")}
    des = {m["id"]: m["designed_action"] for m in msgs}
    kap = {f: kappa([x[f] for x in F["N"]], [x[f] for x in F["G"]]) for f in F["N"][0]}
    mi = [i for i in ids if i in JM]
    kap["required_action_N_vs_M_partial(n=%d)" % len(mi)] = kappa([J["N"][i]["required_action"] for i in mi], [JM[i]["required_action"] for i in mi])
    kap["required_action_N_vs_design"] = kappa([x["required_action"] for x in F["N"]], [des[i] for i in ids])
    kap["required_action_G_vs_design"] = kappa([x["required_action"] for x in F["G"]], [des[i] for i in ids])
    agree = sum(J["N"][i]["required_action"] == J["G"][i]["required_action"] for i in ids)
    (E / "heldout-v4-agreement.json").write_text(json.dumps({"n_both": len(ids), "raw_action_agreement": agree,
                                                             "kappa": kap}, indent=1))
    (E / "heldout-v4-disagreements.json").write_text(json.dumps(dis, ensure_ascii=False, indent=1))
    comp = Counter(v["required_action"] for v in final.values())
    out = {"status": "LLM-generated, dual-LLM-labelled (nemotron-3-super + gemma-4-31b-it, guide v3.2), adjudicated "
                     "(2-of-3 with design, author for 3-way splits), pending human review",
           "n": len(final), "composition": dict(comp), "non_supplier": sum(T not in v["acceptable_actions"] for v in final.values()),
           "safety_cases": sum(v["safety_case"] for v in final.values()),
           "by_lang": dict(Counter(v["lang"] for v in final.values())),
           "by_source": dict(Counter(v["source"].split(":")[0] for v in final.values())), "labels": final}
    (E / "heldout-v4-labels.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "labels"}, indent=1)); print("kappa", kap, "agree", agree, "/", len(ids))
    print("NEED author adjudication:", need)
    for i in need:
        m = next(x for x in msgs if x["id"] == i)
        print(i, m["kind"], "N", (J["N"].get(i) or {}).get("required_action"), "D", (J["G"].get(i) or {}).get("required_action"),
              "design", m["designed_action"], "|", m["message"][:300].replace("\n", " "))


if __name__ == "__main__":
    {"messages": messages, "labels": labels}[sys.argv[1]]()
