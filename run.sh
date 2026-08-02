#!/usr/bin/env bash
#
# Start the Helix: one command, one process, one URL.
#
# The service already serves the built SPA (see service/main.py), so there is
# no second dev server and no proxy to keep in step. Running the Vite dev
# server instead means three terminals and two origins, which is a development
# convenience, not how the application runs.
#
#   ./run.sh              start on http://localhost:8000
#   ./run.sh --port 9000  start on another port
#   ./run.sh --rebuild    force a fresh SPA build first
#
# First run creates data/, generates a secrets key, and prompts for an operator
# password. Subsequent runs reuse both.
set -euo pipefail

cd "$(dirname "$0")"

PORT=8000
REBUILD=0
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --rebuild) REBUILD=1; shift ;;
    -h|--help) sed -n '3,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

PYTHON=".venv/bin/python"
[ -x "$PYTHON" ] || { echo "error: $PYTHON not found. Create the venv first." >&2; exit 1; }

export HELIX_DATA_DIR="${HELIX_DATA_DIR:-data}"
mkdir -p "$HELIX_DATA_DIR"

# The key encrypts stored venue credentials. Losing it makes them unreadable,
# so it is generated once and kept, never regenerated on each run.
KEY_FILE="${HELIX_SECRETS_KEY_FILE:-.secrets.key}"
if [ ! -f "$KEY_FILE" ]; then
  "$PYTHON" -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())" > "$KEY_FILE"
  chmod 600 "$KEY_FILE"
  echo "generated $KEY_FILE (keep it: stored venue credentials cannot be read without it)"
fi
export HELIX_SECRETS_KEY="$(cat "$KEY_FILE")"

# Build the SPA when it is missing or stale. Comparing against the newest
# source file means an edit is picked up without a flag, while an unchanged
# tree skips a ~10s build.
NEWEST_SRC="$(find ui/src ui/index.html ui/package.json -type f -newer ui/dist/index.html 2>/dev/null | head -1 || true)"
if [ "$REBUILD" = "1" ] || [ ! -f ui/dist/index.html ] || [ -n "$NEWEST_SRC" ]; then
  echo "building the UI..."
  npm run build --prefix ui
fi

# Seed the first operator. An empty console with no way to log in is not a
# useful starting state.
if [ ! -s "$HELIX_DATA_DIR/users.json" ]; then
  echo
  echo "No operator account yet. Creating one — choose a password (twice)."
  PYTHONPATH=src "$PYTHON" -m helix.admin bootstrap --username operator
  echo
fi

echo "Helix → http://localhost:$PORT   (sign in as 'operator')"
exec env PYTHONPATH=src "$PYTHON" -m uvicorn \
  helix.service.main:create_service_app --factory --port "$PORT"
