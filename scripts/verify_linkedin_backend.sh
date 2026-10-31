#!/usr/bin/env bash
# Manual acceptance of the new durable backend; never signs in or submits.
set -euo pipefail
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
if [[ -n "${JOB_AGENT_PYTHON:-}" ]]; then
  task_python="$JOB_AGENT_PYTHON"
elif [[ -x .venv/bin/python ]]; then
  task_python=.venv/bin/python
else
  task_python=python3
fi
exec "$task_python" src/agent_backend.py verify-linkedin "$@"
