# foundry-a2a-client

Agent-to-Agent (A2A v1.0) between Azure AI Foundry and your laptop, in **both directions**:

| Direction | Who calls whom | Script |
|---|---|---|
| **A. Foundry → local** | Foundry agent uses the A2A tool to call the Ticket Triage Agent on your laptop | `foundry_client.py create / ask / chat` |
| **B. Local → Foundry** | A script on your laptop calls the Foundry agent's own A2A endpoint | `foundry_client.py enable-a2a` + `scripts/call_foundry_agent.py` |

**Direction A:**

```
 you ──► foundry_client.py ──► Foundry agent "helpdesk-orchestrator" (gpt-4.1-mini)
                                     │  A2A tool (v1.0, JSON-RPC, x-api-key)
                                     ▼
                         HTTPS tunnel (devtunnel / ngrok)
                                     ▼
                     a2a_agent/server.py on your laptop  ("Ticket Triage Agent")
```

* `a2a_agent/` is the remote agent. It's a small A2A v1.0 server built on the official
  `a2a-sdk`. It classifies an IT ticket into one of 8 categories and returns the
  priority and owning team. The logic in `triage.py` is a keyword classifier, so it
  runs without a GPU. Swap it for a real model later.
* `foundry_client.py` is the Foundry side. It creates a prompt agent with the A2A tool
  and lets you `ask` it once or `chat` with it.
* `scripts/test_a2a_local.py` calls the A2A agent directly, the way Foundry will.
* `scripts/call_foundry_agent.py` is the direction B client. It calls a Foundry agent over A2A.

---

## Step by step

### 0. Prerequisites

* Python 3.10+
* [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli), signed in with `az login`
* A Foundry project (new Foundry) with a model deployment such as `gpt-4.1-mini`
* Roles on the project: **Foundry Project Manager** to create the connection and
  **Foundry User** to create and run the agent
