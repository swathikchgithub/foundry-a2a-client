# foundry-a2a-client

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![A2A](https://img.shields.io/badge/A2A_protocol-v1.0-green)

Agent-to-Agent (**A2A v1.0**) communication between an **Azure AI Foundry agent** and an
agent running on **your laptop**, in both directions. It's built to run locally first and
deploy to the cloud later.

| Direction | Who calls whom | Commands |
|---|---|---|
| **A. Foundry → local** | A Foundry agent uses the built-in A2A tool to call the Ticket Triage Agent on your laptop | `foundry_client.py create / ask / chat` |
| **B. Local → Foundry** | A script on your laptop calls the Foundry agent's own A2A endpoint | `foundry_client.py enable-a2a` + `scripts/call_foundry_agent.py` |

---

## Use case: IT helpdesk triage

An employee writes: *"I clicked a link in a weird email and it asked for my password. Urgent!"*

1. The **Foundry agent** (`helpdesk-orchestrator`, a GPT model in Azure) recognises an IT
   ticket and calls the **Ticket Triage Agent** over A2A.
2. The **Ticket Triage Agent** replies:
   `Category: Security_Phishing · Priority: P1 · Route to: Security Operations`.
3. The Foundry agent turns that into a helpful answer, for example: *"Disconnect from the network and don't
   enter any credentials. I've flagged this as P1 for Security Operations…"*

Think of it as a **receptionist** (the Foundry agent talks to the user) and a **specialist**
(the triage agent does one job well). A2A is the standard protocol they use, so either side
can be replaced without rewriting the other.

**Why split into two agents?**
- The specialist can be **your own model**. You can swap the keyword triage for a fine-tuned classifier.
- It can be **owned by another team** or run on another platform and still plug in.
- **Many agents can reuse it**: a helpdesk bot, an email bot, an ITSM integration.

---

## Architecture

**Direction A: Foundry calls your laptop**

```
 you ──► foundry_client.py ──► Foundry agent "helpdesk-orchestrator"  (Azure, gpt-4.1-mini)
                                     │  A2A tool (v1.0 JSON-RPC, x-api-key header)
                                     │  via project connection "ticket-triage-a2a"
                                     ▼
                         HTTPS tunnel  (Dev Tunnels / ngrok)
                                     ▼
                  a2a_agent/server.py on your laptop  ("Ticket Triage Agent")
```

The tunnel is only needed because Azure can't reach `localhost`. Once the triage agent is
deployed to the cloud, the tunnel goes away.

**Direction B: your laptop calls Foundry**

```
 scripts/call_foundry_agent.py ──A2A SendMessage + Entra token──►
     https://<account>.services.ai.azure.com/api/projects/<project>/agents/<agent>/endpoint/protocols/a2a
```

This direction needs no tunnel or connection, because your laptop calls out to Azure.

---

## Project structure

```
foundry-a2a-client/
├── a2a_agent/
│   ├── server.py             # A2A v1.0 server (official a2a-sdk): agent card + JSON-RPC, x-api-key auth
│   └── triage.py             # ticket triage logic (keyword-based, no GPU; swap for a real model)
├── scripts/
│   ├── test_a2a_local.py     # call the local A2A agent directly, the way Foundry will
│   └── call_foundry_agent.py # direction B: A2A client that calls a Foundry agent
├── foundry_client.py         # Foundry side: create / ask / chat / enable-a2a / delete
├── requirements.txt
├── .env.example              # all settings, documented
└── LICENSE
```

---

## Prerequisites

- Python 3.10+
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli), signed in with `az login`
- A Foundry project (new Foundry) with a model deployment, for example `gpt-4.1-mini`
- Azure roles on the project:
  - **Foundry Project Manager** to create the A2A connection (direction A)
  - **Foundry User** to create and run the agent
  - **Foundry Agent Consumer** (or higher) to call the agent over A2A (direction B)
