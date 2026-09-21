#!/usr/bin/env bash
# Wrapper for util/dt_trace_profiler.py. Forwards every argument.
# Config comes from .env in the repo root, or from DT_ENVIRONMENT_URL / DT_API_TOKEN.
#
#   ./util/dt_trace_profiler.sh --days 1 --shape-top 5
#   ./util/dt_trace_profiler.sh --help
#
# No virtualenv. The profiler is stdlib only. On Git Bash, `python3` is often
# the Microsoft Store alias (it is on PATH but does not run). This script
# probes python3, then python, then `py -3`, and uses the first one that runs.
set -euo pipefail

cd "$(dirname "$0")/.."

usable() {
  "$@" -c "import sys; raise SystemExit(0 if sys.version_info[0] >= 3 else 1)" >/dev/null 2>&1
}

if usable python3; then
  PY=(python3)
elif usable python; then
  PY=(python)
elif usable py -3; then
  PY=(py -3)
else
  echo "ERROR: Python 3 was not found." >&2
  echo "On Git Bash, 'python --version' is the one that works. 'python3' is often the Microsoft Store alias." >&2
  exit 1
fi

exec "${PY[@]}" util/dt_trace_profiler.py "$@"
