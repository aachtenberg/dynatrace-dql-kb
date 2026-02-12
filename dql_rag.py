"""
DQL RAG Pipeline - Retrieval-Augmented Generation for Dynatrace Query Language

This script builds a local RAG system that:
1. Ingests DQL documentation and example queries
2. Stores them as embeddings in a local ChromaDB vector database
3. Retrieves relevant context when you ask a question
4. Sends the question + context to an LLM API to generate accurate DQL

Usage:
    # First time: ingest your docs
    python dql_rag.py ingest

    # Then query:
    python dql_rag.py query "Show me hosts with CPU above 90% in the last hour"

    # Interactive mode:
    python dql_rag.py interactive
"""

import os
import sys
import json
import hashlib
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class Config:
    """Central configuration - edit these values for your environment."""

    # LLM Provider: "anthropic", "openai", "azure_openai", or "ollama"
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")

    # API Keys (set via environment variables)
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

    # Azure OpenAI (if using Azure)
    AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
    AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

    # Ollama (local)
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral-small3.2:24b")

    # Model settings
    ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
    OPENAI_MODEL = "gpt-4o"

    # Embedding model (using sentence-transformers locally - no API key needed)
    EMBEDDING_MODEL = "all-MiniLM-L6-v2"

    # ChromaDB persistence directory
    CHROMA_DIR = os.path.join(os.path.dirname(__file__), "chroma_db")

    # Document source directory
    DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")

    # Chunking parameters
    CHUNK_SIZE = 800       # tokens (approximate, using characters / 4)
    CHUNK_OVERLAP = 100    # overlap between chunks

    # Retrieval parameters
    TOP_K = 10             # number of chunks to retrieve


# ---------------------------------------------------------------------------
# Document Chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, chunk_size: int = Config.CHUNK_SIZE,
               overlap: int = Config.CHUNK_OVERLAP) -> list[str]:
    """
    Split text into overlapping chunks.
    Uses character-based splitting with ~4 chars per token approximation.
    Tries to split on paragraph/sentence boundaries when possible.
    """
    char_chunk = chunk_size * 4
    char_overlap = overlap * 4

    if len(text) <= char_chunk:
        return [text.strip()] if text.strip() else []

    chunks = []
    start = 0
    while start < len(text):
        end = start + char_chunk

        # Try to find a clean break point (paragraph, then sentence, then word)
        if end < len(text):
            # Look for paragraph break
            para_break = text.rfind("\n\n", start + char_chunk // 2, end)
            if para_break != -1:
                end = para_break + 2
            else:
                # Look for sentence break
                for sep in [". ", ".\n", ";\n", "\n"]:
                    sent_break = text.rfind(sep, start + char_chunk // 2, end)
                    if sent_break != -1:
                        end = sent_break + len(sep)
                        break
                else:
                    # Look for word break
                    word_break = text.rfind(" ", start + char_chunk // 2, end)
                    if word_break != -1:
                        end = word_break + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end - char_overlap
        if start >= len(text):
            break

    return chunks


# ---------------------------------------------------------------------------
# Vector Store (ChromaDB)
# ---------------------------------------------------------------------------

def get_collection():
    """Get or create the ChromaDB collection with the embedding function."""
    import chromadb
    from chromadb.utils import embedding_functions

    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=Config.EMBEDDING_MODEL
    )

    client = chromadb.PersistentClient(path=Config.CHROMA_DIR)
    collection = client.get_or_create_collection(
        name="dql_docs",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"}
    )
    return collection


def ingest_documents():
    """
    Read all files from the docs directory, chunk them, and store in ChromaDB.
    Supports .txt, .md, .json, and .dql files.
    """
    docs_path = Path(Config.DOCS_DIR)
    if not docs_path.exists():
        print(f"Creating docs directory at: {docs_path}")
        docs_path.mkdir(parents=True)
        _create_sample_docs(docs_path)
        print("Sample DQL documentation created. Add your own docs and re-run ingest.")

    collection = get_collection()

    supported_extensions = {".txt", ".md", ".json", ".dql", ".yaml", ".yml"}
    all_chunks = []
    all_ids = []
    all_metadata = []

    for filepath in sorted(docs_path.rglob("*")):
        if filepath.suffix.lower() not in supported_extensions:
            continue
        if filepath.name.startswith("."):
            continue

        print(f"  Processing: {filepath.name}")
        text = filepath.read_text(encoding="utf-8", errors="ignore")

        chunks = chunk_text(text)
        for i, chunk in enumerate(chunks):
            # Deterministic ID based on content hash
            chunk_id = hashlib.md5(
                f"{filepath.name}:{i}:{chunk[:100]}".encode()
            ).hexdigest()

            all_chunks.append(chunk)
            all_ids.append(chunk_id)
            all_metadata.append({
                "source": filepath.name,
                "chunk_index": i,
                "total_chunks": len(chunks)
            })

    if not all_chunks:
        print("No documents found to ingest.")
        return

    # ChromaDB upsert (handles duplicates gracefully)
    # Process in batches of 100 (ChromaDB recommendation)
    batch_size = 100
    for i in range(0, len(all_chunks), batch_size):
        collection.upsert(
            ids=all_ids[i:i + batch_size],
            documents=all_chunks[i:i + batch_size],
            metadatas=all_metadata[i:i + batch_size]
        )

    print(f"\nIngested {len(all_chunks)} chunks from "
          f"{len(set(m['source'] for m in all_metadata))} files.")
    print(f"Vector DB stored at: {Config.CHROMA_DIR}")


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def retrieve(query: str, top_k: int = Config.TOP_K) -> list[dict]:
    """
    Retrieve the most relevant document chunks for a given query.
    Returns list of {text, source, score} dicts.
    """
    collection = get_collection()
    results = collection.query(
        query_texts=[query],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )

    retrieved = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0]
    ):
        retrieved.append({
            "text": doc,
            "source": meta.get("source", "unknown"),
            "score": round(1 - dist, 3)  # cosine distance → similarity
        })

    return retrieved


