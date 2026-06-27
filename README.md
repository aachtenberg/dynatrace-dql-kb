# Dynatrace DQL Knowledge Base

DQL reference docs, Copilot agents, and a RAG pipeline that make LLMs produce **working** Dynatrace Query Language instead of the usual hallucinated garbage.

## GitHub Copilot Agents

Open this repo in VS Code with Copilot enabled. Two agents are available in Copilot Chat:

### `@dql-expert`
Writes syntactically correct DQL queries. Knows the critical rules that LLMs always get wrong:
- Metrics use `timeseries`, never `fetch`
- `by:` requires curly braces: `by:{host.name}`
- No SQL syntax — DQL is pipe-based
- `makeTimeseries` is only for logs/events/spans, not metrics
- All common metric keys, aggregation functions, string functions, etc.

```
@dql-expert show me hosts with CPU above 90% in the last hour
@dql-expert error logs from the payment service grouped by host
@dql-expert week-over-week CPU comparison
```

### `@dashboard-builder`
Generates Grail/Platform dashboard JSON (the new format, not Classic). Knows the full tile schema, grid layout system, all visualization types, and Terraform deployment with `dynatrace_document`.

```
@dashboard-builder create a host overview dashboard with CPU, memory, and error logs
@dashboard-builder add a single-value tile showing total error count
```

### How it works
Copilot picks up context from three layers in this repo:

| Layer | File | Scope |
|-------|------|-------|
| Global instructions | `.github/copilot-instructions.md` | Attached to every Copilot request |
| File-type instructions | `.github/instructions/dql.instructions.md` | Applied when editing `.dql` or `.md` files |
| File-type instructions | `.github/instructions/dashboard.instructions.md` | Applied when editing dashboard JSON |
| Agents | `.github/agents/dql-expert.md` | Invoked with `@dql-expert` in Chat |
| Agents | `.github/agents/dashboard-builder.md` | Invoked with `@dashboard-builder` in Chat |

The `docs/` directory also serves as searchable workspace context when Copilot Chat is in Agent Mode.

## Knowledge Base

The `docs/` directory contains DQL reference material:

| File | What's in it |
|------|-------------|
| `dql_syntax_reference.md` | Commands, functions, operators, data types — the full language reference |
| `dql_example_queries.md` | 40+ working query examples: hosts, logs, spans, K8s, entities, advanced patterns |
| `dql_tips_and_patterns.md` | Common mistakes and how to avoid them |
| `dql_wrong_vs_right.md` | 17 explicit wrong→right pairs for every hallucination LLMs produce |
| `dashboard_json_schema.md` | Grail dashboard JSON format, tile types, visualizations, Terraform |
| `metric_keys.md` | **Your environment's** metric keys (populate from Notebooks — see below) |
| `entity_schemas.md` | **Your environment's** entity/log/span field schemas (populate from Notebooks) |

### Populate with your environment data

The generic DQL grammar is complete, but LLMs will still hallucinate **metric keys** and **field names** because those are environment-specific. Populate the two placeholder docs (`docs/metric_keys.md`, `docs/entity_schemas.md`) from your live tenant.

#### Automated — `dt_fetch.py` (recommended)

Queries the Dynatrace Grail API directly and writes both docs. Stdlib only — no extra dependencies.

```bash
cp .env.example .env          # then fill in DT_ENVIRONMENT_URL and DT_API_TOKEN
python dt_fetch.py test       # verify token + connectivity (one tiny query)
python dt_fetch.py all        # populate metric_keys.md + entity_schemas.md
# or individually: python dt_fetch.py metrics | schemas
```

`.env` config (also read from real environment variables):

| Variable | Example | Notes |
|----------|---------|-------|
| `DT_ENVIRONMENT_URL` | `https://abc12345.apps.dynatrace.com` | Platform/apps URL, no trailing slash |
| `DT_API_TOKEN` | `dt0c01...` or `dt0s16...` | Auth scheme auto-detected: classic API token (`dt0c01`) → `Api-Token`, platform token (`dt0s16`) → `Bearer` |

