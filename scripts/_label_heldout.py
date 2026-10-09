"""One-off: write the author labels for the held-out set (run once, BEFORE any pipeline run)."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
raw = json.loads((ROOT / "docs/eval/heldout-raw.json").read_text())
msgs = [m for b in raw["batches"] for m in b["messages"]]
batch_of = [b["batch"] for b in raw["batches"] for _ in b["messages"]]
assert len(msgs) == 60
H, C, D, T = "HUMAN_REVIEW", "CLARIFY_WITH_CUSTOMER", "DIRECT_WORKFLOW", "CREATE_SUPPLIER_TASK"
# id: (lang_actual, issue, goal, mixed, action, acceptable_actions_extra, category, edge, note)
L = {
 1: ("en", "NO_ISSUE_INQUIRY", "INFORMATION", False, H, [], "negation", True, "'not broken at all' + policy question"),
 2: ("en", "NO_ISSUE_INQUIRY", "INFORMATION", False, H, [], "pre_purchase", False, "sizing advice before buying"),
 3: ("en", "DEFECT", "INFORMATION", False, H, [], "inquiry_about_problem", True, "asks whether a stiff zipper is a defect; generator tagged it 'es' but it is English"),
 4: ("de", "NO_ISSUE_INQUIRY", "INFORMATION", False, H, [], "part_inquiry", True, "part numbers mentioned, only asks if the filter is sold alone"),
 5: ("ja", "DEFECT", "INFORMATION", False, H, [], "negation", True, "possible fault, asks fault vs setting, explicitly does NOT want an exchange"),
 6: ("en", "UNCLEAR", "INFORMATION", False, H, [C], "inquiry_about_problem", True, "metallic taste + asks if filter fits / lid sold separately or missing; questions only"),
 7: ("en", "PART_NEED", "INFORMATION", False, H, [], "part_inquiry", True, "asks if CS-VALVE-2 is in stock; order number lower-case and uncertain"),
 8: ("zh-Hant", "SIZE_MISMATCH", "INFORMATION", False, H, [], "inquiry_about_problem", False, "sleeves short; asks about other sizes and return policy"),
 9: ("es", "NO_ISSUE_INQUIRY", "INFORMATION", False, H, [], "pre_purchase", False, "size range + delivery time"),
 10: ("de", "DEFECT", "INFORMATION", False, H, [], "part_inquiry", True, "lamp flickers; asks whether DL-LED-5W is user-replaceable (question, not an order)"),
 11: ("ja", "SIZE_MISMATCH", "INFORMATION", False, H, [], "inquiry_about_problem", False, "shoes narrow; asks for sizing advice"),
 12: ("en", "DEFECT", "INFORMATION", False, H, [], "inquiry_about_problem", True, "stiff zipper; asks for parts or a fix tip; does not want to return; order no. slightly off"),
 13: ("de", "PART_NEED", "INFORMATION", False, H, [C], "part_inquiry", True, "something broke; asks whether filters or lid KL-170-LID are available (two candidate parts, question form)"),
 14: ("es", "PART_NEED", "INFORMATION", False, H, [], "part_inquiry", False, "asks if DL-CLAMP-M sold alone + shipping to Mexico"),
 15: ("ja", "PART_NEED", "INFORMATION", False, H, [], "part_inquiry", False, "spec question about DL-LED-5W voltage"),
 16: ("en", "SIZE_MISMATCH", "REFUND", False, D, [], "refund_only", False, "too small, refund"),
 17: ("en", "DEFECT", "REFUND", False, D, [], "refund_only", True, "kettle leaking (water, not a safety word), 'just give me my money back'"),
 18: ("en", "SIZE_MISMATCH", "REFUND", False, D, [], "refund_only", False, "cancel + full refund; generator tagged it 'de' but it is English"),
 19: ("de", "DEFECT", "REFUND", False, D, [], "refund_only", False, "poor quality, demands refund; order ref 'WO-40005' is malformed"),
 20: ("es", "UNCLEAR", "REFUND", False, D, [], "refund_only", False, "late delivery, only wants money back; no order number"),
 21: ("es", "NO_ISSUE_INQUIRY", "REFUND", False, D, [], "refund_only", False, "changed mind, wants full refund"),
 22: ("ja", "SIZE_MISMATCH", "REFUND", False, D, [], "refund_only", False, "colour not as wished, refund"),
 23: ("en", "DEFECT", "REFUND", False, D, [], "refund_only", True, "cracked shade; 'I don't want a replacement, just refund'; generator tagged it 'ja' but it is English"),
 24: ("zh-Hant", "SIZE_MISMATCH", "REFUND", False, D, [], "refund_only", False, "return + refund"),
 25: ("zh-Hant", "DEFECT", "REFUND", False, D, [H], "refund_only", True, "gas-stove valve broken, refuses a part, wants refund; no explicit leak/smell, so not labelled safety"),
 26: ("en", "UNCLEAR", "UNCLEAR", True, C, [], "mixed", False, "missing kettle + cracked lamp, undecided refund/replacement"),
 27: ("en", "SIZE_MISMATCH", "UNCLEAR", True, C, [], "mixed", False, "undecided exchange vs return"),
 28: ("en", "DEFECT", "UNCLEAR", True, C, [], "mixed", False, "two defective items, asks how to send back"),
 29: ("zh-Hant", "DEFECT", "UNCLEAR", True, C, [], "mixed", False, "scratches, undecided refund vs exchange to navy"),
 30: ("zh-Hant", "DEFECT", "UNCLEAR", True, C, [], "mixed", True, "socks + lamp on two (one uncertain) orders"),
 31: ("es", "UNCLEAR", "UNCLEAR", True, C, [], "mixed", False, "wrinkled + undecided exchange L / refund"),
 32: ("es", "DEFECT", "REFUND", True, C, [], "mixed", True, "two items (kettle + socks), return both: one goal but two items/orders"),
 33: ("de", "UNCLEAR", "UNCLEAR", True, C, [], "mixed", False, "wrong colour lamp + scratched kettle, exchange or refund?"),
 34: ("de", "DEFECT", "UNCLEAR", True, H, [], "mixed_safety", True, "gas stove 'hat ein Leck' = gas leak -> safety first; also wrong valve, undecided"),
 35: ("ja", "UNCLEAR", "UNCLEAR", True, C, [], "mixed", False, "two lamps blink, refund vs exchange, maybe missing kettle"),
 36: ("en", "SIZE_MISMATCH", "EXCHANGE", False, C, [], "insufficient_info", False, "no order number, no size"),
 37: ("en", "NO_ISSUE_INQUIRY", "INFORMATION", False, H, [C], "insufficient_info", False, "order lookup, order number with an extra digit"),
 38: ("zh-Hant", "DEFECT", "REPAIR", False, C, [], "insufficient_info", True, "lamp does not light, 'replace a part for me', no order/part number"),
 39: ("es", "SIZE_MISMATCH", "REFUND", False, D, [C], "insufficient_info", True, "'quiero devolverlo' (return) = refund flow; no order number (refund flow identifies the order)"),
 40: ("es", "DEFECT", "UNCLEAR", False, C, [H], "insufficient_info", False, "something broken, order number with an extra digit, no outcome"),
 41: ("de", "DEFECT", "UNCLEAR", False, C, [H], "insufficient_info", True, "strange noises, 'Bitte um Hilfe' (help, no outcome)"),
 42: ("de", "DEFECT", "UNCLEAR", False, C, [H], "insufficient_info", False, "jacket broken, wrong order number"),
 43: ("ja", "DEFECT", "REPAIR", False, C, [], "insufficient_info", False, "sole came off, wants it fixed, no order number"),
 44: ("ja", "MISSING_ITEM", "UNCLEAR", False, C, [H], "insufficient_info", True, "part not arriving, order number with an extra digit, no outcome stated"),
 45: ("en", "UNCLEAR", "REFUND", False, D, [], "refund_only", True, "refund for final-sale socks; refund policy decides (it will refuse)"),
 46: ("en", "SIZE_MISMATCH", "EXCHANGE", False, T, [], "clear_request", False, "drop-shipped TRAIL-RUNNER 42->43, 10 days"),
 47: ("zh-Hant", "MISSING_ITEM", "INFORMATION", False, H, [C], "clear_request", True, "rain cover (not a catalog item) missing; 'please confirm'; order shows delivered"),
 48: ("es", "DEFECT", "REPAIR", False, D, [], "clear_request", True, "zipper broke in week 1 (8 days): inside our return window, supplier not needed"),
 49: ("de", "PART_NEED", "BUY_PART", False, C, [H], "clear_request", True, "CS-VALVE-2, no order number (and the writer's order is shoes)"),
 50: ("ja", "PART_NEED", "BUY_PART", False, T, [H], "clear_request", True, "KL-170-LID (0 in stock, supplier supplies parts); note order logistics says LOST"),
 51: ("en", "SIZE_MISMATCH", "EXCHANGE", False, T, [C, H], "clear_request", True, "white lamp -> black (drop-shipped); 'it' could mean the clamp; order has 2 lamps, 1 delivered"),
 52: ("es", "PART_NEED", "BUY_PART", False, C, [], "clear_request", True, "DL-LED-5W 'se quemó' (burned out bulb, not fire); no order number"),
 53: ("de", "PART_NEED", "INFORMATION", False, H, [], "part_inquiry", True, "'can I buy the filter separately?' (same shape as the LED-module regression)"),
 54: ("ja", "PART_NEED", "INFORMATION", False, H, [], "part_inquiry", True, "lost valve, 'is it possible to buy only the part?'"),
 55: ("en", "SIZE_MISMATCH", "EXCHANGE", False, C, [D], "clear_request", True, "final-sale socks, 'different size' without a size"),
 56: ("en", "NO_ISSUE_INQUIRY", "INFORMATION", False, H, [], "negation", False, "'isn't broken at all', product question"),
 57: ("zh-Hant", "NO_ISSUE_INQUIRY", "INFORMATION", False, H, [], "negation", True, "'完全沒有壞掉' + part number, maintenance question"),
 58: ("es", "NO_ISSUE_INQUIRY", "INFORMATION", False, H, [], "pre_purchase", False, "fit question"),
 59: ("de", "NO_ISSUE_INQUIRY", "INFORMATION", False, H, [], "negation", True, "'funktioniert einwandfrei' + hypothetical about the valve"),
 60: ("ja", "NO_ISSUE_INQUIRY", "INFORMATION", False, H, [], "negation", True, "'not arrived' is narrative; hypothetical rumour question about the LED module"),
}
cases = []
for i, m in enumerate(msgs, 1):
    lang, issue, goal, mixed, act, extra, cat, edge, note = L[i]
    cases.append({"id": f"H{i:02d}", "batch": batch_of[i - 1], "message": m["message"], "language": lang,
                  "generator_language_tag": m["language"], "customer": m["customer"],
                  "category": cat, "issue_type": issue, "customer_goal": goal, "mixed": mixed,
                  "required_action": act, "acceptable_actions": [act] + extra,
                  "supplier_task_expected": act == T, "edge_case": edge, "note": note})
out = {"status": "blind-generated, author-labelled, pending human review",
       "generator": {"model": raw["generator_model"], "provider": raw["provider"],
                     "prompt": "docs/eval/heldout-generation-prompt.md", "prompt_sha256": raw["prompt_sha256"]},
       "labelled_by": "experiment author (Grok Bot), following docs/eval/heldout-labelling-guide.md, BEFORE any pipeline run",
       "labelled_at": "2026-10-09",
       "rules": "Labels are frozen in this commit. They are never edited after seeing results; clearly wrong labels go to docs/eval/heldout-label-errata.md.",
       "writer_intent_not_used_as_label": "the generator's writer_intent is in heldout-raw.json only; labels come from the message text + guide",
       "cases": cases}
(ROOT / "docs/eval/heldout-labels.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
