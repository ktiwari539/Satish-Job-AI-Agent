#!/usr/bin/env bash
# Reuse the existing project Python and saved profile; setup never clears data.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
SETUP=false
if [[ "${1:-}" == "--setup" ]]; then
  SETUP=true
  shift
fi
if [[ -n "${JOB_AGENT_PYTHON:-}" ]]; then
  PYTHON_BIN="$JOB_AGENT_PYTHON"
elif [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$REPO_DIR/.venv/bin/python"
elif [[ "$SETUP" == true ]]; then
  python3 -m venv "$REPO_DIR/.venv"
  PYTHON_BIN="$REPO_DIR/.venv/bin/python"
else
  PYTHON_BIN=python3
fi
if [[ "$SETUP" == true ]]; then
  # Preserve an already working Playwright version rather than upgrading or
  # downgrading the runtime associated with the user's saved browser profile.
  if ! "$PYTHON_BIN" -c 'from playwright.sync_api import sync_playwright' >/dev/null 2>&1; then
    "$PYTHON_BIN" -m pip install -r tests/browser/requirements.txt
  fi
  "$PYTHON_BIN" -m playwright install chromium
fi
exec "$PYTHON_BIN" src/certify_linkedin.py "$@"
