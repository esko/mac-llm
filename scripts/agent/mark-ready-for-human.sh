#!/usr/bin/env bash
set -euo pipefail

pr="${1:?usage: mark-ready-for-human.sh <pr-number>}"

command -v gh >/dev/null || { echo "gh is required" >&2; exit 1; }

gh pr edit "$pr" \
  --remove-label "agent:review-loop" \
  --remove-label "agent:codex-loop" \
  --remove-label "agent:needs-fix" \
  --remove-label "agent:codex-blocked" \
  --remove-label "review:requested" \
  --remove-label "agent:review-loop-limit" \
  --remove-label "agent:takeover-requested" \
  --add-label "agent:ready-for-human" || true

comment_file=".agents/state/ready-for-human-pr-${pr}-comment.md"
mkdir -p .agents/state
cat > "$comment_file" <<EOF
Agent status: PR is ready for human review.

Human merge is still required; agents must not merge.
EOF

gh pr comment "$pr" --body-file "$comment_file" || true

echo "Marked PR #$pr as ready for human review. Do not merge automatically."
