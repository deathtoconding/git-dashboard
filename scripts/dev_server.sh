#!/usr/bin/env bash
#
# Bootstrap a local instance and start the dashboard.
#
# Idempotent: safe to run on a fresh clone as well as on a machine that is
# already set up. It only touches git-ignored runtime files (venv, config.json,
# data/) and never modifies tracked files.
#
#   scripts/dev_server.sh                       # 0.0.0.0:8000 with the demo dataset
#   scripts/dev_server.sh --host 127.0.0.1 --port 9000
#   scripts/dev_server.sh --root ~/projects --repos 8 --skip-demo
#   GITDASH_VENV=/path/to/venv scripts/dev_server.sh
#
# Environment:
#   GITDASH_VENV   virtualenv location (default: <repo>/.venv)
#   PYTHON         interpreter used to create the venv (default: python3)
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
VENV="${GITDASH_VENV:-$ROOT/.venv}"
HOST="0.0.0.0"
PORT="8000"
ROOT_DIR="data/demo"
REPOS="8"
SEED="1337"
SKIP_DEMO=0
SKIP_SCAN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --root) ROOT_DIR="$2"; shift 2 ;;
    --repos) REPOS="$2"; shift 2 ;;
    --seed) SEED="$2"; shift 2 ;;
    --skip-demo) SKIP_DEMO=1; shift ;;
    --skip-scan) SKIP_SCAN=1; shift ;;
    -h|--help) sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }

# --- 1. virtual environment -------------------------------------------------
if [[ ! -x "$VENV/bin/python" ]]; then
  say "creating virtual environment in $VENV"
  "$PYTHON" -m venv "$VENV"
fi
PY="$VENV/bin/python"

if ! "$PY" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  say "installing dependencies"
  "$VENV/bin/pip" install --quiet --upgrade pip
  # requirements-dev.txt pulls in requirements.txt and adds pytest/httpx/ruff.
  "$VENV/bin/pip" install --quiet -r requirements-dev.txt
fi
say "python $("$PY" -c 'import platform; print(platform.python_version())') at $PY"

# --- 2. configuration -------------------------------------------------------
if [[ ! -f config.json ]]; then
  say "writing config.json (root: $ROOT_DIR)"
  "$PY" - "$ROOT_DIR" "$HOST" "$PORT" <<'PY'
import json, sys, pathlib
root, host, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
pathlib.Path("config.json").write_text(json.dumps({
    "database_path": "data/dashboard.db",
    "repository_roots": [root],
    "refresh_interval_minutes": 0,
    "host": host,
    "port": port,
    "log_level": "INFO",
}, indent=2) + "\n")
PY
else
  say "keeping the existing config.json"
fi

# --- 3. data ----------------------------------------------------------------
if [[ "$SKIP_DEMO" -eq 0 && "$ROOT_DIR" == "data/demo" ]]; then
  if [[ -z "$(ls -A data/demo 2>/dev/null)" ]]; then
    say "generating the demo dataset ($REPOS repositories, seed $SEED)"
    "$PY" scripts/create_demo_repos.py --target data/demo --repos "$REPOS" --seed "$SEED" >/dev/null
  fi
fi

say "discovering and scanning repositories"
"$PY" -m app --config config.json discover --register 2>&1 | tail -1
if [[ "$SKIP_SCAN" -eq 0 ]]; then
  "$PY" -m app --config config.json scan --all 2>&1 | tail -1
fi

# --- 4. serve ---------------------------------------------------------------
say "starting the dashboard on http://$HOST:$PORT"
exec "$PY" -m app --config config.json start --host "$HOST" --port "$PORT"
