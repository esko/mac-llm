#!/usr/bin/env bash
set -euo pipefail

issue="${1:-}"
if [[ -z "$issue" ]]; then
  echo "usage: finish-pr.sh <issue-number>" >&2
  exit 2
fi

command -v gh >/dev/null || { echo "gh is required" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }
command -v git >/dev/null || { echo "git is required" >&2; exit 1; }

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

gh auth status >/dev/null

base_branch="${AGENT_BASE_BRANCH:-main}"
branch="$(git branch --show-current)"
if [[ -z "$branch" ]]; then
  echo "Could not determine current branch. Run from the issue worktree." >&2
  exit 2
fi

if [[ "$branch" == "$base_branch" ]]; then
  echo "Refusing to finish PR from base branch '$base_branch'. Run from the issue branch worktree." >&2
  exit 2
fi

if [[ -n "$(git status --porcelain)" ]]; then
  cat <<'MSG' >&2
Working tree has uncommitted changes.

Commit working increments before finishing the PR. This script intentionally does not auto-commit agent work.
MSG
  git status --short >&2
  exit 10
fi

mkdir -p .agents/state

issue_title="$(gh issue view "$issue" --json title --jq '.title')"
issue_url="$(gh issue view "$issue" --json url --jq '.url')"
worker="unknown"
labels="$(gh issue view "$issue" --json labels --jq '.labels[].name')"
if printf '%s\n' "$labels" | grep -q '^worker:claude$'; then
  worker="claude"
elif printf '%s\n' "$labels" | grep -q '^worker:cursor$'; then
  worker="cursor"
elif printf '%s\n' "$labels" | grep -q '^worker:codex$'; then
  worker="codex"
fi

pr_body_file=".agents/state/pr-body-issue-${issue}.md"
if [[ ! -f "$pr_body_file" ]]; then
  cat > "$pr_body_file" <<EOF_BODY
Closes #$issue

## What changed

- Implemented the scoped changes for issue #$issue: $issue_title

## How to test

- See commits and agent notes in this PR.

## Benchmark/artifact path

N/A unless noted in commits or comments.

## Known limitations

- None noted by the issue-worker before review.

## Next smallest step

- Human review after reviewer loop completes.

## Agent checklist

- [x] Scope is limited to the linked issue
- [x] TDD used where practical
- [x] Relevant tests/commands run where available
- [ ] Review loop completed
- [x] No automatic merge
EOF_BODY
fi

cat <<EOF_STATUS
Finishing issue #$issue on branch $branch
Issue: $issue_url
Worker: $worker

This script will:
1. push the branch
2. create or find the PR
3. label it
4. run the blocking reviewer loop
EOF_STATUS

git push -u origin "$branch"

pr=""
if pr="$(gh pr view --json number --jq '.number' 2>/dev/null)"; then
  echo "Found existing PR #$pr for current branch."
else
  echo "Creating PR for branch $branch..."
  gh pr create \
    --title "$issue_title" \
    --body-file "$pr_body_file" \
    --base "$base_branch" \
    --head "$branch"
  pr="$(gh pr view --json number --jq '.number')"
fi

# Keep labels best-effort; not all repositories allow every edit with the available token.
gh pr edit "$pr" \
  --add-label "worker:${worker}" \
  --add-label "agent:review-loop" || true

gh issue edit "$issue" \
  --add-label "agent:implementing" || true

cat > ".agents/state/finish-pr-${pr}.md" <<EOF_STATE
# Finish PR state

Issue: #$issue
PR: #$pr
Branch: $branch
Worker: $worker

The issue-worker must not consider this task complete until:

- \`./scripts/agent/review-loop.sh $pr\` exits 0, or
- the worker escalates to supervisor.
EOF_STATE

set +e
./scripts/agent/review-loop.sh "$pr"
review_status="$?"
set -e

case "$review_status" in
  0)
    cat <<EOF_DONE
finish-pr: review loop completed cleanly for PR #$pr.
The PR should now be marked agent:ready-for-human.
Stop. Do not merge.
EOF_DONE
    exit 0
    ;;
  20)
    cat <<EOF_BLOCK
finish-pr: reviewer returned blocking feedback for PR #$pr.

Required next step for issue-worker:
1. Read the newest summary under .agents/state/review-pr-${pr}/.
2. Fix only blocking reviewer findings and directly related test gaps.
3. Commit and push.
4. Rerun:

   ./scripts/agent/finish-pr.sh $issue

Do not merge.
EOF_BLOCK
    exit 20
    ;;
  21)
    cat <<EOF_AMBIG
finish-pr: reviewer feedback was ambiguous for PR #$pr.

Required next step for issue-worker:
1. Inspect .agents/state/review-pr-${pr}/.
2. Fix if there are actionable findings; otherwise escalate or mark ready only if clearly safe.
3. Prefer rerunning:

   ./scripts/agent/finish-pr.sh $issue

Do not merge.
EOF_AMBIG
    exit 21
    ;;
  40)
    cat <<EOF_ESC
finish-pr: review loop escalated PR #$pr to supervisor.
The issue-worker must stop touching this branch.
EOF_ESC
    exit 40
    ;;
  *)
    echo "finish-pr: review-loop.sh exited with unexpected status $review_status" >&2
    exit "$review_status"
    ;;
esac
