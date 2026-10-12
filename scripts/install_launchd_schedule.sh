#!/bin/bash
set -euo pipefail

REPO_DIR="${JOB_AGENT_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
PYTHON_BIN="${JOB_AGENT_PYTHON:-python3}"
PLIST="$HOME/Library/LaunchAgents/com.satish.job-agent.review.plist"
RUNNER="$REPO_DIR/scripts/run_review_window.sh"
LOG_DIR="$REPO_DIR/data"
mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.satish.job-agent.review</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$RUNNER</string>
  </array>

  <key>EnvironmentVariables</key>
  <dict>
    <key>JOB_AGENT_REPO</key>
    <string>$REPO_DIR</string>
    <key>JOB_AGENT_PYTHON</key>
    <string>$PYTHON_BIN</string>
  </dict>

  <key>StartCalendarInterval</key>
  <array>
    <dict>
      <key>Hour</key><integer>10</integer>
      <key>Minute</key><integer>0</integer>
    </dict>
    <dict>
      <key>Hour</key><integer>23</integer>
      <key>Minute</key><integer>0</integer>
    </dict>
  </array>

  <key>StandardOutPath</key>
  <string>$LOG_DIR/review-window.stdout.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/review-window.stderr.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "Installed: $PLIST"
echo "Scheduled local starts: 10:00 and 23:00"
