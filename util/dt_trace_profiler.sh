#!/usr/bin/env bash
# Wrapper for util/dt_trace_profiler.py. Forwards every argument.
# Config comes from .env in the repo root, or from DT_ENVIRONMENT_URL / DT_API_TOKEN.
#
#   ./util/dt_trace_profiler.sh --days 1 --shape-top 5
#   ./util/dt_trace_profiler.sh --help
set -euo pipefail

cd "$(dirname "$0")/.."

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "ERROR: python3 not found on PATH" >&2
  exit 1
fi

exec "$PY" util/dt_trace_profiler.py "$@"
