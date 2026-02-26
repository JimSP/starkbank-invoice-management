"""
setup_webhook.py
================
One-time script to register the webhook endpoint on Stark Bank.

    python setup_webhook.py https://your-domain.com/webhook
"""

import sys
import starkbank
from app.config import init_starkbank


def register(url: str) -> starkbank.Webhook:
    """Create a webhook for *url* (or return existing one)."""
    for existing in starkbank.webhook.query():
        if existing.url == url:
            print(f"[OK] Already registered — id={existing.id}  url={existing.url}")
            return existing

    webhook = starkbank.webhook.create(url=url, subscriptions=["invoice"])
    print(f"[OK] Webhook created — id={webhook.id}  url={webhook.url}")
    return webhook


if __name__ == "__main__":  # pragma: no cover
    if len(sys.argv) < 2:
        print("Usage: python setup_webhook.py <public-https-url>")
        sys.exit(1)

    init_starkbank()
    register(sys.argv[1])

    print("\nAll registered webhooks:")
    for w in starkbank.webhook.query():
        print(f"  {w.id}  {w.url}  {w.subscriptions}")
