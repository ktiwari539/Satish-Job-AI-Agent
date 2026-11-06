#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export JOB_AGENT_WORKFLOW=portals
exec bash "$REPO_DIR/scripts/certify_linkedin.sh" "$@"
