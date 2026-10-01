# foundry-a2a-client

An Azure AI Foundry agent that calls a **local A2A agent** through the
generally available **A2A tool** (A2A protocol v1.0).

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
| The tunnel URL changed | Update `A2A_PUBLIC_URL`, restart the server, and edit the connection's endpoint in Foundry. |

## Later: deploy to the cloud

The server is a plain ASGI app (`a2a_agent.server:app`), so it containerizes directly.
Use Azure Container Apps, or App Service with
`uvicorn a2a_agent.server:app --host 0.0.0.0 --port 8000`. Keep `A2A_API_KEY` in
Key Vault or as a Container Apps secret. Set `A2A_PUBLIC_URL` to the app's URL and
update the Foundry connection target. Once it runs in Azure you can replace the API
key with `project-managed-identity` auth.
