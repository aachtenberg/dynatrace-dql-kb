#!/usr/bin/env bash
# Get this repo running on a machine you do not administer.
#
#   ./quickstart.sh
#       Checks that Python 3.10+ starts. Installs nothing.
#       Prints the commands for dt_fetch and the trace profiler.
#       If .env exists, runs one tiny Grail query to prove the token.
#
#   ./quickstart.sh --with-rag
#       Also installs the local RAG/MCP stack into .venv.
#       This downloads from PyPI and Hugging Face. Do not use it on a
#       desktop that is not allowed to reach those sites. Build the
#       Docker image on a machine that can, then move the image.
set -euo pipefail

cd "$(dirname "$0")"
# shellcheck source=util/find_python.sh
source util/find_python.sh
find_python

if [[ "${1:-}" == "--with-rag" ]]; then
  echo "Installing the RAG/MCP stack into .venv."
  echo "This needs outbound access to PyPI and Hugging Face."
  if [[ -x .venv/bin/python ]]; then
    VENV_PY=.venv/bin/python
  elif [[ -x .venv/Scripts/python.exe ]]; then
    VENV_PY=.venv/Scripts/python.exe
  else
    "${PY[@]}" -m venv .venv
    if [[ -x .venv/bin/python ]]; then
      VENV_PY=.venv/bin/python
    else
      VENV_PY=.venv/Scripts/python.exe
    fi
  fi
  "$VENV_PY" -m pip install --upgrade pip
  "$VENV_PY" -m pip install torch --index-url https://download.pytorch.org/whl/cpu
  "$VENV_PY" -m pip install -r requirements-mcp.txt
  "$VENV_PY" dql_rag.py ingest
  echo
  echo "Search (no LLM key):"
  echo "  $VENV_PY dql_rag.py query \"hosts with CPU above 90%\""
  echo "MCP server, stdio, retrieval only:"
  echo "  $VENV_PY mcp_server.py"
  exit 0
fi

if [[ -n "${1:-}" ]]; then
  echo "Unknown option: $1" >&2
  echo "Usage: ./quickstart.sh [--with-rag]" >&2
  exit 1
fi

ver="$("${PY[@]}" -c 'import sys; print(sys.version.split()[0])')"
echo "Python ${ver} is available (${PY[*]}). Nothing to install."
echo
echo "Copilot: open this folder in VS Code. The agents are in .github/agents/."
echo
echo "To query your own tenant, copy .env.example to .env and set:"
echo "  DT_ENVIRONMENT_URL=https://<env-id>.apps.dynatrace.com"
echo "  DT_API_TOKEN=<platform token created in that environment>"
echo "The URL must be the apps host, not live.dynatrace.com."
echo "A corporate proxy is picked up from HTTPS_PROXY."
echo
echo "Then:"
echo "  ./dt_fetch.sh test"
echo "  ./dt_fetch.sh all"
echo "  ./util/dt_trace_profiler.sh --days 1 --shape-top 5 --min-runs 10 --max-runs 500"
echo
if [[ -f .env ]]; then
  echo "Found .env. Running one connectivity query..."
  "${PY[@]}" dt_fetch.py test || echo "Connectivity test failed. Check DT_ENVIRONMENT_URL and DT_API_TOKEN in .env."
else
  echo "No .env yet. The docs already in this repo are enough to read and to use with Copilot."
fi
echo
echo "The MCP server and the RAG CLI download PyTorch and an embedding model."
echo "Skip them on a locked-down desktop. Where downloads are allowed:"
echo "  ./quickstart.sh --with-rag"
echo "Or build the Docker image once on a connected machine, then run it offline."
