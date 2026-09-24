# Ollama model comparison

2026-09-24. One snapshot. Re-run this before changing `OLLAMA_MODEL`.

Kept out of `docs/` so `dql_rag.py ingest` does not treat it as DQL reference.

## Pick

| Use | Tag |
|-----|-----|
| Default (`dql_rag.py query`, `@dql-expert`, `@dashboard-builder`) | `qwen3:8b` |

`gpt-oss:20b` is the runner-up. On the RAG path it returns host ids instead of names.

## Setup

| Item | Value |
|------|-------|
| Server | Ollama 0.34.4 at `127.0.0.1:11434` (0.15.6 rejected `gemma4:12b` and `gpt-oss:20b`) |
| Call | Native `POST /api/chat`. `/v1/chat/completions` ignores `num_ctx` and kept ~2050 of a 7–9k token prompt. Those runs were dropped. |
| Window | `num_ctx` 16384, `think` off, temperature 0, `num_predict` 2048. Journal: `-c 16384`, no truncation. |
| GPU | ~16 GB NVIDIA, WSL2 |
| Skipped | `llava:7b`, `llava:13b`, `llama3.2-vision:11b`, `nomic-embed-text` |

| Surface | Prompt | Chunks |
|---------|--------|--------|
| RAG (`dql_rag.ask`, same as `dql_rag.py query` and `dql_generate`) | `SYSTEM_PROMPT` in `dql_rag.py` | top 10 |
| `@dql-expert` | `.github/agents/dql-expert.md` plus `dql_search` text | top 8 |
| `@dashboard-builder` | `.github/agents/dashboard-builder.md` plus `dql_search` text | top 8 |

Retrieval: ingested `docs/`, `all-MiniLM-L6-v2`, Chroma, offline. Agent runs call `dql_rag.retrieve` and format it the way `dql_search` does.

## Questions

1. `hosts with CPU above 90% in the last hour`
2. `error logs grouped by host in the last 30 minutes`
3. Dashboard only: `Build a new-format dashboard with one data tile for hosts with CPU above 90% in the last hour.`

## Pass bar

| Task | Required |
|------|----------|
| CPU | `timeseries` (not `fetch` of the metric), named agg, `scalar:true`, `by:{}`, `from:-1h`, `filter > 90` |
| Logs | `fetch logs`, quoted `"ERROR"`, `timestamp >= now() - 30m`, `summarize count(), by:{}` |
| Dashboard | `"version": 15`, `"type": "data"`, no Classic (`tileType`, `bounds`, `builtin:`), CPU bar on the tile query |

Host-name `lookup` is noted, not required. Queries were not run on a tenant. The reference uses `status == "ERROR"`.

## Results

Times are CPU question, then logs question.

### RAG

| Model | CPU | Logs | Time |
|-------|-----|------|------|
| `qwen3:8b` | Pass + names | Pass | 10s, 3s |
| `gemma4:12b` | Pass | Pass | 17s, 4s |
| `gpt-oss:20b` | Pass, host ids | Pass | 19s, 4s |
| `qwen2.5:7b-instruct-q8_0` | Miss `from:-1h` | Pass | 20s, 3s |
| `qwen3:14b` | Miss `from:-1h` | Pass | 16s, 4s |
| `glm-4.7-flash:latest` | Miss `from:-1h` | Pass | 33s, 11s |

Log answers matched: `fetch logs`, both filters, `summarize error_count = count(), by:{host.name}`, `sort`.

`qwen3:8b` CPU query:

```dql
timeseries cpu_usage=avg(dt.host.cpu.usage, scalar:true), by:{dt.entity.host}, from:-1h
| filter cpu_usage > 90
| lookup [fetch dt.entity.host | fields id, entity.name],
    sourceField:dt.entity.host, lookupField:id
| fields entity.name, cpu_usage
| sort cpu_usage desc
```

### `@dql-expert`

| Model | CPU | Logs | Time |
|-------|-----|------|------|
| `qwen3:8b` | Pass + names | Pass (`by:{dt.entity.host}`, then lookup) | 11s, 5s |
| `gpt-oss:20b` | Pass + names | Pass, `#` comment inside the query | 19s, 7s |
| `gemma4:12b` | Pass | Pass | 12s, 4s |
| `qwen2.5:7b-instruct-q8_0` | Miss `from:-1h` | Pass | 14s, 4s |
| `qwen3:14b` | Miss `from:-1h` | Pass | 15s, 6s |
| `glm-4.7-flash:latest` | Miss `from:-1h` | Pass | 30s, 8s |

