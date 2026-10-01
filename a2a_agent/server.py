"""
Local A2A (protocol v1.0, JSON-RPC) server exposing the ticket triage agent.

Endpoints:
  GET  /.well-known/agent-card.json   agent card (public, no key needed)
  POST /                              JSON-RPC endpoint (requires x-api-key)

Run:
  python -m a2a_agent.server
"""

import logging
import os
import secrets

import uvicorn
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from a2a.helpers import new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH

from a2a_agent.triage import triage

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("a2a_agent")

PORT = int(os.getenv("A2A_PORT", "8000"))
PUBLIC_URL = os.getenv("A2A_PUBLIC_URL", f"http://localhost:{PORT}").rstrip("/")
API_KEY = os.getenv("A2A_API_KEY", "")
API_KEY_HEADER = "x-api-key"


class TriageAgentExecutor(AgentExecutor):
    """Reads the text of the incoming message and replies with one text message."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        ticket = context.get_user_input().strip()
        log.info("A2A request (context=%s): %r", context.context_id, ticket[:200])

        if not ticket:
            reply = "Send me the text of an IT support ticket and I'll classify and route it."
        else:
            reply = triage(ticket).to_text()

        await event_queue.enqueue_event(
            new_text_message(reply, context_id=context.context_id, task_id=context.task_id)
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Triage is synchronous; nothing to cancel.")


def build_agent_card() -> AgentCard:
    return AgentCard(
        name="Ticket Triage Agent",
        description=(
            "Classifies an IT support ticket into one of 8 categories "
            "(Hardware, Software, Network, Access_Account, Password_Reset, Email, "
            "Security_Phishing, Printer) and returns priority and the team to route it to."
        ),
        version="0.1.0",
        supported_interfaces=[
            AgentInterface(url=f"{PUBLIC_URL}/", protocol_binding="JSONRPC", protocol_version="1.0"),
        ],
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id="triage_ticket",
                name="Triage IT ticket",
                description="Given the free-text body of an IT ticket, return category, priority and owning team.",
                tags=["itsm", "helpdesk", "classification", "routing"],
                examples=[
                    "My laptop connects to wifi but shows no internet access.",
                    "I clicked a link in a suspicious email asking for my password.",
                ],
            )
        ],
    )


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Require x-api-key on everything except the public agent card."""

    async def dispatch(self, request, call_next):
        if API_KEY and request.url.path != AGENT_CARD_WELL_KNOWN_PATH:
            supplied = request.headers.get(API_KEY_HEADER, "")
            if not secrets.compare_digest(supplied, API_KEY):
                log.warning("Rejected request to %s: bad or missing %s", request.url.path, API_KEY_HEADER)
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def build_app() -> Starlette:
    card = build_agent_card()
    handler = DefaultRequestHandler(
        agent_executor=TriageAgentExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = create_agent_card_routes(card) + create_jsonrpc_routes(
        handler, rpc_url="/", enable_v0_3_compat=True
    )
    app = Starlette(routes=routes)
    app.add_middleware(ApiKeyMiddleware)
    return app


app = build_app()


if __name__ == "__main__":
    if not API_KEY or API_KEY == "change-me":
        log.warning("A2A_API_KEY is not set to a real secret -- set one in .env before exposing this server.")
    log.info("Agent card: %s%s", PUBLIC_URL, AGENT_CARD_WELL_KNOWN_PATH)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
