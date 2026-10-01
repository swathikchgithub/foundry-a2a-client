"""
Foundry side: create a prompt agent that has the A2A tool pointing at the
Ticket Triage Agent, then talk to it.

Commands:
  python foundry_client.py create            # create/update the Foundry agent (new version)
  python foundry_client.py ask "ticket text"  # one-shot question
  python foundry_client.py chat              # interactive multi-turn chat
  python foundry_client.py delete            # delete all versions of the agent

Auth: uses DefaultAzureCredential, so run `az login` first.
"""

import argparse
import os
import sys

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import A2AProtocolVersion, A2ATool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()

INSTRUCTIONS = """You are a helpdesk orchestrator for an IT service desk.

When the user describes an IT problem or pastes a support ticket, ALWAYS call the
Ticket Triage Agent (the A2A tool) with the ticket text, verbatim. Use its result to:
1. State the category, priority and the team the ticket is routed to.
2. Give the user 2-3 practical first steps they can try while they wait.
3. If the category is Security_Phishing, tell them to disconnect from the network
   and not to enter any credentials, before anything else.

Never invent a category or priority yourself -- only report what the triage agent returned.
For questions that are not IT tickets, answer directly without calling the tool."""


def env(name: str) -> str:
    value = os.getenv(name)
    if not value or "<" in value:
        sys.exit(f"Set {name} in .env (see .env.example)")
    return value


def get_project() -> AIProjectClient:
    return AIProjectClient(endpoint=env("PROJECT_ENDPOINT"), credential=DefaultAzureCredential())


def agent_name() -> str:
    return os.getenv("FOUNDRY_AGENT_NAME", "helpdesk-orchestrator")


def create(project: AIProjectClient) -> None:
    connection = project.connections.get(env("A2A_CONNECTION_NAME"))
    print(f"Using A2A connection: {connection.name} ({connection.id})")

    tool = A2ATool(a2a_version=A2AProtocolVersion.V1_0, project_connection_id=connection.id)
    agent = project.agents.create_version(
        agent_name=agent_name(),
        definition=PromptAgentDefinition(
            model=env("MODEL_DEPLOYMENT_NAME"),
            instructions=INSTRUCTIONS,
            tools=[tool],
        ),
    )
    print(f"Agent ready: name={agent.name} version={agent.version} id={agent.id}")


def respond(openai, text: str, conversation_id: str | None = None) -> str:
    kwargs = {"conversation": conversation_id} if conversation_id else {}
    response = openai.responses.create(
        input=text,
        extra_body={"agent_reference": {"name": agent_name(), "type": "agent_reference"}},
        **kwargs,
    )
    for item in response.output:
        if item.type != "message":
            print(f"  [tool activity: {item.type}]")
    return response.output_text


def ask(project: AIProjectClient, text: str) -> None:
    openai = project.get_openai_client()
    print(respond(openai, text))


def chat(project: AIProjectClient) -> None:
    openai = project.get_openai_client()
    conversation = openai.conversations.create()
    print(f"Chatting with '{agent_name()}' (conversation {conversation.id}). Ctrl+C or 'exit' to quit.\n")
    try:
        while True:
            text = input("you> ").strip()
            if text.lower() in {"exit", "quit"}:
                break
            if text:
                print(f"\nagent> {respond(openai, text, conversation.id)}\n")
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        openai.conversations.delete(conversation_id=conversation.id)


def delete(project: AIProjectClient) -> None:
    project.agents.delete(agent_name=agent_name())
    print(f"Deleted agent '{agent_name()}'")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("create")
    sub.add_parser("chat")
    sub.add_parser("delete")
    ask_parser = sub.add_parser("ask")
    ask_parser.add_argument("text")
    args = parser.parse_args()

    with get_project() as project:
        if args.command == "create":
            create(project)
        elif args.command == "ask":
            ask(project, args.text)
        elif args.command == "chat":
            chat(project)
        elif args.command == "delete":
            delete(project)


if __name__ == "__main__":
    main()