### `@dashboard-builder`

All six returned version 15 and a data tile.

| Model | Tile query | Time |
|-------|------------|------|
| `gpt-oss:20b` | Pass + sort | 27s |
| `glm-4.7-flash:latest` | Pass | 43s |
| `gemma4:12b` | Miss `scalar:true` | 22s |
| `qwen3:14b` | Miss `from:-1h` | 22s |
| `qwen3:8b` | `from:-1h` only. Miss filter and `by:` | 14s |
| `qwen2.5:7b-instruct-q8_0` | `avg(...) > 90` inside `timeseries` | 20s |

## Example fix, same day

| File | Change |
|------|--------|
| `@dql-expert`, `copilot-instructions.md` | Name-lookup example gained `from:-1h` |
| `dql.instructions.md` | Scalar example is the full query (filter + lookup) |
| `@dashboard-builder`, `dashboard.instructions.md` | Sample tile: `timeseries usage=avg(dt.host.cpu.usage, scalar:true), by:{dt.entity.host}, from:-1h \| filter usage > 90` on a table. DQL rules are in the file. |

`docs/` was not changed. Re-ran `qwen3:8b` and `gpt-oss:20b` only. Window 16384, no truncation.

| Surface | `qwen3:8b` | `gpt-oss:20b` |
|---------|------------|---------------|
| RAG | Same as above | Same as above (host ids) |
| `@dql-expert` | Pass + names | Pass + names. Log comment gone. |
| `@dashboard-builder` | Pass, 11s | Pass, 15s |

## Repeat

```bash
export LLM_PROVIDER=ollama
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export OLLAMA_NUM_CTX=16384
export OLLAMA_MODEL=qwen3:8b
python dql_rag.py query "hosts with CPU above 90% in the last hour"
python dql_rag.py query "error logs grouped by host in the last 30 minutes"
```

Agent check: system message is the agent file, user message is the question plus `dql_search` excerpts, same `/api/chat` options. Discard the run if the journal shows truncation.

## Frontier check

`gemini-3.1-pro-preview` via the Gemini API. Same questions, same prompts, temperature 0. Not the default. Locked-down hosts do not call this.

| Surface | CPU / tile | Logs | Time |
|---------|------------|------|------|
| RAG | Pass + names | Pass | 6s, 5s |
| `@dql-expert` | Pass + names | Pass | 6s, 5s |
| `@dashboard-builder` | Pass, version 15, table | — | 13s |

Re-checked after the Kubernetes examples were ingested. Same model. Thinking left on (this model rejects a zero thinking budget).

| Question | RAG | `@dql-expert` |
|----------|-----|---------------|
| Host CPU > 90%, 1h | Pass | Pass |
| Error logs by host, 30m | Pass | Pass |
| Container CPU by namespace, 1h | `dt.kubernetes.container.cpu_usage`, split `dt.entity.cloud_application_namespace` | Pass (`k8s.namespace.name`) |
| Which clusters are k3s | Pass | Pass |
| Pod restarts, 6h | Pass | Pass |

`@dashboard-builder` for namespace CPU: version 15, right metric, split `dt.entity.kubernetes_namespace`. JSON cut off before the document closed. Both alternate namespace fields returned rows. The example in the agent uses `k8s.namespace.name`.

## Namespace fix, same day

The Kubernetes example sat at rank 13, so RAG never saw it (top 10). The dashboard sample was a long `visualizationSettings` blob and the JSON ran out of tokens.

| Change | Why |
|--------|-----|
| `docs/kubernetes.md` | Short page. Ranks 1 for "container CPU by namespace". |
| Dashboard sample | Short table tile plus a line chart: `timeseries avg(dt.kubernetes.container.cpu_usage), by:{k8s.namespace.name}, from:-1h` |

Re-ingested (44 chunks, 8 files). Same Gemini model.

| Surface | Result |
|---------|--------|
| RAG | Pass. `by:{k8s.namespace.name}`, `from:-1h`. 5s. |
| `@dashboard-builder` | Pass. Version 15, `lineChart`, same query, JSON closed. 6s. |
