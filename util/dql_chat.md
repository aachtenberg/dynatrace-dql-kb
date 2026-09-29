# DQL chat

The DQL agent as a chat in your browser. You ask in plain language ("any open problems?", "chart CPU for the busiest hosts", "who calls checkout?"); the model searches this repo's DQL reference, checks every metric and field name against your tenant, runs the query and answers from the records: a one- or two-line summary, then **Worth a look** (up to three things in the records you would want to know without asking: an outlier, errors, one host carrying the load, a result that was cut off), then details and the query. When a picture helps, it draws a line chart, a bar chart or a React Flow graph **from the query's records**. The model names a result and its fields; it never types the numbers.

Chats are kept (SQLite, standard library) so you can reopen them from **Recents**, and the model picks up where it left off. The page follows the patterns of Claude Code and Copilot Chat: a message box with the tools inside it, `/` commands, numbered approval prompts, a model picker, and settings that apply as you change them.

It is the same agent as `./util/dql_agent.sh`, with the same setup, model providers and safety checks. [dql_agent.md](dql_agent.md) covers the setup (Dynatrace token, AWS access, `--check`) and troubleshooting.

Standard library only. The page's graph library (React Flow) is vendored in `dqlagent/static/vendor/`, so nothing is installed and nothing loads from a CDN.

## Quick start

```bash
cp .env.example .env          # set DT_ENVIRONMENT_URL and DT_API_TOKEN; BEDROCK_REGION for Bedrock
./util/dql_agent.sh --check   # says whether the model and the tenant work, and which one does not
./util/dql_chat.sh            # opens the chat in your browser
```

That is all. Nothing to install and no database to set up: history goes to a SQLite file the chat creates, and a local Ollama is offered automatically when one is running. If the default model is not enabled for your AWS account, the chat says so and lets you pick another. **Everything below is optional.**

```bash
./util/dql_chat.sh --no-browser             # print the link instead of opening a browser
./util/dql_chat.sh --no-history             # keep chats in memory only
./util/dql_chat.sh --history-db ~/chats.db  # keep them in another file
```

## Using it

- **The message box** holds everything: type and press Enter (Shift+Enter for a new line). The round **↑** button sends; while an answer runs it becomes **■ Stop**, and Esc does the same. The pill on the left is the run mode, the one on the right the model.
- **Each query asks first.** Its card shows **Run this query?** with three options, by click or key: **1** Yes, **2** Yes, and don't ask again (switches the mode to Run automatically), **3** No, and tell the model what to do differently ("last 24h instead", "only prod hosts"). Esc declines. The mode pill (**Ask before running** / **Run automatically**) switches it back. Every query is still checked for the usual DQL mistakes before it runs.
- **Records** of every query are one click away under its card: up to 200 rows.
- **Charts and graphs** carry a **Table** toggle and the query they were drawn from. Line charts show every series at the pointer; arrow keys move the readout. Graphs pan, zoom and drag; node colour is the Smartscape type (host, process, service, …), and a ring marks what the model highlighted, usually the entities under **Worth a look**.
- **Recents** (the sidebar) lists your chats, newest first, titled by their first question. Click one to reopen it exactly as it looked, graphs included, and keep asking: the model has its earlier messages and query results. The **⋯** menu renames or deletes a chat. **New chat** starts another; the current one stays in Recents. A reload reopens the chat you were in.

### Commands

Type `/` in the message box for the list; arrows pick, Tab completes, Enter runs.

| Command | Does |
|---------|------|
| `/clear` | Start a new chat (the current one stays in Recents) |
| `/resume` | Open Recents to reopen a past chat |
| `/model` | Open the model picker |
| `/config` | Open settings |
| `/theme [system\|light\|dark]` | Switch the theme; without a word, open it in settings |

## Settings

The **settings** button (top right, or `/config`) opens a dialog. **Every change applies at once**; there is no Save button. Text and number fields apply on Enter or when you leave them, and show **Saved** or the server's error on their row. A new model or region starts a new chat; the current one stays in Recents.

Theme and run mode are this browser's choice. Model, region, turns and output tokens are saved **per user** on the server (with history on), so they follow you to another browser and survive a restart.

| Setting | Providers | What it does |
|---------|-----------|--------------|
| Theme | — | System (follows the OS), Light or Dark. Charts and graphs follow it. |
| Run queries without asking | — | Same as the mode pill. Needs a tenant. |
| Provider | when the server offers more than one | e.g. Amazon Bedrock or Ollama on this machine. Switching starts a new chat; each provider keeps the model you last picked. The model picker lists every offered provider's models, grouped, so picking a model there switches provider too. |
| Turns per question | all | Model calls allowed for one question (1–30, default 10). Each search, name check, query or chart is one. |
| Max output tokens per turn | all | Caps each model reply, thinking included (256–64,000). Default 16,000 for Claude models, 4,096 otherwise. |
| AWS region | Bedrock | Where Bedrock is called. The model list follows it. |
| Model or inference profile | Bedrock | Picked from the account's inference profiles and on-demand models, or typed. Empty: the Claude Sonnet 5 profile for the region. |
| Model | OpenAI-compatible, vLLM, Azure OpenAI (deployment), Ollama, Anthropic | Filled from the server's model list where it has one. |
| Context window (num_ctx) | Ollama | Default 16,384. Below that the agent's prompt is cut. |

