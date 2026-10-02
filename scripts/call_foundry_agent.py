"""
Reverse direction: a local A2A *client* calling a Foundry agent over A2A v1.0.

  laptop (this script) ──A2A JSON-RPC + Entra token──► Foundry agent's A2A endpoint

No tunnel and no project connection needed -- your laptop calls out to Azure.

Prerequisites:
  1. `python foundry_client.py create` and `python foundry_client.py enable-a2a`
  2. `az login` as an identity with the Foundry Agent Consumer role (or higher) on the project

Usage:
  python scripts/call_foundry_agent.py "My VPN keeps disconnecting"   # one message
  python scripts/call_foundry_agent.py --chat                         # multi-turn (keeps contextId)
  python scripts/call_foundry_agent.py --card                         # just print the agent card

Options:
  --agent NAME   target agent (default: FOUNDRY_AGENT_NAME from .env)
  --url URL      full A2A base URL instead of building it from PROJECT_ENDPOINT
  --no-auth      don't send an Entra token (only for testing against the local server)
"""

import argparse
import json
import os
import sys
import uuid

import httpx
from dotenv import load_dotenv

load_dotenv()

TOKEN_SCOPE = "https://ai.azure.com/.default"
CARD_PATH = "/.well-known/agent-card.json"


def a2a_base_url(args) -> str:
    if args.url:
        return args.url.rstrip("/")
    endpoint = os.getenv("PROJECT_ENDPOINT", "")
    if not endpoint or "<" in endpoint:
        sys.exit("Set PROJECT_ENDPOINT in .env, or pass --url")
    agent = args.agent or os.getenv("FOUNDRY_AGENT_NAME", "helpdesk-orchestrator")
    return f"{endpoint.rstrip('/')}/agents/{agent}/endpoint/protocols/a2a"


def auth_headers(no_auth: bool) -> dict[str, str]:
    if no_auth:
        return {}
    from azure.identity import DefaultAzureCredential

    token = DefaultAzureCredential().get_token(TOKEN_SCOPE).token
    return {"Authorization": f"Bearer {token}"}


def fail(resp: httpx.Response, what: str) -> None:
    hint = {
        401: "Token missing/invalid -- run `az login` (and `az account set -s <subscription>`).",
        403: "Signed-in identity needs the Foundry Agent Consumer role (or higher) on the project.",
        404: "Wrong URL/agent name, or incoming A2A not enabled -- run `python foundry_client.py enable-a2a`.",
    }.get(resp.status_code, "")
    sys.exit(f"{what} failed: HTTP {resp.status_code}\n{resp.text[:2000]}\n{hint}")


def fetch_card(client: httpx.Client, base: str) -> dict:
    resp = client.get(f"{base}{CARD_PATH}")
    if resp.status_code != 200:
        fail(resp, "Agent card fetch")
    return resp.json()


def rpc_url_from_card(card: dict, base: str) -> str:
    """Pick the JSON-RPC v1.0 interface advertised by the card; fall back to the base URL."""
    for iface in card.get("supportedInterfaces", []):
        if iface.get("protocolBinding", "").upper() == "JSONRPC" and str(iface.get("protocolVersion", "")).startswith("1"):
            return iface["url"]
    return card.get("url") or base


def send(client: httpx.Client, rpc_url: str, text: str, context_id: str | None) -> tuple[str, str | None]:
    message = {
        "messageId": str(uuid.uuid4()),
        "role": "ROLE_USER",
        "parts": [{"text": text}],
    }
    if context_id:
        message["contextId"] = context_id

    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "SendMessage",
        "params": {"message": message},
    }
    resp = client.post(rpc_url, json=payload, headers={"A2A-Version": "1.0"})
    if resp.status_code != 200:
        fail(resp, "SendMessage")
    body = resp.json()
    if "error" in body:
        sys.exit(f"JSON-RPC error: {json.dumps(body['error'], indent=2)}")
    return extract_reply(body["result"])


def extract_reply(result: dict) -> tuple[str, str | None]:
    """A v1.0 SendMessage result holds either a `message` or a `task`."""
    if "message" in result:
        msg = result["message"]
        return parts_text(msg.get("parts", [])), msg.get("contextId")

    task = result.get("task", result)
    chunks = [parts_text(a.get("parts", [])) for a in task.get("artifacts", [])]
    status_msg = task.get("status", {}).get("message")
    if not any(chunks) and status_msg:
        chunks.append(parts_text(status_msg.get("parts", [])))
    state = task.get("status", {}).get("state", "")
    text = "\n".join(c for c in chunks if c)
    if state and state not in ("TASK_STATE_COMPLETED", "completed"):
        text = f"[task state: {state}]\n{text}"
    return text, task.get("contextId")


def parts_text(parts: list[dict]) -> str:
    return "\n".join(p["text"] for p in parts if "text" in p)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("text", nargs="?", help="message to send")
    parser.add_argument("--agent")
    parser.add_argument("--url")
    parser.add_argument("--chat", action="store_true")
    parser.add_argument("--card", action="store_true")
    parser.add_argument("--no-auth", action="store_true")
    args = parser.parse_args()
    if not (args.text or args.chat or args.card):
        parser.error("give a message, --chat, or --card")

    base = a2a_base_url(args)
    print(f"A2A target: {base}")

    with httpx.Client(timeout=120, headers=auth_headers(args.no_auth)) as client:
        card = fetch_card(client, base)
        rpc_url = rpc_url_from_card(card, base)
        print(f"Agent: {card.get('name', '?')} -- JSON-RPC at {rpc_url}\n")
        if args.card:
            print(json.dumps(card, indent=2))
            return

        if args.text:
            reply, _ = send(client, rpc_url, args.text, None)
            print(reply)
            return

        print("Multi-turn chat over A2A. Ctrl+C or 'exit' to quit.\n")
        context_id = None
        try:
            while True:
                text = input("you> ").strip()
                if text.lower() in {"exit", "quit"}:
                    break
                if text:
                    reply, context_id = send(client, rpc_url, text, context_id)
                    print(f"\nagent> {reply}\n")
        except (KeyboardInterrupt, EOFError):
            print()


if __name__ == "__main__":
    main()
