#!/bin/bash
set -euo pipefail

REPO_DIR="${JOB_AGENT_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
PYTHON_BIN="${JOB_AGENT_PYTHON:-python3}"
RESUME_PATH="${JOB_AGENT_RESUME_PATH:-}"
QUERY="${JOB_AGENT_QUERY:-Customer Success Manager}"
LOCATION="${JOB_AGENT_LOCATION:-India}"
MAX_JOBS="${JOB_AGENT_MAX_JOBS:-80}"

if [[ -z "$RESUME_PATH" ]]; then
  echo "JOB_AGENT_RESUME_PATH is required." >&2
  exit 2
fi

cd "$REPO_DIR"
mkdir -p data

LOCK_DIR="data/application-window.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "Another application-window run is already active; exiting."
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

"$PYTHON_BIN" src/job_agent_cli.py   --profile config/qa_profile.json   --private-profile data/private_profile.json   --policy config/automation_policy.production.json   --credentials-file data/portal_credentials.json   --profile-dir browser-profile   --db data/jobs.db   --report data/application_report.json   --resume-path "$RESUME_PATH"   --query "$QUERY"   --location "$LOCATION"   --max-jobs "$MAX_JOBS"