Provider URLs and keys are never settable from the browser; they stay in the server's environment. `DQL_CHAT_ALLOW_SETTINGS=0` fixes all settings, and `DQL_CHAT_ALLOWED_MODELS` limits the ids users may pick (comma-separated; a trailing `*` matches a prefix, e.g. `us.anthropic.claude-sonnet-*,amazon.nova-*`). A saved model the server no longer allows is dropped at the next chat.

## History

With history on (the default), the server keeps each chat in a SQLite file: every event the page drew (question, queries, results, charts, answer) and the agent's state (the model's messages and up to 20 query results per chat). Reopening a chat redraws it from the events and hands the model its messages, so a follow-up such as "now only prod" works after a restart.

- **Where:** `~/.local/share/dql-chat/chats.db` (or `$XDG_DATA_HOME/dql-chat/`); `DQL_CHAT_DB` or `--history-db` changes it. The file is created readable by its owner only, because it holds query results from your tenant.
- **Off:** `DQL_CHAT_HISTORY=0` or `--no-history`. Chats then live in memory until the server restarts, as before, and Recents is empty.
- **Retention:** chats untouched for `DQL_CHAT_RETENTION_DAYS` (default 90) are deleted; `0` keeps them.
- **Per user:** every row carries the user (`local` with a token, the signed-in identity behind a load balancer). Nobody can list, open, rename or delete another user's chats. With `DQL_CHAT_AUTH=none` everyone is the same user and shares one history.
- **Not writable?** The server logs `Chat history is off: …` and runs without history rather than failing.

## Model providers

The agent talks to models through adapters in `dqlagent/llm.py`. The terminal agent and the chat both use `LLM_PROVIDER` and the same variables as `dql_rag.py`, so one `.env` configures everything.

| `LLM_PROVIDER` | Talks to | Variables |
|----------------|----------|-----------|
| unset or `bedrock` | Amazon Bedrock Converse API | `BEDROCK_MODEL_ID`, `BEDROCK_REGION`, AWS credentials |
| `ollama` | Ollama's native `/api/chat` (so `num_ctx` is honored) | `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_NUM_CTX` |
| `vllm` | vLLM, `POST /v1/chat/completions` | `VLLM_BASE_URL`, `VLLM_MODEL`, `PRIVATE_API_KEY` |
| `openai_compatible` | Anything that serves `/v1/chat/completions` (LiteLLM, a company gateway) | `PRIVATE_BASE_URL`, `PRIVATE_MODEL`, `PRIVATE_API_KEY` |
| `azure_openai` | Azure OpenAI | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION` |
| `openai` | OpenAI | `OPENAI_API_KEY`, `OPENAI_MODEL` |
| `anthropic` | Anthropic API, through the official SDK | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` (default `claude-sonnet-5`). Needs `pip install anthropic`. |

The model must support tool use. `./util/dql_agent.sh --check` asks it to call a tool and says if it did not.

**Picking a provider in the chat.** `LLM_PROVIDER` is the server's default. `DQL_CHAT_PROVIDERS` lists the others users may switch to in the page (comma-separated, e.g. `bedrock,ollama`); the default, `auto`, adds a local Ollama when one answers at `OLLAMA_BASE_URL` at start. Each provider still takes its URL and keys from the server's environment. For Ollama the picker shows only models that can call tools (from `/api/show` capabilities); others are listed greyed out, and embedding models are left out. A local model on a shared GPU can take minutes per turn.

## Security

- **On your machine (the default, `DQL_CHAT_AUTH=token`)** the server listens on 127.0.0.1 only. The link it prints carries a random token; every API call must send it, and requests must come from the chat's own host and origin. Another website open in the same browser cannot drive the chat or read its answers.
- The page loads only its own files (a strict Content-Security-Policy; no CDN), and everything from the model or the tenant is inserted as text, never as HTML.
- The chat holds your Dynatrace token and model credentials server-side; the browser never sees them.
- **What leaves the machine:** your question, doc excerpts and up to 50 records per query go to the model provider; queries go to your tenant. Nothing else.
- **What stays on disk:** with history on, the chats and their query results (see History). Theme and run mode are kept in the browser's local storage; the access token only in the tab.
- **Audit:** each query that runs is printed as one JSON line on stdout (`{"event": "query", "user": ..., "query": ..., "records": ..., "scanned": ...}`). `DQL_CHAT_AUDIT=full` adds the questions; `off` stops it.

## Server settings

