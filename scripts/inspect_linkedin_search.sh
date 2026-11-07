#!/usr/bin/env bash
# Search diagnostics only: existing browser profile, no resume, forms or login.
set -euo pipefail
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
if [[ -n "${JOB_AGENT_PYTHON:-}" ]]; then
  task_python="$JOB_AGENT_PYTHON"
elif [[ -x .venv/bin/python ]]; then
  task_python=.venv/bin/python
else
  task_python=python3
fi
exec "$task_python" src/linkedin_discovery.py "$@"
