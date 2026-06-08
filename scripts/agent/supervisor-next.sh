#!/usr/bin/env bash
set -euo pipefail

worker="${1:?usage: supervisor-next.sh <claude|cursor|codex>}"

case "$worker" in
  claude|cursor|codex) ;;
  *) echo "unknown worker: $worker" >&2; exit 2 ;;
esac

command -v gh >/dev/null || { echo "gh is required" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }
command -v git >/dev/null || { echo "git is required" >&2; exit 1; }

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

gh auth status >/dev/null

poll_seconds="${AGENT_WATCH_POLL_SECONDS:-300}"
max_active="${AGENT_MAX_ACTIVE_WORKERS:-2}"
base_branch="${AGENT_BASE_BRANCH:-main}"
worktrees_dir="${MAC_LLM_WORKTREES_DIR:-$repo_root/../mac-llm-worktrees}"
lock_dir="${TMPDIR:-/tmp}/mac-llm-supervisor-${worker}.lockdir"

mkdir -p "$worktrees_dir" "$repo_root/.agents/state"

acquire_lock() {
  if mkdir "$lock_dir" 2>/dev/null; then
    trap 'rmdir "$lock_dir" 2>/dev/null || true' EXIT
    return 0
  fi
  return 1
}

while true; do
  echo
  echo "Supervisor poll: worker:$worker"

  active_count="$(
    gh pr list \
      --state open \
      --label "worker:${worker}" \
      --limit 100 \
      --json number,labels \
    | jq '[.[] | select([.labels[].name] | index("agent:ready-for-human") | not)] | length'
  )"

  echo "Active non-ready PRs for worker:$worker: $active_count / $max_active"

  echo "Active PRs:"
  gh pr list \
    --state open \
    --label "worker:${worker}" \
    --limit 20 \
    --json number,title,labels,url \
    --jq '.[] | "  #\(.number) \(.title) [\([.labels[].name] | join(", "))]"' || true

  attention="$(
    gh pr list \
      --state open \
      --label "worker:${worker}" \
      --label "agent:needs-supervisor" \
      --limit 10 \
      --json number,title,url,labels \
    | jq 'first // empty'
  )"

  if [[ -n "$attention" ]]; then
    echo
    echo "SUPERVISOR_ATTENTION_NEEDED"
    echo "$attention" | jq .
    echo "Inspect this PR before delegating more work."
    exit 30
  fi

  if (( active_count >= max_active )); then
    echo "Concurrency limit reached. Sleeping ${poll_seconds}s..."
    sleep "$poll_seconds"
    continue
  fi

  issue_json="$(
    gh issue list \
      --state open \
      --label "agent:ready" \
      --label "worker:${worker}" \
      --limit 50 \
      --json number,title,labels,url \
    | jq 'map(select([.labels[].name] | index("agent:claimed") | not)) | first // empty'
  )"

  if [[ -z "$issue_json" ]]; then
    echo "No claimable issue for worker:$worker. Sleeping ${poll_seconds}s..."
    sleep "$poll_seconds"
    continue
  fi

  if ! acquire_lock; then
    echo "Another supervisor process is claiming work for worker:$worker. Sleeping..."
    sleep 5
    continue
  fi

  # Re-query inside lock to avoid races.
  issue_json="$(
    gh issue list \
      --state open \
      --label "agent:ready" \
      --label "worker:${worker}" \
      --limit 50 \
      --json number,title,labels,url \
    | jq 'map(select([.labels[].name] | index("agent:claimed") | not)) | first // empty'
  )"

  if [[ -z "$issue_json" ]]; then
    echo "Issue was claimed by another watcher. Continuing."
    rmdir "$lock_dir" 2>/dev/null || true
    trap - EXIT
    sleep 2
    continue
  fi

  issue="$(echo "$issue_json" | jq -r '.number')"
  title="$(echo "$issue_json" | jq -r '.title')"
  url="$(echo "$issue_json" | jq -r '.url')"

  slug="$(
    echo "$title" \
      | tr '[:upper:]' '[:lower:]' \
      | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g' \
      | cut -c1-60
  )"

  branch="agent/issue-${issue}-${slug}"
  worktree="$worktrees_dir/issue-${issue}-${slug}"

  echo "Claiming issue #$issue: $title"

  gh issue edit "$issue" \
    --add-label "agent:claimed" \
    --add-label "agent:delegated" \
    --add-label "worker:${worker}"

  git fetch origin "$base_branch" >/dev/null 2>&1 || true

  if [[ ! -d "$worktree" ]]; then
    if git show-ref --verify --quiet "refs/heads/${branch}"; then
      git worktree add "$worktree" "$branch"
    else
      git worktree add -b "$branch" "$worktree" "origin/$base_branch"
    fi
  fi

  mkdir -p "$worktree/.agents/state"

  cat > "$worktree/.agents/state/current-task.md" <<EOF
# Issue-worker task

Worker: $worker
Issue: #$issue
Title: $title
URL: $url
Branch: $branch
Worktree: $worktree
Base branch: $base_branch

You are the issue-worker for this issue.

Own exactly this issue/worktree/branch/PR lifecycle.

Required:
1. Work only in this worktree.
2. Read AGENTS.md.
3. Read issue #$issue:

   \`\`\`bash
   gh issue view $issue
   \`\`\`

4. Restate acceptance criteria.
5. Use TDD where practical.
6. Implement only this issue.
7. Do not start future milestone work.
8. Run relevant tests.
9. Commit working increments.
10. Push branch:

    \`\`\`bash
    git push -u origin "$branch"
    \`\`\`

11. Open/update PR:

    \`\`\`bash
    gh pr create --fill --base "$base_branch" --head "$branch"
    \`\`\`

12. Get PR number:

    \`\`\`bash
    gh pr view --json number --jq '.number'
    \`\`\`

13. Run Codex loop:

    \`\`\`bash
    ./scripts/agent/codex-loop.sh <pr-number>
    \`\`\`

14. Fix Codex feedback and rerun until ready-for-human.
15. Never merge.

If blocked or needing a decision, label the PR \`agent:needs-supervisor\`, run \`./scripts/agent/escalate-to-supervisor.sh <pr-number> "<reason>"\`, and stop.
EOF

  cat > "$repo_root/.agents/state/last-delegated-task.md" <<EOF
ISSUE=$issue
WORKER=$worker
BRANCH=$branch
WORKTREE=$worktree
TASK_FILE=$worktree/.agents/state/current-task.md
EOF

  cat <<EOF
DELEGATE_ISSUE=$issue
WORKER=$worker
BRANCH=$branch
WORKTREE=$worktree
TASK_FILE=$worktree/.agents/state/current-task.md

Launch an issue-worker subagent for this worktree.
The supervisor must not edit this worktree.
After launching the subagent, run supervisor-next.sh again.
EOF

  exit 0
done