* A tunnel tool so Foundry (in Azure) can reach your laptop. Use one of:
  * [Microsoft Dev Tunnels](https://learn.microsoft.com/azure/developer/dev-tunnels/get-started): `devtunnel`
  * [ngrok](https://ngrok.com/download)

### 1. Install

```bash
git clone https://github.com/swathikchgithub/foundry-a2a-client.git
cd foundry-a2a-client
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Generate an API key for the A2A agent and put it in `.env` as `A2A_API_KEY`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 2. Run the A2A agent locally

```bash
python -m a2a_agent.server
```

In a second terminal:

```bash
python scripts/test_a2a_local.py --url http://localhost:8000 "I clicked a link in a suspicious email, urgent"
```

You should see `Category: Security_Phishing / Priority: P1 / Route to: Security Operations`.

### 3. Expose it over public HTTPS

Foundry runs in Azure, so it can't call `localhost`. Open a tunnel to port 8000.

**Dev Tunnels**
```bash
devtunnel user login
devtunnel host -p 8000 --allow-anonymous
# copy the "Connect via browser" URL, e.g. https://abc123-8000.usw2.devtunnels.ms
```
`--allow-anonymous` only disables the tunnel's own login page. The server still
rejects any request that doesn't send your `x-api-key`. The agent card is the
only exception, because it's public by design.

**ngrok**
```bash
ngrok http 8000
# copy the https://xxxx.ngrok-free.app URL
```

### 4. Point the agent card at the tunnel

Set the tunnel URL in `.env`, then **restart** the server:

```
A2A_PUBLIC_URL=https://abc123-8000.usw2.devtunnels.ms
```

Verify end to end through the tunnel:

```bash
python scripts/test_a2a_local.py
```

### 5. Create the A2A connection in Foundry

**Portal:**
1. Go to [ai.azure.com](https://ai.azure.com) and make sure the **New Foundry** toggle is on. Open your project.
2. Go to **Tools** → **Connect tool** → **Custom** tab → **Agent2Agent (A2A)** → **Create**.
3. Set **Name** to `ticket-triage-a2a`. This must match `A2A_CONNECTION_NAME` in `.env`.
4. Set **A2A Agent Endpoint** to your tunnel URL, for example `https://abc123-8000.usw2.devtunnels.ms`.
5. Under **Authentication**, choose key-based. Set the credential name to `x-api-key` and the
   value to your `A2A_API_KEY`.

**Or with the Azure Developer CLI:**
```bash
azd ai project set "$PROJECT_ENDPOINT"
azd ai connection create ticket-triage-a2a \
  --kind remote-a2a \
  --target https://abc123-8000.usw2.devtunnels.ms \
  --auth-type custom-keys \
  --custom-key "x-api-key=$A2A_API_KEY"
```

### 6. Fill in the Foundry settings in `.env`

```
PROJECT_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project>
MODEL_DEPLOYMENT_NAME=gpt-4.1-mini
A2A_CONNECTION_NAME=ticket-triage-a2a
FOUNDRY_AGENT_NAME=helpdesk-orchestrator
```

`PROJECT_ENDPOINT` is on the project **Overview** page in the Foundry portal.

### 7. Create the Foundry agent with the A2A tool

```bash
python foundry_client.py create
```

Each run creates a new **version** of `helpdesk-orchestrator`. The calls below always
use the latest version.

### 8. Talk to it

```bash
python foundry_client.py ask "My laptop connects to wifi but shows no internet. Blocking my work."
python foundry_client.py chat
```

While the agent is answering, the server terminal shows a log line
`A2A request (context=...)`. That line confirms Foundry called your local agent
over A2A.

---

## Direction B: local client → Foundry agent

Here your laptop is the **caller** and the Foundry agent is the **A2A server**:

```
scripts/call_foundry_agent.py ──A2A SendMessage + Entra token──►
   https://<account>.services.ai.azure.com/api/projects/<project>/agents/<agent>/endpoint/protocols/a2a
```

No tunnel and no project connection are needed, because your laptop calls out to Azure.

### B1. Make sure the Foundry agent exists
```bash
python foundry_client.py create
```

### B2. Turn on incoming A2A for the agent
```bash
python foundry_client.py enable-a2a
```
This calls `project.agents.update_details(...)`, which turns on the A2A protocol on the agent's endpoint
and publishes an agent card. It prints the A2A base URL. Incoming A2A can't be switched on in the
portal yet; it has to be done through the SDK or REST API.

### B3. Give your identity permission
The identity you `az login` with needs the **Foundry Agent Consumer** role (or higher) on the project.
In the Azure portal, open the Foundry resource and go to Access control (IAM) → Add role assignment.

### B4. Call it
```bash
python scripts/call_foundry_agent.py --card                       # see the agent card
python scripts/call_foundry_agent.py "My VPN keeps disconnecting"  # one message
python scripts/call_foundry_agent.py --chat                        # multi-turn, keeps the contextId
```

The script gets a token for `https://ai.azure.com` from your `az login`, fetches the agent card,
and sends an A2A v1.0 JSON-RPC `SendMessage` request.

**Full round trip:** `helpdesk-orchestrator` also holds the A2A tool from direction A. If your
local triage server and tunnel are running, one call goes
**laptop → Foundry → laptop → Foundry → laptop**. If they aren't running, the Foundry agent still
answers, but its tool call fails. Point `--agent` at any other Foundry agent with incoming A2A
enabled to test direction B on its own.

Limits on Foundry's incoming A2A: v1.0 supports JSON-RPC only, text parts only, and no streaming.
Tasks and contexts are kept for 60 days.

---

### 9. Clean up

```bash
python foundry_client.py delete
```
Then stop the tunnel and the server.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Server logs `Rejected request ... bad or missing x-api-key` | The connection's credential name must be exactly `x-api-key`, and its value must match `A2A_API_KEY`. |
| Foundry can't reach the agent, or you get TLS errors | Make sure the tunnel is running and `python scripts/test_a2a_local.py` works against the tunnel URL. |
| Agent answers without calling the tool | Send a clear ticket. The instructions tell it to call the tool for IT problems. You can also add `tool_choice="required"` in `respond()`. |
| `Set PROJECT_ENDPOINT in .env` | Copy the endpoint from the project Overview page. |
| `DefaultAzureCredential` failed | Run `az login`, and `az account set -s <subscription>` if needed. |
| Connection not found | The `A2A_CONNECTION_NAME` in `.env` must match the connection name in the portal. |
| `call_foundry_agent.py`: 401 | Run `az login`. The token must be for `https://ai.azure.com`. |
| `call_foundry_agent.py`: 403 | Assign the Foundry Agent Consumer role on the project to the signed-in identity. |
| `call_foundry_agent.py`: 404 | Check the agent name, and run `python foundry_client.py enable-a2a`. |
| The tunnel URL changed | Update `A2A_PUBLIC_URL`, restart the server, and edit the connection's endpoint in Foundry. |

## Later: deploy to the cloud

The server is a plain ASGI app (`a2a_agent.server:app`), so it containerizes directly.
Use Azure Container Apps, or App Service with
`uvicorn a2a_agent.server:app --host 0.0.0.0 --port 8000`. Keep `A2A_API_KEY` in
Key Vault or as a Container Apps secret. Set `A2A_PUBLIC_URL` to the app's URL and
update the Foundry connection target. Once it runs in Azure you can replace the API
key with `project-managed-identity` auth.
