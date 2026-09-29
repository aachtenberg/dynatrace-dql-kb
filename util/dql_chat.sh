#!/usr/bin/env bash
# Wrapper for util/dql_chat.py. Forwards every argument.
# Config comes from .env in the repo root. Guide: util/dql_chat.md
#
#   ./util/dql_chat.sh                  # opens the chat in your browser
#   ./util/dql_chat.sh --no-browser     # print the link instead
#
# No virtualenv and no pip install. Stdlib only.
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=find_python.sh
source util/find_python.sh
find_python
exec "${PY[@]}" util/dql_chat.py "$@"
