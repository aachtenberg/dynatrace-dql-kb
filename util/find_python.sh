# Source from another bash script. Sets the PY array to a Python 3.10+
# that actually starts.
#
# On Windows Git Bash, python3 is often the Microsoft Store alias: it is on
# PATH, and running it prints "Python was not found". python or `py -3` is
# the interpreter installed by the company software center.

_py_ok() {
  "$@" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

find_python() {
  if _py_ok python3; then
    PY=(python3)
  elif _py_ok python; then
    PY=(python)
  elif _py_ok py -3; then
    PY=(py -3)
  else
    echo "ERROR: Python 3.10 or newer was not found." >&2
    echo "On Git Bash, run: python --version" >&2
    echo "If that prints 3.10 or newer, python3 is the Microsoft Store alias and is ignored here." >&2
    return 1
  fi
}
