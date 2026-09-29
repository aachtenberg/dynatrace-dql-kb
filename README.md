# Dynatrace DQL Knowledge Base

Models often write DQL that Dynatrace rejects: `fetch` on a metric, `by:` without braces, SQL keywords, made-up metric keys. This repo is the reference that keeps the query valid, for Copilot, for MCP clients, and for a chat that runs the queries on your tenant.

It is built for an enterprise desktop you do not administer: the tools are standard-library Python, with no `pip install`, and nothing calls a public model API unless you point it at one.

| Use it from | Who writes the DQL | Needs |
|-------------|--------------------|-------|
| [VS Code](#copilot-agents) | Copilot, following this repo's rules | Nothing |
| [A chat, terminal or browser](#chat-with-your-tenant) | A model that also runs the query and answers from the records | Bedrock or Ollama |
| [An MCP client](#mcp-server) | Your client's model, using the matching reference pages | Docker, or `./quickstart.sh --with-rag` |

[ARCHITECTURE.md](ARCHITECTURE.md) shows how the pieces fit together.

## Quick start

```bash
git clone https://github.com/aachtenberg/dynatrace-dql-kb.git
cd dynatrace-dql-kb
./quickstart.sh          # checks that Python 3.10+ starts; installs nothing
cp .env.example .env     # set DT_ENVIRONMENT_URL and DT_API_TOKEN
./dt_fetch.sh all        # write your tenant's metric keys and field names into docs/
```

Then open the folder in VS Code for the Copilot agents, or start the chat:

```bash
./util/dql_agent.sh --check    # model and tenant; says which one fails
./util/dql_chat.sh             # the chat in your browser
```

On Windows Git Bash the scripts skip the Microsoft Store `python3` alias and use `python` or `py -3`.

## Chat with your tenant

Ask in plain language ("any open problems?", "who calls checkout?"). A model searches `docs/`, checks every metric and field name against your tenant, runs the query, and answers from the records: a short summary first, then anything **worth a look**. When Grail rejects a query, the model reads the error and fixes it.

- **Browser, `./util/dql_chat.sh`:** charts and React Flow graphs drawn from the query's records (never from numbers the model typed), chats kept to reopen later, open Davis problems on the welcome screen, and a model picker across Bedrock and Ollama. It runs locally, or as a container on AWS ([how to build and deploy it](util/dql_chat.md#deploy-the-container-on-aws)). See [util/dql_chat.md](util/dql_chat.md).
- **Terminal, `./util/dql_agent.sh`:** the same agent, including in AWS CloudShell. See [util/dql_agent.md](util/dql_agent.md) for AWS setup, recipes and troubleshooting.
- **Safe by default:** you approve each query before it runs, each query is checked for the classic DQL mistakes first, and a query can scan at most 50 GB. Your question, doc excerpts and up to 50 records per query go to the model: Bedrock in your AWS account, or your own Ollama.

Run `./dt_fetch.sh all` first. The agent checks names against `docs/metric_keys.md` and `docs/entity_schemas.md`, so it is only as good as those two files.

## Copilot agents

Open the repo in VS Code with Copilot and call an agent in Copilot Chat. They pick up `.github/` and `docs/` on their own.

```
@dql-expert show me hosts with CPU above 90% in the last hour
@dql-expert error logs from the payment service grouped by host
@dashboard-builder create a host overview dashboard with CPU, memory, and error logs
```

`@dql-expert` knows the rules models get wrong: metrics use `timeseries`, never `fetch`; `by:` needs braces; no SQL; `makeTimeseries` is for logs, events and spans only. `@dashboard-builder` writes JSON for the current Dashboards app, including Terraform `dynatrace_document`.

## Knowledge base

| File in `docs/` | What's in it |
|-----------------|--------------|
| `dql_syntax_reference.md` | Commands, functions, operators, data types |
| `dql_example_queries.md` | Working queries: hosts, logs, spans, Kubernetes, entities |
| `dql_common_questions.md` | Plain questions (open problems, high CPU, errors) mapped to a query that runs |
| `dql_tips_and_patterns.md`, `dql_wrong_vs_right.md` | Common mistakes and their fixes |
| `kubernetes.md`, `smartscape_calls.md` | Container CPU and restarts; service calls through Smartscape |
| `dashboard_json_schema.md` | Dashboard JSON, tile types, Terraform |
| `metric_keys.md`, `entity_schemas.md` | **Your tenant's** metric keys and fields, written by `dt_fetch` |

Add your own material (team queries, runbook snippets) as `.md`, `.txt`, `.dql`, `.json` or `.yaml` files in `docs/`.

**Your tenant's names.** Metric keys and field names differ per tenant, and models make them up. `./dt_fetch.sh all` writes both files from the Grail API. `DT_ENVIRONMENT_URL` must be the `https://<env-id>.apps.dynatrace.com` host (`live.dynatrace.com` has no Grail API). `DT_API_TOKEN` needs the `storage:*:read` scopes listed in [.env.example](.env.example). A corporate proxy is read from `HTTPS_PROXY`, and a company CA from `SSL_CERT_FILE`.

<details>
<summary>No API access? Fill the two files from a Notebook</summary>

```
metrics | sort metric.key asc          -- into docs/metric_keys.md

describe dt.entity.host                -- these into docs/entity_schemas.md
describe dt.entity.service
describe dt.entity.process_group
describe logs
describe events
describe spans
describe bizevents
```
</details>

## MCP server

The container runs an [MCP](https://modelcontextprotocol.io) server for Claude Code, Claude Desktop, Cursor and other clients:

- `dql_search(question)` returns the matching reference pages; your client's model writes the DQL. It is always on and needs no key.
- `dql_generate(question)` returns a finished query from a model you configure with `LLM_PROVIDER` (Bedrock, Ollama, vLLM or any OpenAI-compatible server; see [.env.example](.env.example)). It is off until you set one.

```bash
docker build -t dql-kb-mcp .      # where PyPI and Hugging Face are reachable; about 2.5 GB
docker run --rm -i dql-kb-mcp     # stdio; runs with no network
```

```jsonc
{ "mcpServers": { "dql-kb": { "command": "docker", "args": ["run", "--rm", "-i", "dql-kb-mcp"] } } }
```

Without Docker, `./quickstart.sh --with-rag` installs the same stack into `.venv`; then `python dql_rag.py query "…"` works from the command line. Retrieval settings (`EMBEDDING_MODEL`, `CHUNK_SIZE`, `TOP_K`) and the Ollama model comparison are in [ARCHITECTURE.md](ARCHITECTURE.md#retrieval-and-generation) and [evaluations/ollama-dql.md](evaluations/ollama-dql.md).

## Also in this repo

- `./util/dt_trace_profiler.sh` ranks trace entry points and flags the ones that look like batch jobs. See [util/dt_trace_profiler.md](util/dt_trace_profiler.md).
- `./util/dt_incident.sh` resolves a name or problem id to an entity and writes an incident brief. See [util/dt_incident.md](util/dt_incident.md).
- `util/tests/`: `python -m unittest discover -s util/tests`. CI runs these tests with `ruff`, with no credentials.
- [evaluations/](evaluations/): model test results, kept out of `docs/` so they are not read as DQL reference.
