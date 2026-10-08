"""One-off: register the PayPal Sandbox webhook for the refund confirmation.

Usage (needs PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET in the environment):

    python scripts/register_webhook.py https://tradeos-s33z.onrender.com/webhooks/paypal

Idempotent: if a webhook with that URL already exists on the app, it is reused.
Prints the webhook ID; set it as PAYPAL_WEBHOOK_ID on the server (not a secret,
but configured via env and never committed).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import SANDBOX_BASE_URL  # noqa: E402
from app.paypal_client import PayPalClient  # noqa: E402

EVENTS = ["PAYMENT.CAPTURE.REFUNDED"]


def main(url: str) -> None:
    pp = PayPalClient(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"],
                      os.environ.get("PAYPAL_BASE_URL") or SANDBOX_BASE_URL)
    for hook in pp.list_webhooks().get("webhooks", []):
        if hook.get("url") == url:
            print(f"exists  PAYPAL_WEBHOOK_ID={hook['id']}  events={[e['name'] for e in hook['event_types']]}")
            return
    hook = pp.create_webhook(url, EVENTS)
    print(f"created PAYPAL_WEBHOOK_ID={hook['id']}  events={[e['name'] for e in hook['event_types']]}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].startswith("https://"):
        sys.exit("usage: register_webhook.py https://<public-host>/webhooks/paypal")
    main(sys.argv[1])