# ---------------------------------------------------------------------------
# LLM Call
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a DQL (Dynatrace Query Language) query generator.
Your ONLY job is to produce syntactically correct, working DQL queries.

CRITICAL RULES — violating any of these produces broken queries:

1. METRICS USE `timeseries`, NOT `fetch`.
   - dt.host.cpu.usage, dt.host.memory.usage, dt.host.disk.*, dt.host.network.*,
     dt.service.request.*, dt.containers.cpu.* — these are ALL metrics.
   - CORRECT:  timeseries avg(dt.host.cpu.usage), by:{{dt.entity.host}}
   - WRONG:    fetch dt.host.cpu.usage
   - If the user asks about CPU, memory, disk, network, request count/duration,
     or any time-series numeric measurement → use `timeseries`.

2. `fetch` is ONLY for: logs, events, bizevents, spans, entities (dt.entity.*),
   dt.system.data_objects. Nothing else.

3. `by:` ALWAYS uses curly braces: by:{{field}} or by:{{field1, field2}}
   - WRONG: by: host.name
   - WRONG: by: (host.name)
   - CORRECT: by:{{host.name}}

4. `makeTimeseries` is ONLY for creating time series from non-metric data
   (logs, events, spans). It requires numeric aggregation functions.
   NEVER use makeTimeseries for actual metrics — use `timeseries`.

5. String values in filters MUST be quoted: filter status == "ERROR"
   WRONG: filter status == ERROR

6. Time ranges:
   - timeseries: use from: parameter → timeseries avg(dt.host.cpu.usage), from:-1h
   - fetch: use filter → | filter timestamp >= now() - 1h

7. Iterative expressions: when timeseries returns arrays, use [] for element-wise ops:
   | fieldsAdd available = 100 - cpu[]

8. Do NOT invent DQL commands or functions. Use ONLY what appears in the reference
   material below. If you're not sure a function exists, say so.

9. Do NOT use SQL syntax. DQL is pipe-based, not SQL. There is no SELECT, FROM,
   WHERE, GROUP BY, HAVING, or ORDER BY in DQL.

Output format:
- Put the DQL query in a code block
- One sentence explaining what it does
- If you made assumptions, state them

