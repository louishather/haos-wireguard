#!/bin/sh
# run.sh <name> [args] - run .vibe/<name>.py with whatever Python is available,
# without relying on PATH. Same lookup as bootstrap/vibe.sh: under command_line /
# shell_command our parent is Home Assistant itself, so its interpreter is the
# best bet; then the usual places.
case "$1" in ""|*[!a-z0-9_]*)
  echo '{"ok": false, "state": "error", "message": "run.sh: bad script name"}'; exit 0 ;;
esac
SCRIPT="$(dirname "$0")/$1.py"
shift
PY=""

usable() {
  case "$1" in ""|*-config) return 1 ;; esac
  [ -x "$1" ]
}

parent=$(readlink "/proc/$PPID/exe" 2>/dev/null)
case "$parent" in */python*) usable "$parent" && PY=$parent ;; esac

if [ -z "$PY" ]; then
  for p in python3 python; do
    found=$(command -v "$p" 2>/dev/null) && usable "$found" && PY=$found && break
  done
fi

if [ -z "$PY" ]; then
  for p in /usr/local/bin/python3 /usr/bin/python3 /usr/local/bin/python3.* /usr/bin/python3.*; do
    usable "$p" && PY=$p && break
  done
fi

if [ -z "$PY" ]; then
  echo '{"ok": false, "state": "error", "message": "No Python interpreter found"}'
  exit 0
fi

exec "$PY" -I "$SCRIPT" "$@"
