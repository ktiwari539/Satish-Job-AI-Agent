#!/bin/bash
set -euo pipefail

REPO_DIR="${JOB_AGENT_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
REPO_DIR="$(cd "$REPO_DIR" && pwd)"
if [[ -n "${JOB_AGENT_PYTHON:-}" ]]; then
  PYTHON_BIN="$JOB_AGENT_PYTHON"
elif [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$REPO_DIR/.venv/bin/python"
else
  PYTHON_BIN=python3
fi

cd "$REPO_DIR"
# The worker reads the current Sheet controls and cannot submit applications.
# Its kernel lock cannot become stale after a crash and remains held over exec.
exec "$PYTHON_BIN" src/scheduled_review.py
