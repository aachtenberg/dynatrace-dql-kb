# DQL RAG Pipeline

A local Retrieval-Augmented Generation system for Dynatrace Query Language. Ask questions in plain English, get accurate DQL queries back — grounded in your actual documentation and query examples.

## How It Works

```
 "Show me hosts with high CPU"
  │
  ▼
 Embed question            (sentence-transformers, runs locally)
  │
  ▼
 Search ChromaDB           (cosine similarity, top-K chunks)
  │
  ▼
 Build prompt              (system + retrieved context + question)
  │
  ▼
 LLM API call              (Claude / OpenAI / Azure OpenAI / Ollama)
  │
  ▼
 DQL query + explanation
```

1. **Ingest** — Documents in `docs/` are split into overlapping chunks (~800 tokens). Each chunk is embedded locally using a sentence-transformer model and stored in ChromaDB.
2. **Retrieve** — Your question is embedded with the same model. ChromaDB returns the 6 most similar chunks via cosine similarity.
3. **Generate** — Retrieved chunks are injected into the LLM system prompt as reference material. The LLM writes a DQL query grounded in the documentation.

## Quick Start

### 1. Install

```bash
python -m venv venv
source venv/bin/activate   # Linux/Mac
# venv\Scripts\activate    # Windows

pip install -r requirements.txt
```

### 2. Set your API key

```bash
# Pick one:
export LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...

# OR
export LLM_PROVIDER=openai
export OPENAI_API_KEY=sk-...

# OR (Azure)
export LLM_PROVIDER=azure_openai
export AZURE_OPENAI_ENDPOINT=https://your-instance.openai.azure.com/
export AZURE_OPENAI_API_KEY=your-key
export AZURE_OPENAI_DEPLOYMENT=gpt-4o

# OR (Ollama - fully local, no API key needed)
export LLM_PROVIDER=ollama
export OLLAMA_MODEL=mistral-small3.2:24b   # any model you've pulled
# export OLLAMA_BASE_URL=http://localhost:11434   # default
```

### 3. Ingest the docs

```bash
python dql_rag.py ingest
```

### 4. Ask questions

```bash
# Single query
python dql_rag.py query "Show me error logs from the payment service in the last hour"

# Interactive mode
python dql_rag.py interactive
```

## Knowledge Base

The `docs/` directory contains the DQL reference material that powers the RAG pipeline:

| File | Description |
|------|-------------|
| `dql_syntax_reference.md` | DQL language reference — commands, functions, data types |
| `dql_example_queries.md` | Working query examples (hosts, logs, spans, K8s, etc.) |
| `dql_tips_and_patterns.md` | Common mistakes and best practices |
| `dashboard_json_schema.md` | New Grail dashboard JSON format + Terraform deployment |

### Adding your own docs

Drop files into `docs/` and re-run `python dql_rag.py ingest`. Supported formats: `.md`, `.txt`, `.dql`, `.json`, `.yaml`, `.yml`.

Things worth adding:
- Your team's existing DQL queries
- Entity types and metric keys specific to your environment
- Custom attributes and tags you use
- Runbook DQL snippets

## Configuration

Edit the `Config` class in `dql_rag.py` or use environment variables:

| Setting | Default | Description |
|---------|---------|-------------|
| `LLM_PROVIDER` | `anthropic` | `anthropic`, `openai`, `azure_openai`, or `ollama` |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Local sentence-transformer model |
| `CHUNK_SIZE` | `800` | Tokens per chunk (~4 chars/token) |
| `CHUNK_OVERLAP` | `100` | Overlap between chunks |
| `TOP_K` | `10` | Number of chunks to retrieve |

## Tips

- **Verbose mode** — In interactive mode, type `verbose` to see which chunks were retrieved and their relevance scores.
- **Chunk tuning** — If answers miss relevant context, try increasing `TOP_K` or decreasing `CHUNK_SIZE`.
- **Embeddings are free** — The sentence-transformer runs locally on CPU. You only pay for the LLM generation call.

## Project Structure

```
├── dql_rag.py              # RAG pipeline (ingest, retrieve, generate)
├── requirements.txt        # Python dependencies
└── docs/                   # Knowledge base (ingested into ChromaDB)
    ├── dql_syntax_reference.md
    ├── dql_example_queries.md
    ├── dql_tips_and_patterns.md
    └── dashboard_json_schema.md
```
