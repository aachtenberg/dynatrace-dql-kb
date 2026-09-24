#!/usr/bin/env bash
# Run dql_agent.py with the Python already on this machine. Forwards every argument.
# No virtualenv and no pip install. Stdlib only.
#
#   ./dql_agent.sh                 # interactive
#   ./dql_agent.sh "question"      # ask once
#   ./dql_agent.sh --check         # test AWS, the model and the tenant
set -euo pipefail

cd "$(dirname "$0")"
# shellcheck source=util/find_python.sh
source util/find_python.sh
find_python
exec "${PY[@]}" dql_agent.py "$@"
