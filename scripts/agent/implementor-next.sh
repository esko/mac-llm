#!/usr/bin/env bash
set -euo pipefail

command -v git >/dev/null || { echo "git is required" >&2; exit 1; }
repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

# Load optional repo-local env without clobbering variables explicitly set by the shell.
_env_AGENT_SUPERVISOR="${AGENT_SUPERVISOR-}"
_env_AGENT_IMPLEMENTOR="${AGENT_IMPLEMENTOR-}"
_env_AGENT_IMPLEMENTER="${AGENT_IMPLEMENTER-}"
if [[ -f .agents/agent.env ]]; then
  # shellcheck disable=SC1091
  source .agents/agent.env
fi
[[ -n "$_env_AGENT_SUPERVISOR" ]] && AGENT_SUPERVISOR="$_env_AGENT_SUPERVISOR"
[[ -n "$_env_AGENT_IMPLEMENTOR" ]] && AGENT_IMPLEMENTOR="$_env_AGENT_IMPLEMENTOR"
[[ -n "$_env_AGENT_IMPLEMENTER" ]] && AGENT_IMPLEMENTER="$_env_AGENT_IMPLEMENTER"
if [[ -z "${AGENT_IMPLEMENTOR:-}" && -n "${AGENT_IMPLEMENTER:-}" ]]; then
  AGENT_IMPLEMENTOR="$AGENT_IMPLEMENTER"
fi

worker="${1:-${AGENT_IMPLEMENTOR:-}}"
if [[ -z "$worker" ]]; then
  echo "usage: implementor-next.sh [implementor-agent]" >&2
  echo "or set AGENT_IMPLEMENTOR in the environment/.agents/agent.env" >&2
  exit 2
fi

