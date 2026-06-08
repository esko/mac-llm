#!/usr/bin/env bash
set -euo pipefail

pr="${1:?usage: escalate-to-supervisor.sh <pr-number> <reason>}"
reason="${2:?usage: escalate-to-supervisor.sh <pr-number> <reason>}"

command -v gh >/dev/null || { echo "gh is required" >&2; exit 1; }
command -v git >/dev/null || { echo "git is required" >&2; exit 1; }

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

mkdir -p .agents/state

branch="$(gh pr view "$pr" --json headRefName --jq '.headRefName')"
url="$(gh pr view "$pr" --json url --jq '.url')"
title="$(gh pr view "$pr" --json title --jq '.title')"
summary_file=".agents/state/supervisor-escalation-pr-${pr}.md"

cat > "$summary_file" <<EOF
# Supervisor escalation

PR: #$pr
Title: $title
URL: $url
Branch: $branch

Reason:
$reason

## Worker status

The issue-worker is giving up and must stop touching this PR/worktree.

## Supervisor options

1. Inspect PR:

   \`\`\`bash
   gh pr view $pr --comments
   gh pr diff $pr
   \`\`\`

2. Decide one of:

   - give targeted instructions and return to worker
   - take over the PR branch directly
   - close the PR and create a replacement issue
   - ask human for decision

3. If taking over:

   - label PR \`agent:supervisor-taking-over\`
   - work only on this PR branch/worktree
   - fix the issue
   - rerun review loop
   - never merge automatically
EOF

gh pr edit "$pr" \
  --add-label "agent:needs-supervisor" \
  --add-label "agent:takeover-requested" || true

comment_file=".agents/state/supervisor-escalation-pr-${pr}-comment.md"
cat > "$comment_file" <<EOF
Agent escalation: supervisor needed.

Reason:
$reason

The issue-worker is stopping and should not continue editing this PR branch.

Supervisor should inspect:
$summary_file

Human merge is still required.
EOF

gh pr comment "$pr" --body-file "$comment_file" || true

cat <<EOF
Escalated PR #$pr to supervisor.

Summary:
  $summary_file

The issue-worker must stop now.
EOF
