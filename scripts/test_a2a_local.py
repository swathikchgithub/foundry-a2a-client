"""
Smoke-test the A2A agent directly (no Foundry involved), the same way Foundry
will call it: fetch the agent card, then send an A2A v1.0 JSON-RPC SendMessage.

Usage:
  python scripts/test_a2a_local.py                       # hits A2A_PUBLIC_URL from .env
  python scripts/test_a2a_local.py --url http://localhost:8000 "printer is jammed"
"""

import argparse
import os
import sys
import uuid

import httpx
from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ticket", nargs="?", default="My laptop connects to wifi but shows no internet access.")
    parser.add_argument("--url", default=os.getenv("A2A_PUBLIC_URL", "http://localhost:8000"))
    args = parser.parse_args()
    base = args.url.rstrip("/")
    api_key = os.getenv("A2A_API_KEY", "")

    with httpx.Client(timeout=30) as client:
        card = client.get(f"{base}/.well-known/agent-card.json")
        card.raise_for_status()
        card = card.json()
        print(f"Agent card OK: {card['name']} -> {card['supportedInterfaces'][0]['url']}")

        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "SendMessage",
            "params": {
                "message": {
                    "messageId": str(uuid.uuid4()),
                    "role": "ROLE_USER",
                    "parts": [{"text": args.ticket}],
                }
            },
        }
        resp = client.post(
            f"{base}/",
            json=payload,
            headers={"x-api-key": api_key, "A2A-Version": "1.0"},
        )
        if resp.status_code != 200:
            print(f"HTTP {resp.status_code}: {resp.text}")
            return 1
        body = resp.json()
        if "error" in body:
            print(f"JSON-RPC error: {body['error']}")
            return 1

        result = body["result"]
        message = result.get("message") or result.get("task", {}).get("status", {}).get("message", {})
        text = "\n".join(p.get("text", "") for p in message.get("parts", []))
        print(f"\nTicket: {args.ticket}\n\n{text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