- For direction A only, a tunnel: [Microsoft Dev Tunnels](https://learn.microsoft.com/azure/developer/dev-tunnels/get-started) or [ngrok](https://ngrok.com/download)

## Install

```bash
git clone https://github.com/swathikchgithub/foundry-a2a-client.git
cd foundry-a2a-client
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

## Configuration (`.env`)

| Variable | Used by | Description |
|---|---|---|
| `A2A_PORT` | local agent | Port the local A2A server listens on (default `8000`) |
| `A2A_PUBLIC_URL` | local agent | Public URL advertised in the agent card (your tunnel URL) |
| `A2A_API_KEY` | local agent | Shared secret Foundry must send as `x-api-key`. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `PROJECT_ENDPOINT` | Foundry | Project endpoint from the Foundry portal's **Overview** page |
| `MODEL_DEPLOYMENT_NAME` | Foundry | Model deployment name, for example `gpt-4.1-mini` |
| `A2A_CONNECTION_NAME` | Foundry | Name of the A2A connection in Foundry (default `ticket-triage-a2a`) |
| `FOUNDRY_AGENT_NAME` | Foundry | Name of the Foundry agent (default `helpdesk-orchestrator`) |

`.env` is git-ignored, so it never gets committed.

---

## Direction A: Foundry agent → local agent

### A1. Run the local A2A agent
```bash
python -m a2a_agent.server
```
In a second terminal:
```bash
python scripts/test_a2a_local.py --url http://localhost:8000 "I clicked a link in a suspicious email, urgent"
```
Expected output: `Category: Security_Phishing / Priority: P1 / Route to: Security Operations`.

### A2. Expose it over public HTTPS
```bash
# Dev Tunnels
devtunnel user login
devtunnel host -p 8000 --allow-anonymous      # copy the https://...devtunnels.ms URL

# or ngrok
ngrok http 8000                               # copy the https://...ngrok-free.app URL
```
`--allow-anonymous` only skips the tunnel's own login page. The server still rejects any
request without your `x-api-key`. The agent card is the only exception, because it's public by design.

### A3. Point the agent card at the tunnel
Set `A2A_PUBLIC_URL=<tunnel URL>` in `.env`, **restart the server**, then check the agent
through the tunnel:
```bash
python scripts/test_a2a_local.py
```

### A4. Create the A2A connection in Foundry
**Portal:** go to [ai.azure.com](https://ai.azure.com) (New Foundry toggle on), open your project, then **Tools** →
**Connect tool** → **Custom** → **Agent2Agent (A2A)** → **Create**.
- **Name:** `ticket-triage-a2a` (must match `A2A_CONNECTION_NAME`)
- **A2A Agent Endpoint:** your tunnel URL
- **Authentication:** key-based. Credential name `x-api-key`, value = your `A2A_API_KEY`

**Or with the Azure Developer CLI:**
```bash
azd ai project set "$PROJECT_ENDPOINT"
azd ai connection create ticket-triage-a2a \
  --kind remote-a2a \
  --target https://<your-tunnel-url> \
  --auth-type custom-keys \
  --custom-key "x-api-key=$A2A_API_KEY"
```

### A5. Create the Foundry agent with the A2A tool
```bash
python foundry_client.py create
```
Each run creates a new **version** of the agent.

### A6. Talk to it
```bash
python foundry_client.py ask "My laptop connects to wifi but shows no internet. Blocking my work."
python foundry_client.py chat
```
**How you know it worked:** the answer includes the category, priority and team, and the
server terminal logs `A2A request (context=...)` at the same moment.

---

## Direction B: local client → Foundry agent

### B1. Create the agent (if you haven't already)
```bash
python foundry_client.py create
```

### B2. Enable incoming A2A on the agent
```bash
python foundry_client.py enable-a2a
```
This calls `project.agents.update_details(...)`, which turns on the A2A protocol on the agent
endpoint and publishes an agent card. It prints the agent's A2A URL. Incoming A2A can't be
enabled in the portal yet; it has to go through the SDK or REST API.

### B3. Grant permission
Assign the **Foundry Agent Consumer** role on the project to the identity you `az login`
with. In the Azure portal, open the Foundry resource → **Access control (IAM)** → **Add role assignment**.

### B4. Call it
```bash
python scripts/call_foundry_agent.py --card                        # print the agent card
python scripts/call_foundry_agent.py "My VPN keeps disconnecting"   # one message
python scripts/call_foundry_agent.py --chat                         # multi-turn (keeps contextId)
python scripts/call_foundry_agent.py --agent other-agent "hi"       # any agent with incoming A2A
```
The script gets an Entra token for `https://ai.azure.com` from your `az login`, fetches the
agent card, and sends an A2A v1.0 JSON-RPC `SendMessage` request.

**Full round trip:** `helpdesk-orchestrator` still has the A2A tool from direction A. If the
local server and tunnel are running, one request goes **laptop → Foundry → laptop → Foundry → laptop**.

**Limits on Foundry's incoming A2A:** v1.0 supports JSON-RPC only, text parts only, and no streaming. Tasks and
contexts are kept for 60 days after their last write.

---

## Command reference

| Command | What it does |
|---|---|
| `python -m a2a_agent.server` | Start the local Ticket Triage A2A agent |
| `python scripts/test_a2a_local.py [--url URL] ["ticket"]` | Call the local agent directly |
| `python foundry_client.py create` | Create a new version of the Foundry agent with the A2A tool |
| `python foundry_client.py ask "text"` | Send one question to the Foundry agent |
| `python foundry_client.py chat` | Multi-turn chat with the Foundry agent |
| `python foundry_client.py enable-a2a` | Expose the Foundry agent as an A2A endpoint |
| `python scripts/call_foundry_agent.py ["text" \| --chat \| --card]` | Call the Foundry agent over A2A |
| `python foundry_client.py delete` | Delete the Foundry agent (all versions) |

## Clean up

```bash
python foundry_client.py delete
```
Then stop the tunnel and the server. Delete the `ticket-triage-a2a` connection in the
portal if you no longer need it.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Server logs `Rejected request ... bad or missing x-api-key` | The connection's credential name must be exactly `x-api-key`, and its value must match `A2A_API_KEY`. |
| Foundry can't reach the agent, or you get TLS errors | Check the tunnel is running and `python scripts/test_a2a_local.py` works against the tunnel URL. |
| Agent answers without calling the tool | Send a clear IT ticket, or add `tool_choice="required"` in `respond()` in `foundry_client.py`. |
| Connection not found | `A2A_CONNECTION_NAME` must match the connection name in Foundry. |
| `DefaultAzureCredential` failed | Run `az login`, and `az account set -s <subscription>` if needed. |
| `call_foundry_agent.py`: 401 | Run `az login`. The token must be for `https://ai.azure.com`. |
| `call_foundry_agent.py`: 403 | Assign the Foundry Agent Consumer role on the project. |
| `call_foundry_agent.py`: 404 | Check the agent name, and run `python foundry_client.py enable-a2a`. |
| The tunnel URL changed | Update `A2A_PUBLIC_URL`, restart the server, and update the connection endpoint in Foundry. |

---

## Roadmap

- [ ] Replace the keyword triage in `a2a_agent/triage.py` with a fine-tuned classifier
      (for example the LoRA TicketSense model)
- [ ] Containerize and deploy the triage agent to Azure Container Apps (drop the tunnel)
- [ ] Switch from the API key to `project-managed-identity` auth once the agent runs in Azure
- [ ] Register the triage agent in Foundry Control Plane for governance and monitoring

**Deployment note:** the server is a plain ASGI app (`a2a_agent.server:app`). Run it with
`uvicorn a2a_agent.server:app --host 0.0.0.0 --port 8000`. Keep `A2A_API_KEY` in Key Vault
or as a Container Apps secret, set `A2A_PUBLIC_URL` to the app URL, and update the Foundry
connection target.

## References

- [Connect to an A2A agent endpoint from Foundry Agent Service](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/agent-to-agent)
- [Enable incoming A2A on a Foundry agent](https://learn.microsoft.com/azure/foundry/agents/how-to/enable-agent-to-agent-endpoint)
- [Agent2Agent (A2A) authentication](https://learn.microsoft.com/azure/foundry/agents/concepts/agent-to-agent-authentication)
- [A2A protocol](https://a2a-protocol.org) · [a2a-python SDK](https://github.com/a2aproject/a2a-python)

## License

This project is licensed under the [MIT License](LICENSE).