Required Grail read scopes: `storage:metrics:read`, `storage:entities:read`, `storage:logs:read`, `storage:events:read`, `storage:bizevents:read`, `storage:spans:read`, `storage:buckets:read`.

The script uses `describe <source>` for schemas (returns full field lists even when a source has no data), raises the API `maxResultRecords` so all metric keys come back, and dedups repeated keys. `.env` is gitignored — your token is never committed.

#### Manual — Dynatrace Notebook

Prefer copy-paste? Run these in a Notebook and paste the output into the placeholder files:

```
-- All metric keys → paste into docs/metric_keys.md
metrics | sort metric.key asc

-- Entity/log/span field discovery → paste into docs/entity_schemas.md
describe dt.entity.host
describe dt.entity.service
describe dt.entity.process_group
describe logs
describe events
describe spans
describe bizevents
```

### Adding your own docs

Drop files into `docs/` — your team's DQL queries, metric keys, entity types, runbook snippets. The more real examples, the better the results. Supported formats: `.md`, `.txt`, `.dql`, `.json`, `.yaml`, `.yml`.

## RAG Pipeline (Optional)

A standalone CLI tool that uses the same knowledge base with a local vector DB for retrieval-augmented generation.

### Quick Start

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
./quickstart.sh
```

> **Prerequisite (Debian/Ubuntu):** the stdlib `venv`/`pip` flow needs the
> `python3-venv` and `python3-pip` packages. If `python -m venv` fails with an
> `ensurepip is not available` error, install them first:
> ```bash
> sudo apt install python3-venv python3-pip
> ```

**Alternative — [`uv`](https://github.com/astral-sh/uv)** (faster, no system pip needed):

```bash
uv venv && uv pip install -r requirements.txt
uv run python dql_rag.py ingest
uv run python dql_rag.py interactive
```

Or configure manually:

```bash
# Pick a provider:
export LLM_PROVIDER=ollama                          # local
export OLLAMA_MODEL=qwen3.6:27b
export OLLAMA_BASE_URL=http://192.168.0.150:11434

# OR
export LLM_PROVIDER=anthropic && export ANTHROPIC_API_KEY=sk-ant-...

# OR
export LLM_PROVIDER=openai && export OPENAI_API_KEY=sk-...

# Ingest and query:
python dql_rag.py ingest
python dql_rag.py query "Show me error logs from the payment service"
python dql_rag.py interactive
```

### Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `LLM_PROVIDER` | `anthropic` | `anthropic`, `openai`, `azure_openai`, or `ollama` |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Local sentence-transformer model |
| `CHUNK_SIZE` | `800` | Tokens per chunk (~4 chars/token) |
| `CHUNK_OVERLAP` | `100` | Overlap between chunks |
| `TOP_K` | `10` | Number of chunks to retrieve |

## Project Structure

```
├── .github/
│   ├── copilot-instructions.md          # Global DQL rules for Copilot
│   ├── instructions/
│   │   ├── dql.instructions.md          # DQL file-type instructions
│   │   └── dashboard.instructions.md    # Dashboard JSON instructions
│   └── agents/
│       ├── dql-expert.md                # @dql-expert agent
│       └── dashboard-builder.md         # @dashboard-builder agent
├── docs/                                # Knowledge base
│   ├── dql_syntax_reference.md
│   ├── dql_example_queries.md
│   ├── dql_tips_and_patterns.md
│   ├── dql_wrong_vs_right.md
│   ├── dashboard_json_schema.md
│   ├── metric_keys.md              # Your env's metrics (populate from Notebooks)
│   └── entity_schemas.md           # Your env's schemas (populate from Notebooks)
├── dql_rag.py                           # RAG pipeline CLI
├── dt_fetch.py                          # Populate env docs from a live Dynatrace tenant
├── .env.example                         # Template for DT_ENVIRONMENT_URL / DT_API_TOKEN
├── quickstart.sh                        # Quick start (Ollama)
└── requirements.txt                     # Python dependencies
```