if ! [[ "$worker" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "unknown/unsafe implementor id: $worker" >&2
  exit 2
fi

supervisor="${AGENT_SUPERVISOR:-unknown}"
implementor="$worker"

command -v gh >/dev/null || { echo "gh is required" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }
command -v git >/dev/null || { echo "git is required" >&2; exit 1; }

gh auth status >/dev/null

poll_seconds="${AGENT_WATCH_POLL_SECONDS:-300}"
max_active="${AGENT_MAX_ACTIVE_WORKERS:-2}"
base_branch="${AGENT_BASE_BRANCH:-main}"
worktrees_dir="${MAC_LLM_WORKTREES_DIR:-$repo_root/../mac-llm-worktrees}"
lock_dir="${TMPDIR:-/tmp}/mac-llm-implementor-claim.lockdir"

mkdir -p "$worktrees_dir" "$repo_root/.agents/state"

acquire_lock() {
  if mkdir "$lock_dir" 2>/dev/null; then
    trap 'rmdir "$lock_dir" 2>/dev/null || true' EXIT
    return 0
  fi
  return 1
}

find_claimable_issue() {
  local worker_label="$1"
  gh issue list \
    --state open \
    --label "agent:ready" \
    --label "$worker_label" \
    --limit 50 \
    --json number,title,labels,url \
  | jq 'map(select([.labels[].name] | index("agent:claimed") | not)) | first // empty'
}

while true; do
  echo
  echo "Implementor poll: implementor:$worker supervisor:${supervisor:-unknown}"

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

  issue_attention="$(
    gh issue list \
      --state open \
      --label "worker:${worker}" \
      --label "agent:needs-supervisor" \
      --limit 10 \
      --json number,title,url,labels \
    | jq 'first // empty'
  )"

  if [[ -n "$issue_attention" ]]; then
    echo
    echo "SUPERVISOR_ISSUE_ATTENTION_NEEDED"
    echo "$issue_attention" | jq .
    echo "Surface this issue to the supervisor before delegating more work. It may be worker-incomplete."
    exit 31
  fi

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
    echo "Surface this PR to the supervisor before delegating more work."
    exit 30
  fi

  if (( active_count >= max_active )); then
    echo "Concurrency limit reached. Sleeping ${poll_seconds}s..."
    sleep "$poll_seconds"
    continue
  fi

  issue_source_label="worker:${worker}"
  issue_json="$(find_claimable_issue "worker:${worker}")"

  if [[ -z "$issue_json" && "${AGENT_ALLOW_WORKER_ANY:-1}" != "0" ]]; then
    issue_source_label="worker:any"
    issue_json="$(find_claimable_issue "worker:any")"
  fi

  if [[ -z "$issue_json" ]]; then
    echo "No claimable issue for worker:$worker. Checked worker:$worker and worker:any. Sleeping ${poll_seconds}s..."
    sleep "$poll_seconds"
    continue
  fi

  if ! acquire_lock; then
    echo "Another implementor process is claiming work for worker:$worker. Sleeping..."
    sleep 5
    continue
  fi

  # Re-query inside the global claim lock to avoid races, especially for worker:any.
  issue_source_label="worker:${worker}"
  issue_json="$(find_claimable_issue "worker:${worker}")"

  if [[ -z "$issue_json" && "${AGENT_ALLOW_WORKER_ANY:-1}" != "0" ]]; then
    issue_source_label="worker:any"
    issue_json="$(find_claimable_issue "worker:any")"
  fi

  if [[ -z "$issue_json" ]]; then
    echo "Issue was claimed by another implementor. Continuing."
    rmdir "$lock_dir" 2>/dev/null || true
    trap - EXIT
    sleep 2
    continue
  fi

  issue="$(echo "$issue_json" | jq -r '.number')"
  title="$(echo "$issue_json" | jq -r '.title')"
  url="$(echo "$issue_json" | jq -r '.url')"

  echo "Selected source label: $issue_source_label"

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

  if [[ "$issue_source_label" == "worker:any" ]]; then
    gh issue edit "$issue" --remove-label "worker:any" || true
  fi

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
Source worker label: $issue_source_label
Issue: #$issue
Title: $title
URL: $url
Branch: $branch
Worktree: $worktree
Base branch: $base_branch
Supervisor: $supervisor
Implementor: $worker

You are the issue-worker subagent for this issue.

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
10. Run the mandatory finish gate:

    \`\`\`bash
    ./scripts/agent/finish-pr.sh $issue
    \`\`\`

11. If `finish-pr.sh` exits with blocking or ambiguous reviewer feedback:
    - read the generated files under `.agents/state/`
    - fix only reviewer findings and directly related test gaps
    - commit the fix
    - rerun `./scripts/agent/finish-pr.sh $issue`

12. Repeat until `finish-pr.sh` exits cleanly and the PR is marked `agent:ready-for-human`, or escalate.
13. Your final response to the implementor must include:
    - issue number
    - PR number
    - `finish-pr.sh` exit result
    - whether the PR is `agent:ready-for-human` or escalated
14. If no PR exists, do not report done. Run `finish-pr.sh` first.
15. Never merge.

If blocked or needing a decision, label the PR \`agent:needs-supervisor\`, run \`./scripts/agent/escalate-to-supervisor.sh <pr-number> "<reason>"\`, and stop.
EOF

  cat > "$repo_root/.agents/state/last-delegated-task.md" <<EOF
ISSUE=$issue
WORKER=$worker
SOURCE_WORKER_LABEL=$issue_source_label
BRANCH=$branch
WORKTREE=$worktree
TASK_FILE=$worktree/.agents/state/current-task.md
EOF

  cat <<EOF
DELEGATE_ISSUE=$issue
WORKER=$worker
SOURCE_WORKER_LABEL=$issue_source_label
SOURCE_WORKER_LABEL=$issue_source_label
BRANCH=$branch
WORKTREE=$worktree
TASK_FILE=$worktree/.agents/state/current-task.md

Launch an issue-worker subagent for this worktree.
The implementor must not edit this worktree while the issue-worker is active.
When the issue-worker reports done, run:

  ./scripts/agent/verify-worker-result.sh $issue

If verification fails, relaunch or steer the same issue-worker/worktree instead of accepting completion.
If verification requests supervisor attention, stop and surface it to the supervisor.
After launching the subagent, run implementor-next.sh again if concurrency allows.
EOF

  exit 0
done
