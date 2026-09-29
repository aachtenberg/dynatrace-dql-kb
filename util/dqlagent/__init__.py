"""The DQL agent: a model that writes DQL, runs it on your Dynatrace tenant and
answers from the records. Standard library only.

    aws      AWS credentials, SigV4 and the Bedrock client (no boto3)
    llm      chat-model adapters: Bedrock, OpenAI-compatible, Ollama, Anthropic
    visuals  charts and graphs built from query results
    core     docs search, name lookup, the DQL check, tools and the agent loop
    web      the browser chat server
    store    chat history and per-user settings, in SQLite

Entry points: util/dql_agent.py (terminal) and util/dql_chat.py (browser).
"""

import sys
from pathlib import Path

# dt_fetch.py lives at the repo root; the agent reuses its Grail client.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
