"""Generate the held-out routing set with an LLM that never sees the routing rules.

    python scripts/generate_heldout.py --model qwen/qwen3.8-27b

The prompt is docs/eval/heldout-generation-prompt.md (business description only). Raw output (with model,
timestamp and prompt SHA-256) goes to docs/eval/heldout-raw.json. Labels are added by hand afterwards
(docs/eval/heldout-labels.json) following docs/eval/heldout-labelling-guide.md, before any pipeline run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import Settings  # noqa: E402

PROMPT_DOC = ROOT / "docs" / "eval" / "heldout-generation-prompt.md"
OUT = ROOT / "docs" / "eval" / "heldout-raw.json"


def load_prompt() -> tuple[str, str, list[str]]:
    text = PROMPT_DOC.read_text()
    system = re.search(r"SYSTEM:\n(.*?)\n\nUSER", text, re.S).group(1).strip()
    user = re.search(r"USER \(.*?\):\n\n(.*?)\nBatch briefs", text, re.S).group(1).strip()
    briefs = re.findall(r"^\d\. (.*?)(?=^\d\. |\Z)", text.split("Batch briefs")[1], re.S | re.M)
    return system, user, [" ".join(b.split()) for b in briefs]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen/qwen3.8-27b")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--batch", type=int, help="only run this batch (1-based) and APPEND it as a top-up")
    args = ap.parse_args()
    s = Settings.from_env()
    system, user_tpl, briefs = load_prompt()
    out = {"generator_model": args.model, "provider": s.llm_base_url,
           "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
           "prompt_sha256": hashlib.sha256(PROMPT_DOC.read_bytes()).hexdigest(), "batches": []}
    with httpx.Client(timeout=120) as client:
        existing = json.loads(OUT.read_text()) if args.batch else None
        todo = [(args.batch, briefs[args.batch - 1])] if args.batch else list(enumerate(briefs, 1))
        for i, brief in todo:
            user = user_tpl.replace("{N}", str(args.n)).replace("{BATCH_BRIEF}", brief)
            for attempt in range(5):
                r = client.post(f"{s.llm_base_url}/chat/completions",
                                headers={"Authorization": f"Bearer {s.llm_api_key}"},
                                json={"model": args.model, "temperature": 0.9,
                                      "response_format": {"type": "json_object"},
                                      "messages": [{"role": "system", "content": system},
                                                   {"role": "user", "content": user}]})
                if r.status_code == 429:
                    time.sleep(float(r.headers.get("retry-after", "15") or 15) + 1)
                    continue
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
                content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
                try:
                    msgs = json.loads(content)["messages"]
                    break
                except (ValueError, KeyError):
                    continue
            else:
                sys.exit(f"batch {i} failed")
            entry = {"batch": i, "brief": brief, "messages": msgs}
            if existing:
                entry.update(top_up=True, generator_model=args.model, generated_at=out["generated_at"],
                             note=f"top-up: requested {args.n} more because the first call returned fewer")
            out["batches"].append(entry)
            print(f"batch {i}: {len(msgs)} messages", flush=True)
            time.sleep(5)
    if existing:
        existing["batches"] += out["batches"]
        out = existing
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
