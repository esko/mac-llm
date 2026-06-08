#!/usr/bin/env bash
set -euo pipefail

pr="${1:?usage: mark-ready-for-human.sh <pr-number>}"

command -v gh >/dev/null || { echo "gh is required" >&2; exit 1; }

gh pr edit "$pr" \
  --remove-label "agent:codex-loop" \
  --remove-label "agent:needs-fix" \
  --remove-label "agent:codex-blocked" \
  --remove-label "agent:review-loop-limit" \
  --remove-label "agent:takeover-requested" \
  --add-label "agent:ready-for-human" || true

gh pr comment "$pr" --body "Agent status: PR is ready for human review. Human merge is still required; agents must not merge." || true

echo "Marked PR #$pr as ready for human review. Do not merge automatically."
