#!/usr/bin/env bash
# Wrapper for util/dt_trace_profiler.py. Forwards every argument.
# Config comes from .env in the repo root, or from DT_ENVIRONMENT_URL / DT_API_TOKEN.
#
#   ./util/dt_trace_profiler.sh --days 1 --shape-top 5
#   ./util/dt_trace_profiler.sh --help
#
# No virtualenv. The profiler is stdlib only.
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=find_python.sh
source util/find_python.sh
find_python
exec "${PY[@]}" util/dt_trace_profiler.py "$@"
