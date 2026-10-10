"""Register (or update) the PayPal Sandbox webhook for TradeOS. Idempotent.

    python scripts/register_webhook.py https://tradeos-s33z.onrender.com/webhooks/paypal            # dry run
    python scripts/register_webhook.py https://tradeos-s33z.onrender.com/webhooks/paypal --apply    # change it

- If a webhook with that URL already exists on the app, its event list is replaced in place
  (PATCH /v1/notifications/webhooks/{id}), so the webhook ID, and PAYPAL_WEBHOOK_ID, stay the same.
- Only if none exists is a new one created; then set the printed ID as PAYPAL_WEBHOOK_ID on the server.
Needs PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET (and optionally PAYPAL_BASE_URL) in the environment.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import SANDBOX_BASE_URL  # noqa: E402
from app.paypal_client import PayPalClient  # noqa: E402

EVENTS = [
    "PAYMENT.CAPTURE.REFUNDED",   # refund completed -> may move PENDING to COMPLETED
    "PAYMENT.REFUND.PENDING",     # refund pending (e.g. ECHECK)
    "PAYMENT.REFUND.FAILED",      # refund failed -> needs a human
    "PAYMENT.CAPTURE.REVERSED",   # log-only warning
    "PAYMENT.CAPTURE.DECLINED",   # log-only warning
]


def plan(pp, url: str) -> tuple[str, str | None, list[str], list[str]]:
    """Returns (action, webhook_id, current_events, wanted_events); action in create/update/none."""
    for hook in pp.list_webhooks().get("webhooks", []):
        if hook.get("url") == url:
            current = sorted(e["name"] for e in hook.get("event_types", []))
            return ("none" if current == sorted(EVENTS) else "update"), hook["id"], current, sorted(EVENTS)
    return "create", None, [], sorted(EVENTS)


def main(pp, url: str, apply: bool) -> dict:
    action, hook_id, current, wanted = plan(pp, url)
    print(f"webhook url: {url}")
    print(f"current: id={hook_id} events={current}")
    print(f"wanted : events={wanted}")
    if action == "none":
        print(f"no change. PAYPAL_WEBHOOK_ID={hook_id} (unchanged)")
    elif not apply:
        print(f"DRY RUN: would {action} " + (f"webhook {hook_id} in place (ID unchanged)" if hook_id else "a new webhook")
              + ". Re-run with --apply.")
    elif action == "update":
        hook = pp.update_webhook_events(hook_id, EVENTS)
        print(f"updated PAYPAL_WEBHOOK_ID={hook.get('id', hook_id)} (unchanged) events="
              f"{sorted(e['name'] for e in hook.get('event_types', []))}")
    else:
        hook = pp.create_webhook(url, EVENTS)
        hook_id = hook["id"]
        print(f"created PAYPAL_WEBHOOK_ID={hook_id} -> set this on the server")
    return {"action": action, "id": hook_id, "applied": apply or action == "none"}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--apply"]
    if len(args) != 1 or not args[0].startswith("https://"):
        sys.exit("usage: register_webhook.py https://<public-host>/webhooks/paypal [--apply]")
    client = PayPalClient(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"],
                          os.environ.get("PAYPAL_BASE_URL") or SANDBOX_BASE_URL)
    main(client, args[0], "--apply" in sys.argv)
