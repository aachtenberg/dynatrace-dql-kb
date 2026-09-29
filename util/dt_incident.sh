#!/usr/bin/env bash
# Wrapper for util/dt_incident.py. Forwards every argument.
# Config comes from .env in the repo root, or from DT_ENVIRONMENT_URL / DT_API_TOKEN.
#
#   ./util/dt_incident.sh resolve "payments-api"
#   ./util/dt_incident.sh brief "payments-api"
#   ./util/dt_incident.sh brief P-12345
#   ./util/dt_incident.sh --help
#
# No virtualenv. The tool is stdlib only.
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=find_python.sh
source util/find_python.sh
find_python
exec "${PY[@]}" util/dt_incident.py "$@"
