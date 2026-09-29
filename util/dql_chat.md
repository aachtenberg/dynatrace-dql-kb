# DQL chat

The DQL agent as a chat in your browser. Ask in plain language ("any open problems?", "who calls checkout?"). The model checks names against your tenant, runs the query, and answers from the records: a short summary, then **Worth a look**, then the query. When a picture helps, it draws a chart or a graph from those records. Chats are kept so you can reopen them and carry on.

Same agent as `./util/dql_agent.sh`. Token, AWS access and troubleshooting are in [dql_agent.md](dql_agent.md). Nothing to install: standard library only, and React Flow is vendored.

## Quick start

```bash
cp .env.example .env          # your tenant, and one model: Bedrock, Azure or Ollama
./util/dql_agent.sh --check   # tests the tenant and each model; says what to fix
./util/dql_chat.sh            # opens the chat
```

History is a SQLite file the chat creates. The model picker offers every provider set up in `.env`, and a local Ollama when one is running. If the default model is not enabled in your AWS account, the chat says so and lets you pick another.

```bash
./util/dql_chat.sh --no-browser             # print the link
./util/dql_chat.sh --no-history             # memory only
./util/dql_chat.sh --history-db ~/chats.db  # another file
```

The rest of this page is optional.

| If you want to… | Go to |
|-----------------|-------|
| Learn the page | [Using it](#using-it) |
| Change model, region, turns | [Settings](#settings) |
| Keep or turn off past chats | [History](#history) |
| Point it at Bedrock, Ollama, or another server | [Model providers](#model-providers) |
| Lock it down, or see what leaves the machine | [Security](#security) |
| Set variables | [Server settings](#server-settings) |
| Run it on AWS | [Deploy the container on AWS](#deploy-the-container-on-aws) |
| Call it from your own app | [Use it from your own app](#use-it-from-your-own-app) |

## Using it

**Send.** Enter sends. Shift+Enter adds a line. The **↑** button sends, and becomes **■ Stop** while an answer runs. Esc stops too.

The pill on the left is the run mode. The one on the right is the model.

**Run a query.** Each query asks first. On the card, or by key:

| Key | Does |
|-----|------|
| **1** | Yes |
| **2** | Yes, and don't ask again (switches to Run automatically) |
| **3** | No. Tell the model what to change ("last 24h instead", "only prod hosts") |
| Esc | Decline |

The mode pill switches **Ask before running** and **Run automatically**. Every query is still checked for the usual DQL mistakes before it runs.

**Records.** Up to 200 rows, one click under the query card.

**Charts and graphs.** Each one has a **Table** toggle and the query it was drawn from. **⤢** fills the window; Esc restores it.

Line charts show every series at the pointer. Arrow keys move the readout. Graphs pan, zoom and drag. Node colour is the Smartscape type (host, process, service, …). A ring marks what the model highlighted, usually the entities under **Worth a look**.

**Open problems.** The welcome screen and the top-bar badge show the count, the categories and the newest ones. A click asks the agent about them.

The server runs two fixed read-only queries for this (an exact count, and the newest few), cached for a minute. The model does not write them. `DQL_CHAT_PROBLEMS=0` turns the check off.

**Recents.** The sidebar lists your chats, newest first, titled by the first question. Open one to see it again, graphs included, and keep asking. The model still has its earlier messages and query results.

**⋯** renames or deletes a chat; **Select** picks several to delete at once. Delete is immediate and final: the chat and its query results are erased from the server, with no trash to restore from. **New chat** starts another and leaves the current one in the list. A reload reopens the chat you were in.

### Commands

Type `/` in the message box for the list; arrows pick, Tab completes, Enter runs.

| Command | Does |
|---------|------|
| `/clear` | Start a new chat (the current one stays in Recents) |
| `/resume` | Open Recents to reopen a past chat |
| `/model` | Open the model picker |
| `/problems` | Ask about the open Davis problems |
| `/config` | Open settings |
| `/theme [system\|light\|dark]` | Switch the theme; without a word, open it in settings |

## Settings

Open them from the button at the top right, or `/config`. A change applies at once. There is no Save button. Text and number fields apply on Enter or when you leave them, and the row shows **Saved** or the server's error.

A new provider, model or region starts a new chat. The current one stays in Recents.

Theme and run mode stay in this browser. Model, region, turns and output tokens are saved per user on the server when history is on, so they follow you to another browser.

| Setting | Providers | What it does |
|---------|-----------|--------------|
| Theme | — | System, Light or Dark. Charts and graphs follow it. |
| Run queries without asking | — | Same as the mode pill. Needs a tenant. |
| Provider | when more than one is offered | Bedrock or Ollama, for example. Each provider keeps the model you last picked. |
| Turns per question | all | Model calls for one question. 1–30, default 10. A search, name check, query or chart is one call. |
| Max output tokens per turn | all | Caps one reply, thinking included. 256–64,000. Default 16,000 for Claude and the Responses API, 4,096 otherwise. |
| AWS region | Bedrock | Where Bedrock is called. The model list follows it. |
| Model or inference profile | Bedrock | From the account's profiles and on-demand models, or typed. Empty uses the Claude Sonnet 5 profile for the region. |
| Model | OpenAI-compatible, vLLM, Azure OpenAI, Ollama, Anthropic | Filled from the server's list where it has one. For Azure, this is the deployment name. |
| Context window (num_ctx) | Ollama | Default 16,384. Below that the agent's prompt is cut. |

The model picker lists every offered provider's models, grouped. Picking a model there switches provider too.

URLs and API keys stay in the server's environment. The browser cannot set them.

- `DQL_CHAT_ALLOW_SETTINGS=0` freezes every setting.
- `DQL_CHAT_ALLOWED_MODELS` limits the ids users may pick. Comma-separated. A trailing `*` matches a prefix, for example `us.anthropic.claude-sonnet-*,amazon.nova-*`.
- A saved model the server no longer allows is dropped at the next chat.

## History

On by default. Each chat is a SQLite file: what the page drew (question, queries, results, charts, answer) and the agent's state (the model's messages, and up to 20 query results). Reopening a chat redraws it and hands the model those messages, so "now only prod" still works after a restart.

- **File:** `~/.local/share/dql-chat/chats.db`, or `$XDG_DATA_HOME/dql-chat/`. `DQL_CHAT_DB` or `--history-db` changes it. The file is readable by its owner only. It holds query results from your tenant.
- **Off:** `DQL_CHAT_HISTORY=0` or `--no-history`. Chats stay in memory until the server restarts, and Recents is empty.
- **Retention:** chats untouched for `DQL_CHAT_RETENTION_DAYS` (default 90) are deleted. `0` keeps them.
- **Per user:** every row carries the user. That is `local` with a token, or the signed-in identity behind a load balancer. One user cannot list, open, rename or delete another's chats. With `DQL_CHAT_AUTH=none`, everyone is the same user and shares one history.
- **Not writable:** the server logs `Chat history is off: …` and runs without history.

## Model providers

The agent talks to models through adapters in `dqlagent/llm.py`. The terminal agent and the chat both use `LLM_PROVIDER` and the same variables as `dql_rag.py`, so one `.env` configures everything.

| `LLM_PROVIDER` | Talks to | Variables |
|----------------|----------|-----------|
| unset or `bedrock` | Amazon Bedrock Converse API | `BEDROCK_MODEL_ID`, `BEDROCK_REGION`, AWS credentials |
| `ollama` | Ollama's native `/api/chat` (so `num_ctx` is honored) | `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_NUM_CTX` |
| `vllm` | vLLM, `POST /v1/chat/completions` | `VLLM_BASE_URL`, `VLLM_MODEL`, `PRIVATE_API_KEY` |
| `openai_compatible` | Anything that serves `/v1/chat/completions` (LiteLLM, a company gateway) | `PRIVATE_BASE_URL`, `PRIVATE_MODEL`, `PRIVATE_API_KEY` |
| `azure_openai` | Azure OpenAI, Responses API at `/openai/v1/responses` | `AZURE_OPENAI_ENDPOINT` (`https://<resource>.openai.azure.com`), `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT` |
| `openai` | OpenAI, Responses API | `OPENAI_API_KEY`, `OPENAI_MODEL` |
| `anthropic` | Anthropic API, through the official SDK | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` (default `claude-sonnet-5`). Needs `pip install anthropic`. |

`OPENAI_API` picks the OpenAI wire format. Unset, `openai` and `azure_openai` use the Responses API and the others use chat completions. `chat` sends `openai` and `azure_openai` to chat completions; for Azure that is the deployment URL with `AZURE_OPENAI_API_VERSION`. `responses` sends `vllm` and `openai_compatible` to `/v1/responses`. Responses calls set `store: false`, so the provider keeps no copy of the conversation. Reasoning models send back their reasoning encrypted, and the adapter returns it with the tool results, as it does for Bedrock.

The model must support tool use. `./util/dql_agent.sh --check` asks each provider set up in `.env` to call a tool, and says which ones work.

`LLM_PROVIDER` is the server's default. With `DQL_CHAT_PROVIDERS=auto`, the default, the picker also offers every other provider that is set up in `.env`, plus an Ollama that answers at `OLLAMA_BASE_URL`. Otherwise `DQL_CHAT_PROVIDERS` is a fixed, comma-separated list, for example `bedrock,ollama`. URLs and keys always come from the server's environment.

For Ollama, the picker offers models that can call tools (`/api/show` capabilities). Others are greyed out. Embedding models are left out. A local model on a shared GPU can take minutes per turn.

### Azure AI Foundry

You need an Azure subscription and the Azure CLI, signed in with `az login`. Set these two for the commands below:

```bash
RG=my-resource-group
AI=my-foundry-resource        # also the subdomain of its endpoint
```

**1. A Foundry resource.** Skip this if you have one. `az cognitiveservices account list -o table` lists yours.

```bash
az group create -n $RG -l eastus2
az cognitiveservices account create -g $RG -n $AI -l eastus2 \
  --kind AIServices --sku S0 --custom-domain $AI
```

**2. A model deployment.** GlobalStandard bills per token, with no standing cost. `--sku-capacity` is thousands of tokens per minute.

```bash
az cognitiveservices account deployment create -g $RG -n $AI \
  --deployment-name gpt-5-mini --model-name gpt-5-mini \
  --model-version 2025-08-07 --model-format OpenAI \
  --sku-name GlobalStandard --sku-capacity 50
```

Any model with tool calling works, if your subscription has quota for it. New subscriptions often have none for the newest models: the deployment fails with `InsufficientQuota ... the quota limit is 0`. This lists the models you do have quota for:

```bash
az cognitiveservices usage list -l eastus2 -o table \
  --query "[?limit>\`0\` && contains(name.value, 'GlobalStandard')].{model:name.value, limit:limit}"
```

To get more, use **Quotas** in [ai.azure.com](https://ai.azure.com) to request it.

**3. The `.env`.** The resource already has two keys; this copies one in without printing it.

```bash
{ echo "LLM_PROVIDER=azure_openai"
  echo "AZURE_OPENAI_ENDPOINT=https://$AI.openai.azure.com"
  echo "AZURE_OPENAI_DEPLOYMENT=gpt-5-mini"
  echo "AZURE_OPENAI_API_KEY=$(az cognitiveservices account keys list -g $RG -n $AI --query key1 -o tsv)"
} >> .env
```

Leave out `LLM_PROVIDER` to keep Bedrock as the default. The chat's picker offers Azure either way.

**4. Check it.** Run `./util/dql_agent.sh --check`.

Good to know:
- **Model field:** the picker offers `AZURE_OPENAI_DEPLOYMENT`. For another deployment, type its name, not the model name.
- **Older deployments:** a model without reasoning is retried without encrypted reasoning, on its own. A resource without the v1 API needs `OPENAI_API=chat`.
- **Portal instead of the CLI:** in [ai.azure.com](https://ai.azure.com), go to **Models + endpoints**, then **Deploy model**. The key and endpoint are on the resource's overview page.
- **Keys:** only API keys work. A resource with local auth turned off (Entra ID only) is refused with HTTP 401 or 403.
- **Budget:** set one in the portal under **Cost Management**, then **Budgets**, scoped to the resource group.

## Security

- **On your machine** (`DQL_CHAT_AUTH=token`, the default) the server listens on 127.0.0.1 only. The link it prints carries a random token, and every API call must send it. Requests must come from the chat's own host and origin, so another site open in the same browser cannot drive the chat.
- The page loads only its own files. Nothing comes from a CDN. Text from the model or the tenant is inserted as text, never as HTML.
- The Dynatrace token and the model credentials stay on the server. The browser never sees them.
- **Leaves the machine:** your question, doc excerpts, and up to 50 records per query, sent to the model the user picks. Any provider with a key in `.env` can be picked, so remove keys you do not want used, or set `DQL_CHAT_PROVIDERS` to a fixed list. Queries go to your tenant.
- **Stays on disk:** the chats and their query results, when history is on. Theme and run mode stay in the browser. The access token stays in the tab.
- **Audit:** each query, and each open-problems check, is one JSON line on stdout (`event`, `user`, `query`, `records`, `scanned`). `DQL_CHAT_AUDIT=full` adds the questions. `off` stops it.

## Server settings

| Variable | Default | Notes |
|----------|---------|-------|
| `DQL_CHAT_HOST` | `127.0.0.1` | `0.0.0.0` in the container |
| `DQL_CHAT_PORT` | `8750` | |
| `DQL_CHAT_AUTH` | `token` | `token`, `proxy` (behind a load balancer that signs users in), or `none` (only on a network nobody else can reach) |
| `DQL_CHAT_TOKEN` | random | Fix the token, e.g. for a bookmark |
| `DQL_CHAT_USER_HEADER` | `x-amzn-oidc-identity` | In `proxy` mode, the header that carries the signed-in user |
| `DQL_CHAT_AUTO_RUN` | `0` | `1` starts a browser in "Run automatically" until its user picks a mode |
| `DQL_CHAT_ALLOW_SETTINGS` | `1` | `0` fixes the settings |
| `DQL_CHAT_ALLOWED_MODELS` | any | See Settings |
| `DQL_CHAT_PROVIDERS` | `auto` | Providers users may pick besides `LLM_PROVIDER`, e.g. `bedrock,ollama`; `auto` adds every provider set up in `.env`, and an Ollama that answers |
| `DQL_CHAT_HISTORY` | `1` | `0` keeps chats in memory only (`--no-history`) |
| `DQL_CHAT_DB` | `~/.local/share/dql-chat/chats.db` | The history file (`--history-db`); `/data/chats.db` in the container |
| `DQL_CHAT_RETENTION_DAYS` | `90` | Chats untouched this long are deleted; `0` keeps them |
| `DQL_CHAT_MAX_SESSIONS` | `50` | Open conversations kept in memory (with history on, an evicted one reloads from disk) |
| `DQL_CHAT_IDLE_MINUTES` | `240` | A conversation idle this long leaves memory (with history on, it reloads from disk when reopened) |
| `DQL_CHAT_APPROVAL_TIMEOUT` | `600` | Seconds a query waits for Run before it counts as declined |
| `DQL_CHAT_PROBLEMS` | `1` | `0` drops the open-problems check from the welcome screen |
| `DQL_CHAT_AUDIT` | `queries` | `queries`, `full` or `off` |
| `DQL_AGENT_SCAN_LIMIT_GB` | `50` | Grail stops a query that would read more |

## Deploy the container on AWS

Skip this if you run the chat on your own machine.

The container reads its configuration from the environment and takes AWS credentials from the task role. A fit for it is **ECR → ECS on Fargate → an Application Load Balancer that signs users in** (OIDC, or Amazon Cognito). App Runner has no built-in sign-in, so it needs something else in front.

### 1. Build and push the image

Run `./dt_fetch.sh all` first: the image carries `docs/` as it is, including the tenant's metric keys and field names.

```bash
ACCOUNT=123456789012 REGION=us-east-1
REPO=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/dql-chat
aws ecr create-repository --repository-name dql-chat --region $REGION
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.$REGION.amazonaws.com
docker buildx build --load -f util/dql_chat.Dockerfile -t $REPO:1 .
docker push $REPO:1
```

Use `docker buildx build`. It reads `util/dql_chat.Dockerfile.dockerignore`. Plain `docker build` on some installs still uses the root `.dockerignore` and stops with `COPY failed: ... dt_fetch.py`.

The image is about 120 MB. It runs as `nobody` and checks `/healthz`. The only file it writes is `/data/chats.db`.

### 2. Task definition

```json
{
  "family": "dql-chat",
  "requiresCompatibilities": ["FARGATE"],
  "networkMode": "awsvpc",
  "cpu": "512", "memory": "1024",
  "taskRoleArn": "arn:aws:iam::123456789012:role/dql-chat-task",
  "executionRoleArn": "arn:aws:iam::123456789012:role/dql-chat-execution",
  "containerDefinitions": [{
    "name": "dql-chat",
    "image": "123456789012.dkr.ecr.us-east-1.amazonaws.com/dql-chat:1",
    "portMappings": [{ "containerPort": 8750 }],
    "environment": [
      { "name": "DQL_CHAT_AUTH", "value": "proxy" },
      { "name": "BEDROCK_REGION", "value": "us-east-1" },
      { "name": "DT_ENVIRONMENT_URL", "value": "https://<env-id>.apps.dynatrace.com" },
      { "name": "DQL_CHAT_ALLOWED_MODELS", "value": "us.anthropic.claude-sonnet-*" }
    ],
    "secrets": [
      { "name": "DT_API_TOKEN", "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789012:secret:dql-chat/dt-token" }
    ],
    "logConfiguration": { "logDriver": "awslogs", "options": {
      "awslogs-group": "/ecs/dql-chat", "awslogs-region": "us-east-1", "awslogs-stream-prefix": "chat" } }
  }]
}
```

- **Credentials** come from the task role. The agent reads the container credentials endpoint and refreshes them. The task definition holds no keys.
- **Task role:** `bedrock:InvokeModel` on the model and its inference profile, as in [dql_agent.md](dql_agent.md) §2.2. Also `bedrock:ListInferenceProfiles` and `bedrock:ListFoundationModels`, for the default model and the picker.
- **Dynatrace token:** Secrets Manager, through `secrets`. The execution role needs `secretsmanager:GetSecretValue` on that secret.
- **Network:** the tasks need HTTPS out to your tenant and to Bedrock. From a private subnet, use NAT, or a VPC endpoint for `bedrock-runtime` and for `bedrock` (the model list).
- **Logs:** audit lines go to the CloudWatch log group.
- **History:** task storage is wiped when the task stops. To keep chats, mount an EFS access point (owner uid 65534) at `/data`. Otherwise set `DQL_CHAT_HISTORY=0`.

### 3. Load balancer

Use an internal or internet-facing ALB. The HTTPS listener authenticates (**authenticate-oidc** or **authenticate-cognito**), then forwards to a target group on port 8750. The ALB passes `x-amzn-oidc-identity`. The chat uses that as the user and refuses a request that lacks it.

- Health check: `GET /healthz`.
- The task security group allows port 8750 from the ALB's security group only. In `proxy` mode the chat trusts that header, and the security group is what makes the header trustworthy.
- Idle timeout can stay at 60 seconds. The chat streams answers and sends a heartbeat every 15 seconds.
- Run one task. SQLite should have one writer, so one history file is not shared across tasks. Open answers and approval prompts live in the task's memory. With history on EFS, a restart keeps the chats. With history off, a restart starts them fresh.

## Use it from your own app

Everything above is a thin layer over `dqlagent.core.Agent`. A Flask route that streams the same events:

```python
import json, sys
sys.path.insert(0, "/path/to/dynatrace-dql-kb/util")
from flask import Flask, Response, request
from dqlagent import core, llm

app = Flask(__name__)
index = core.DocIndex()                     # load the docs once

@app.post("/ask")
def ask():
    events = []
    agent = core.Agent(llm.make_model(), index, can_run=True, approve="always",
                       visuals_on=True, on_event=lambda kind, data: events.append((kind, data)))
    answer = agent.ask(request.json["question"])
    return {"answer": answer,
            "visuals": [d["spec"] for k, d in events if k == "visual"],
            "queries": [d["query"] for k, d in events if k == "result"]}
```

Keep one `Agent` per conversation, so a follow-up still has the earlier messages. For a human approval step, pass `approve="ask"` and an `approver(query) -> (run, said)` callable. A graph spec is already React Flow nodes and edges, with positions, so a React page can draw it as it arrives.
