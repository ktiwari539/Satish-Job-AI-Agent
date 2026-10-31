#!/bin/bash
set -euo pipefail
if ! command -v launchctl >/dev/null 2>&1; then
  echo "This installer requires macOS launchctl." >&2
  exit 2
fi

REPO_DIR="${JOB_AGENT_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
REPO_DIR="$(cd "$REPO_DIR" && pwd)"
if [[ -n "${JOB_AGENT_PYTHON:-}" ]]; then
  PYTHON_BIN="$(command -v "$JOB_AGENT_PYTHON")"
elif [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$REPO_DIR/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi
PLIST="$HOME/Library/LaunchAgents/com.satish.job-agent.review.plist"
RUNNER="$REPO_DIR/scripts/run_review_window.sh"
LOG_DIR="$REPO_DIR/data"
mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"

"$PYTHON_BIN" - "$PLIST" "$RUNNER" "$REPO_DIR" "$LOG_DIR" <<'PY'
import os, plistlib, sys
from pathlib import Path
target, runner, repo, logs = sys.argv[1:]
environment = {'JOB_AGENT_REPO': repo, 'JOB_AGENT_PYTHON': sys.executable}
for key in ('JOB_AGENT_QUERY', 'JOB_AGENT_LOCATION', 'JOB_AGENT_MAX_JOBS',
            'JOB_AGENT_PORTALS', 'JOB_AGENT_SOURCES'):
    if key in os.environ:
        environment[key] = os.environ[key]
payload = dict(Label='com.satish.job-agent.review',
    ProgramArguments=['/bin/bash', runner], EnvironmentVariables=environment,
    StartCalendarInterval=[dict(Hour=10, Minute=0), dict(Hour=23, Minute=0)],
    StandardOutPath=str(Path(logs)/'review-window.stdout.log'),
    StandardErrorPath=str(Path(logs)/'review-window.stderr.log'))
temporary = Path(target).with_suffix('.tmp')
with temporary.open('wb') as output:
    plistlib.dump(payload, output)
os.replace(temporary, target)
PY

launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "Installed: $PLIST"
echo "Scheduled local-system-time starts: 10:00 and 23:00 (Mac must be awake and signed in)."
echo "Review only: public employer feeds, current Sheet controls, no automatic login or submission."
