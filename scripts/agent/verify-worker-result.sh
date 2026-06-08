#!/usr/bin/env bash
set -euo pipefail

issue="${1:-}"
if [[ -z "$issue" ]]; then
  echo "usage: verify-worker-result.sh <issue-number>" >&2
  exit 2
fi

command -v gh >/dev/null || { echo "gh is required" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }
command -v git >/dev/null || { echo "git is required" >&2; exit 1; }

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

mkdir -p .agents/state

base_branch="${AGENT_BASE_BRANCH:-main}"
worktrees_dir="${MAC_LLM_WORKTREES_DIR:-$repo_root/../mac-llm-worktrees}"

title="$(gh issue view "$issue" --json title --jq '.title')"
url="$(gh issue view "$issue" --json url --jq '.url')"
labels="$(gh issue view "$issue" --json labels --jq '.labels[].name')"

worker="unknown"
if printf '%s\n' "$labels" | grep -q '^worker:claude$'; then
  worker="claude"
elif printf '%s\n' "$labels" | grep -q '^worker:cursor$'; then
  worker="cursor"
elif printf '%s\n' "$labels" | grep -q '^worker:codex$'; then
  worker="codex"
fi

slug="$(
  echo "$title" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g' \
    | cut -c1-60
)"

branch="agent/issue-${issue}-${slug}"
worktree="$worktrees_dir/issue-${issue}-${slug}"
state_file=".agents/state/verify-worker-issue-${issue}.md"

pr_json="$(
  gh pr list \
    --state open \
    --head "$branch" \
    --json number,title,url,labels,headRefName,reviewDecision,statusCheckRollup \
  | jq 'first // empty'
)"

if [[ -z "$pr_json" ]]; then
  gh issue edit "$issue" \
    --add-label "agent:worker-incomplete" \
    --add-label "agent:needs-supervisor" || true

  cat > "$state_file" <<EOF_STATE
# Worker result verification failed: no PR

Issue: #$issue
Title: $title
URL: $url
Worker: $worker
Expected branch: $branch
Expected worktree: $worktree

Result:
No open PR exists for the expected issue branch.

Likely cause:
The issue-worker reported completion before running the mandatory finish gate:

\`\`\`bash
./scripts/agent/finish-pr.sh $issue
\`\`\`

Supervisor next step:
1. Reopen or relaunch the issue-worker for this same worktree.
2. Instruct it not to do new implementation unless needed.
3. It must commit any remaining work and run the finish gate.
4. If it cannot, supervisor should take over or ask the human.

The issue is labeled \`agent:worker-incomplete\` and \`agent:needs-supervisor\`.
EOF_STATE

  cat "$state_file"
  exit 22
fi

pr="$(echo "$pr_json" | jq -r '.number')"
pr_url="$(echo "$pr_json" | jq -r '.url')"
pr_labels="$(echo "$pr_json" | jq -r '.labels[].name')"
review_decision="$(echo "$pr_json" | jq -r '.reviewDecision // "UNKNOWN"')"

has_label() {
  printf '%s\n' "$pr_labels" | grep -q "^$1$"
}

failed_checks="$(
  echo "$pr_json" \
    | jq '[.statusCheckRollup[]? | select((.conclusion // "") as $c | ($c == "FAILURE" or $c == "CANCELLED" or $c == "TIMED_OUT"))] | length'
)"

pending_checks="$(
  echo "$pr_json" \
    | jq '[.statusCheckRollup[]? | select((.status // "") != "COMPLETED")] | length'
)"

if has_label "agent:ready-for-human"; then
  cat > "$state_file" <<EOF_STATE
# Worker result verified: ready for human

Issue: #$issue
PR: #$pr
URL: $pr_url
Worker: $worker
Review decision: $review_decision
Failed checks: $failed_checks
Pending checks: $pending_checks

Result:
The PR is labeled \`agent:ready-for-human\`.

Supervisor may continue watching for more work. Human merge is still required.
EOF_STATE
  cat "$state_file"
  exit 0
fi

if has_label "agent:needs-supervisor" || has_label "agent:takeover-requested" || has_label "agent:review-loop-limit"; then
  cat > "$state_file" <<EOF_STATE
# Worker result needs supervisor

Issue: #$issue
PR: #$pr
URL: $pr_url
Worker: $worker
Review decision: $review_decision
Failed checks: $failed_checks
Pending checks: $pending_checks

Result:
The PR is explicitly labeled for supervisor attention.

Supervisor next step:
Inspect PR comments, generated state files, and decide whether to advise, relaunch worker, take over, replan, or ask the human.
EOF_STATE
  cat "$state_file"
  exit 30
fi

# PR exists, but the worker stopped before review loop produced a final state.
gh pr edit "$pr" \
  --add-label "agent:worker-incomplete" \
  --add-label "agent:needs-supervisor" || true

gh issue edit "$issue" \
  --add-label "agent:worker-incomplete" \
  --add-label "agent:needs-supervisor" || true

cat > "$state_file" <<EOF_STATE
# Worker result verification failed: PR not completed

Issue: #$issue
PR: #$pr
URL: $pr_url
Worker: $worker
Review decision: $review_decision
Failed checks: $failed_checks
Pending checks: $pending_checks
Expected worktree: $worktree

Result:
A PR exists, but it is not labeled \`agent:ready-for-human\` and it is not an intentional supervisor escalation.

Likely cause:
The issue-worker opened a PR but did not complete the mandatory finish/review loop.

Supervisor next step:
1. Relaunch the issue-worker in the same worktree, or take over.
2. Required command from the worktree:

\`\`\`bash
./scripts/agent/finish-pr.sh $issue
\`\`\`

3. The worker must fix reviewer feedback and rerun until ready-for-human or escalation.

The PR and issue are labeled \`agent:worker-incomplete\` and \`agent:needs-supervisor\`.
EOF_STATE

cat "$state_file"
exit 23