Reference material (use ONLY syntax shown here):
{context}
"""


def call_llm(query: str, context: str) -> str:
    """Send the query + retrieved context to the configured LLM."""

    system = SYSTEM_PROMPT.format(context=context)

    if Config.LLM_PROVIDER == "anthropic":
        return _call_anthropic(system, query)
    elif Config.LLM_PROVIDER == "openai":
        return _call_openai(system, query)
    elif Config.LLM_PROVIDER == "azure_openai":
        return _call_azure_openai(system, query)
    elif Config.LLM_PROVIDER == "ollama":
        return _call_ollama(system, query)
    else:
        raise ValueError(f"Unknown LLM provider: {Config.LLM_PROVIDER}")


def _call_anthropic(system: str, query: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=Config.ANTHROPIC_MODEL,
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": query}]
    )
    return response.content[0].text


def _call_openai(system: str, query: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=Config.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=Config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": query}
        ],
        max_tokens=2048
    )
    return response.choices[0].message.content


def _call_azure_openai(system: str, query: str) -> str:
    from openai import AzureOpenAI
    client = AzureOpenAI(
        api_key=Config.AZURE_OPENAI_API_KEY,
        azure_endpoint=Config.AZURE_OPENAI_ENDPOINT,
        api_version="2024-02-01"
    )
    response = client.chat.completions.create(
        model=Config.AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": query}
        ],
        max_tokens=2048
    )
    return response.choices[0].message.content


def _call_ollama(system: str, query: str) -> str:
    from openai import OpenAI
    client = OpenAI(
        base_url=f"{Config.OLLAMA_BASE_URL}/v1",
        api_key="ollama"  # required by client but unused by Ollama
    )
    response = client.chat.completions.create(
        model=Config.OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": query}
        ],
        max_tokens=2048
    )
    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

def ask(query: str, verbose: bool = False) -> str:
    """
    Full RAG pipeline: retrieve context → build prompt → call LLM.
    """
    # Step 1: Retrieve relevant chunks
    chunks = retrieve(query)

    if verbose:
        print("\n--- Retrieved Context ---")
        for i, c in enumerate(chunks):
            print(f"[{i+1}] (score: {c['score']}) {c['source']}")
            print(f"    {c['text'][:120]}...")
        print("--- End Context ---\n")

    # Step 2: Format context
    context_parts = []
    for i, chunk in enumerate(chunks):
        context_parts.append(
            f"--- Source: {chunk['source']} (relevance: {chunk['score']}) ---\n"
            f"{chunk['text']}"
        )
    context = "\n\n".join(context_parts)

    # Step 3: Call LLM
    return call_llm(query, context)


def interactive_mode():
    """Interactive REPL for asking DQL questions."""
    print("=" * 60)
    print("DQL RAG Assistant - Interactive Mode")
    print("Type 'quit' to exit, 'verbose' to toggle context display")
    print("=" * 60)

    verbose = False
    while True:
        try:
            query = input("\n🔍 Ask about DQL: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not query:
            continue
        if query.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break
        if query.lower() == "verbose":
            verbose = not verbose
            print(f"Verbose mode: {'ON' if verbose else 'OFF'}")
            continue

        try:
            response = ask(query, verbose=verbose)
            print(f"\n{response}")
        except Exception as e:
            print(f"\nError: {e}")
            print("Make sure your API key is set and docs are ingested.")


# ---------------------------------------------------------------------------
# Sample Documentation (bootstrap)
# ---------------------------------------------------------------------------

def _create_sample_docs(docs_path: Path):
    """Create a placeholder directing users to the pre-built docs."""
    (docs_path / "README.md").write_text("""\
# DQL RAG Documentation

This directory should contain DQL reference documentation.

If you're seeing this placeholder, the pre-built docs were not included.
Run `python dql_rag.py ingest` after adding your documentation files here.

Recommended files to add:
- dql_syntax_reference.md (DQL command and function reference)
- dql_example_queries.md (working query examples)
- dql_tips_and_patterns.md (common patterns and mistakes)
- dashboard_json_schema.md (new Grail dashboard JSON format)
- Your team's own DQL queries and dashboard templates
""")

    print(f"  Created sample docs in {docs_path}/")


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "ingest":
        print("Ingesting documents...")
        ingest_documents()

    elif command == "query":
        if len(sys.argv) < 3:
            print("Usage: python dql_rag.py query \"your question here\"")
            sys.exit(1)
        query = " ".join(sys.argv[2:])
        response = ask(query, verbose=True)
        print(f"\n{response}")

    elif command == "interactive":
        interactive_mode()

    else:
        print(f"Unknown command: {command}")
        print("Commands: ingest, query, interactive")
        sys.exit(1)


if __name__ == "__main__":
    main()
