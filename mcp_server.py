"""
DQL Knowledge Base — MCP server.

Exposes the DQL knowledge base to any MCP-aware agent (Claude Code/Desktop,
Cursor, etc.) as callable tools:

  - dql_search(question)    Retrieve the most relevant DQL reference docs.
                            No LLM key required. Always available.
  - dql_generate(question)  Produce a finished DQL query using the configured
                            LLM provider. Only registered when an LLM is
                            configured (see dql_rag.Config / env vars).

The vector DB must be ingested first (`python dql_rag.py ingest`). In the
Docker image this happens at build time, so the server starts ready to go.

Run directly (stdio transport):
    python mcp_server.py
"""

import sys

import dql_rag
from dql_rag import Config

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    sys.stderr.write(
        "The 'mcp' package is required. Install with: pip install -r requirements-mcp.txt\n"
    )
    raise


mcp = FastMCP("dql-kb")


def _llm_configured() -> bool:
    """Whether dql_generate can actually call a model.
    Ollama needs no key; the API providers need their key set."""
    provider = Config.LLM_PROVIDER
    if provider == "ollama":
        return True
    if provider == "anthropic":
        return bool(Config.ANTHROPIC_API_KEY)
    if provider == "openai":
        return bool(Config.OPENAI_API_KEY)
    if provider == "azure_openai":
        return bool(Config.AZURE_OPENAI_API_KEY and Config.AZURE_OPENAI_ENDPOINT)
    return False


@mcp.tool()
def dql_search(question: str, top_k: int = 8) -> str:
    """Search the Dynatrace Query Language (DQL) knowledge base and return the
    most relevant reference material: syntax rules, working query examples,
    common-mistake fixes, and this environment's metric keys / field schemas.

    Use this BEFORE writing any DQL so the query is grounded in correct syntax
    (metrics use `timeseries` not `fetch`, `by:{...}` needs braces, etc.) and
    real metric keys / field names instead of hallucinated ones.

    Args:
        question: What the user wants to query, in plain language
                  (e.g. "hosts with CPU above 90% in the last hour").
        top_k: How many document chunks to return (default 8).

    Returns:
        Concatenated, source-attributed reference snippets.
    """
    chunks = dql_rag.retrieve(question, top_k=top_k)
    if not chunks:
        return "No knowledge base content found. Has `dql_rag.py ingest` been run?"
    parts = []
    for c in chunks:
        parts.append(
            f"--- Source: {c['source']} (relevance: {c['score']}) ---\n{c['text']}"
        )
    return "\n\n".join(parts)


def _register_generate():
    @mcp.tool()
    def dql_generate(question: str) -> str:
        """Generate a complete, syntactically correct DQL query for the given
        request, using the configured LLM grounded in the knowledge base.

        Returns the DQL query plus a short explanation. Use dql_search instead
        if you want raw reference material to write the query yourself.

        Args:
            question: What to query, in plain language.
        """
        return dql_rag.ask(question)

    return dql_generate


# Generation is opt-in: only expose the tool when a provider is actually usable,
# so the default container has zero secrets and only offers retrieval.
if _llm_configured():
    _register_generate()
    sys.stderr.write(
        f"dql-kb MCP: dql_search + dql_generate (provider={Config.LLM_PROVIDER})\n"
    )
else:
    sys.stderr.write(
        "dql-kb MCP: dql_search only (no LLM configured; set LLM_PROVIDER + key "
        "to enable dql_generate)\n"
    )


if __name__ == "__main__":
    mcp.run()
