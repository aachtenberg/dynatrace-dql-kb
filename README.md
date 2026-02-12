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

The generic DQL grammar is complete, but LLMs will still hallucinate **metric keys** and **field names** because those are environment-specific. Fix this by running these queries in a Dynatrace Notebook and pasting the output into the placeholder files:

```
-- All metric keys → paste into docs/metric_keys.md
metrics | fields metricId, description, unit | sort metricId asc

-- Entity/log/span schemas → paste into docs/entity_schemas.md
describe dt.entity.host
describe dt.entity.service
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

Or configure manually:

```bash
# Pick a provider:
export LLM_PROVIDER=ollama                          # local
export OLLAMA_MODEL=mistral-small3.2:24b
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
├── quickstart.sh                        # Quick start (Ollama)
└── requirements.txt                     # Python dependencies
```