| Variable | Default | |
|----------|---------|-|
| `DQL_CHAT_HOST` | `127.0.0.1` | `0.0.0.0` in the container |
| `DQL_CHAT_PORT` | `8750` | |
| `DQL_CHAT_AUTH` | `token` | `token`, `proxy` (behind a load balancer that signs users in), or `none` (only on a network nobody else can reach) |
| `DQL_CHAT_TOKEN` | random | Fix the token, e.g. for a bookmark |
| `DQL_CHAT_USER_HEADER` | `x-amzn-oidc-identity` | In `proxy` mode, the header that carries the signed-in user |
| `DQL_CHAT_AUTO_RUN` | `0` | `1` starts a browser in "Run automatically" until its user picks a mode |
| `DQL_CHAT_ALLOW_SETTINGS` | `1` | `0` fixes the settings |
| `DQL_CHAT_ALLOWED_MODELS` | any | See Settings |
| `DQL_CHAT_PROVIDERS` | `auto` | Providers users may pick besides `LLM_PROVIDER`, e.g. `bedrock,ollama`; `auto` adds a local Ollama if it answers |
| `DQL_CHAT_HISTORY` | `1` | `0` keeps chats in memory only (`--no-history`) |
| `DQL_CHAT_DB` | `~/.local/share/dql-chat/chats.db` | The history file (`--history-db`); `/data/chats.db` in the container |
| `DQL_CHAT_RETENTION_DAYS` | `90` | Chats untouched this long are deleted; `0` keeps them |
| `DQL_CHAT_MAX_SESSIONS` | `50` | Open conversations kept in memory (with history on, an evicted one reloads from disk) |
| `DQL_CHAT_IDLE_MINUTES` | `240` | A conversation idle this long leaves memory (with history on, it reloads from disk when reopened) |
| `DQL_CHAT_APPROVAL_TIMEOUT` | `600` | Seconds a query waits for Run before it counts as declined |
| `DQL_CHAT_AUDIT` | `queries` | `queries`, `full` or `off` |
| `DQL_AGENT_SCAN_LIMIT_GB` | `50` | Grail stops a query that would read more |

## Deploy on AWS

The chat runs as a container, reads everything from the environment, and gets AWS credentials from the task role, so it deploys like any small web service. The shape that fits: **ECR → ECS on Fargate → an Application Load Balancer that signs users in** (OIDC with your identity provider, or Amazon Cognito). App Runner has no built-in sign-in, so it would need its own front door.

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

Build with BuildKit (`docker buildx build`): it reads `util/dql_chat.Dockerfile.dockerignore`. The legacy builder, which plain `docker build` still falls back to on some installs, reads the root `.dockerignore` instead and stops with `COPY failed: ... dt_fetch.py`.

The image is about 120 MB (python:3.12-slim plus text files), runs as `nobody`, and has a health check on `/healthz`. The only thing it writes is chat history, to `/data/chats.db` (a volume).

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

- **Credentials:** the task role. The agent reads the container credentials endpoint ECS provides and refreshes them before they expire; no keys in the task definition.
- **Task role policy:** `bedrock:InvokeModel` on the model and its inference profile (the policy in [dql_agent.md](dql_agent.md) §2.2), plus `bedrock:ListInferenceProfiles` and `bedrock:ListFoundationModels` for the default model and the model picker.
- **The Dynatrace token** comes from Secrets Manager through `secrets`; the execution role needs `secretsmanager:GetSecretValue` on it.
- **Network:** the tasks need HTTPS out to your tenant and to Bedrock. In a private subnet, use NAT, or a VPC endpoint for `bedrock-runtime` (and `bedrock` for the model list) plus whatever route your tenant needs.
- **Logs:** the audit lines land in the CloudWatch log group.
- **History:** Fargate task storage is wiped when the task stops. To keep chats, mount an EFS access point (owner uid 65534) at `/data` through `volumes` and `mountPoints`; to go without, set `DQL_CHAT_HISTORY=0`.

### 3. Load balancer

- An internal (or internet-facing) ALB with an HTTPS listener whose default action is **authenticate-oidc** (or **authenticate-cognito**), then **forward** to a target group on port 8750. The ALB signs users in and passes `x-amzn-oidc-identity` to the chat, which uses it as the user and refuses requests without it.
- Target group health check: `GET /healthz`.
- **Only the ALB may reach the tasks:** their security group allows port 8750 from the ALB's security group only. In `proxy` mode the chat trusts the identity header; the security group is what makes that header trustworthy.
- Idle timeout: the chat streams answers and sends a heartbeat every 15 seconds, so the default 60 seconds is enough.
- Run **one task**. With history on EFS a restart loses nothing; open answers and approval prompts live in the task's memory, and SQLite should have one writer, so do not share one history file between several tasks. Without history, a restart starts everyone's chat afresh.

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

Keep one `Agent` per user conversation for follow-up questions. For a human approval step, pass `approve="ask"` and an `approver(query) -> (run, said)` callable. Graph specs are already in React Flow's node and edge format with positions, so an existing React front end can render them as they are.
