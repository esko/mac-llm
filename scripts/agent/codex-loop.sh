#!/usr/bin/env bash
set -euo pipefail

# Compatibility wrapper. Prefer scripts/agent/review-loop.sh.
export AGENT_REVIEWER="${AGENT_REVIEWER:-codex}"
exec "$(dirname "$0")/review-loop.sh" "$@"
