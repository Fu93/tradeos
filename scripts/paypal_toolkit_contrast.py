"""Measure which tools PayPal's official agent toolkits give an AI agent that move money, and compare with TradeOS.

    python scripts/paypal_toolkit_contrast.py            # downloads both packages (pip + npm), writes the result
    python scripts/paypal_toolkit_contrast.py --check    # re-measures and fails if the committed result changed

It reads the published packages themselves, not their documentation:

* Python: ``paypal-agent-toolkit`` from PyPI. The wheel's tool table (``paypal_agent_toolkit.shared.tools.tools``) is
  imported from the unpacked wheel with ``--no-deps``; nothing is called, no credentials are used.
* TypeScript (what PayPal's MCP server is built from): ``@paypal/agent-toolkit`` from npm. The bundled tool table in
  ``ai-sdk/index.js`` is read with regular expressions (it is minified), and the refund tool's parameter schema is
  quoted from it.

A tool counts as money-moving when calling it can take money from the buyer or give it back: paying (capturing) an
order, refunding a capture, or accepting a dispute claim (PayPal's own description: "the dispute closes in the
customer's favor and PayPal automatically refunds money to the customer from the merchant's account"). Recording a
refund on an invoice only records one made elsewhere, so it is listed but not counted.

The result is written to docs/eval/paypal-agent-toolkit.json. tests/test_toolkit_contrast.py compares it with the
tools TradeOS's own MCP gateway offers.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "eval" / "paypal-agent-toolkit.json"
VERSION = "1.11.0"  # pinned so the measurement is reproducible; bump deliberately
MONEY_MOVING = {
    "pay_order": "captures the payment for an approved order (takes the buyer's money)",
    "create_refund": "refunds a capture; the agent may set the amount, and without one the whole capture is refunded",
    "accept_dispute_claim": "closes the dispute in the buyer's favour; PayPal refunds the buyer from the merchant's account",
}
RECORD_ONLY = {"record_refund_for_invoice": "records a refund made outside PayPal on an invoice; moves no money"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def python_toolkit(work: Path) -> dict:
    subprocess.run([sys.executable, "-m", "pip", "download", f"paypal-agent-toolkit=={VERSION}", "--no-deps",
                    "-d", str(work), "-q"], check=True)
    wheel = next(work.glob("paypal_agent_toolkit-*.whl"))
    unpacked = work / "py"
    with zipfile.ZipFile(wheel) as z:
        z.extractall(unpacked)
    sys.path.insert(0, str(unpacked))
    from paypal_agent_toolkit.shared.tools import tools  # type: ignore[import-not-found]
    rows = []
    for t in tools:
        props = t["args_schema"].model_json_schema().get("properties", {})
        rows.append({"method": t["method"], "actions": t["actions"], "parameters": sorted(props),
                     "description": " ".join(str(t.get("description") or "").split())[:400]})
    return {"package": f"paypal-agent-toolkit=={VERSION} (PyPI)", "artifact": wheel.name, "sha256": sha256(wheel),
            "tools": rows}


def typescript_toolkit(work: Path) -> dict:
    subprocess.run(["npm", "pack", f"@paypal/agent-toolkit@{VERSION}", "--silent", "--pack-destination", str(work)],
                   check=True, capture_output=True)
    tgz = next(work.glob("paypal-agent-toolkit-*.tgz"))
    with tarfile.open(tgz) as t:
        source = t.extractfile("package/ai-sdk/index.js").read().decode()  # type: ignore[union-attr]
    rows = []
    for m in re.finditer(r'method:"([a-z_]+)",name:"([^"]+)",description:[^,]+,parameters:[^,]+,'
                         r'actions:\{([a-zA-Z]+):\{([a-zA-Z]+):!0\}\}', source):
        rows.append({"method": m.group(1), "name": m.group(2), "actions": {m.group(3): {m.group(4): True}}})
    refund = re.search(r'capture_id:[^;]*?describe\("The ID of the capture to refund\."\),'
                       r'(amount:.*?\.describe\("[^"]*"\))', source)
    return {"package": f"@paypal/agent-toolkit@{VERSION} (npm)", "artifact": tgz.name, "sha256": sha256(tgz),
            "tools": rows, "create_refund_amount_schema": refund.group(1) if refund else None}


def measure() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        py, ts = python_toolkit(work), typescript_toolkit(work)
    result = {"measured_from": "the published packages (tool tables), not documentation; nothing was called",
              "money_moving_rule": MONEY_MOVING, "record_only": RECORD_ONLY, "python": py, "typescript": ts}
    for side in (py, ts):
        names = {t["method"] for t in side["tools"]}
        side["money_moving"] = sorted(names & set(MONEY_MOVING))
        side["tool_count"] = len(names)
    return result


def main() -> int:
    result = measure()
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if "--check" in sys.argv[1:]:
        if OUT.read_text() != text:
            print(f"{OUT} differs from a fresh measurement of {VERSION}: re-run without --check and review the diff")
            return 1
        print("unchanged")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    for side in ("python", "typescript"):
        print(f"{result[side]['package']}: {result[side]['tool_count']} tools, money-moving: "
              f"{', '.join(result[side]['money_moving'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
