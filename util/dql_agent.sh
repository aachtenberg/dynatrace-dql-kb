#!/usr/bin/env bash
# Wrapper for util/dql_agent.py. Forwards every argument.
# Config comes from .env in the repo root. Runbook: util/dql_agent.md
#
#   ./util/dql_agent.sh                 # interactive
#   ./util/dql_agent.sh "question"      # ask once
#   ./util/dql_agent.sh --check         # test AWS, the model and the tenant
#
# No virtualenv and no pip install. Stdlib only.
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=find_python.sh
source util/find_python.sh
find_python
exec "${PY[@]}" util/dql_agent.py "$@"
