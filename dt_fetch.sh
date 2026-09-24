#!/usr/bin/env bash
# Run dt_fetch.py with the Python already on this machine. Forwards every argument.
# No virtualenv and no pip install. Stdlib only.
#
#   ./dt_fetch.sh test
#   ./dt_fetch.sh all
set -euo pipefail

cd "$(dirname "$0")"
# shellcheck source=util/find_python.sh
source util/find_python.sh
find_python
exec "${PY[@]}" dt_fetch.py "$@"
