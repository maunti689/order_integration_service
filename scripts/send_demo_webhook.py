import argparse
import json
from datetime import datetime, timezone

import httpx

from app.core.config import get_settings
from app.core.security import sign_webhook


def main() -> None:
    parser = argparse.ArgumentParser(description="Отправить подписанный webhook поставщика")
    parser.add_argument("order_id")
    parser.add_argument("status", choices=["confirmed", "fulfilled", "rejected", "failed"])
    parser.add_argument("--api-url", default="http://localhost:8000")
    args = parser.parse_args()

    payload = {
        "event_id": f"demo-{args.status}-{args.order_id}",
        "event_type": f"order.{args.status}",
        "order_id": args.order_id,
        "status": args.status,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    raw_payload = json.dumps(payload, separators=(",", ":")).encode()
    signature = sign_webhook(raw_payload, get_settings().provider_webhook_secret)
    response = httpx.post(
        f"{args.api_url.rstrip('/')}/webhooks/provider",
        content=raw_payload,
        headers={
            "Content-Type": "application/json",
            "X-Provider-Signature": signature,
        },
        timeout=5,
    )
    print(response.status_code, response.text)


if __name__ == "__main__":
    main()
