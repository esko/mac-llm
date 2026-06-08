#!/usr/bin/env bash
set -euo pipefail

pr="${1:-}"
if [[ -z "$pr" ]]; then
  echo "usage: codex-loop.sh <pr-number>" >&2
  exit 2
fi

command -v gh >/dev/null || { echo "gh is required" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }
command -v git >/dev/null || { echo "git is required" >&2; exit 1; }

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

gh auth status >/dev/null

owner_repo="$(gh repo view --json nameWithOwner --jq '.nameWithOwner')"
owner="${owner_repo%%/*}"
repo="${owner_repo#*/}"

poll_seconds="${CODEX_POLL_SECONDS:-45}"
codex_author_regex="${CODEX_AUTHOR_REGEX:-codex|openai}"
max_codex_loops="${AGENT_MAX_CODEX_LOOPS:-3}"
max_ambiguous="${AGENT_MAX_AMBIGUOUS_REVIEWS:-1}"
request_id="codex-loop-$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM"
request_time="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

state_dir=".agents/state/codex-pr-${pr}"
mkdir -p "$state_dir"

attempts_file="$state_dir/attempts.jsonl"
request_file="$state_dir/request-${request_id}.json"
feedback_file="$state_dir/feedback-${request_id}.md"
raw_file="$state_dir/raw-${request_id}.json"
summary_file="$state_dir/summary-${request_id}.md"

blocking_count="0"
ambiguous_count="0"
if [[ -f "$attempts_file" ]]; then
  blocking_count="$(jq -s '[.[] | select(.result == "blocking")] | length' "$attempts_file")"
  ambiguous_count="$(jq -s '[.[] | select(.result == "ambiguous")] | length' "$attempts_file")"
fi

next_blocking_attempt="$((blocking_count + 1))"
if (( next_blocking_attempt > max_codex_loops )); then
  gh pr edit "$pr" --add-label "agent:review-loop-limit" || true
  ./scripts/agent/escalate-to-supervisor.sh "$pr" "Codex review loop exceeded ${max_codex_loops} blocking attempts."
  exit 40
fi

printf 'Requesting Codex review for PR #%s\n' "$pr"
printf 'Request id: %s\n' "$request_id"

# Mark state before requesting review.
gh pr edit "$pr" \
  --remove-label "agent:ready-for-human" \
  --add-label "agent:codex-loop" \
  --add-label "codex:requested" || true

request_body="$(cat <<EOF
@codex review

Request id: \`$request_id\`

Please review this PR against:
- AGENTS.md
- the linked GitHub issue acceptance criteria
- the current milestone scope
- the mac-llm implementation plan

Focus on:
- P0/P1 correctness issues
- missing or weak tests
- unsafe shell/file behavior
- milestone leakage
- unnecessary refactors
- benchmark/artifact correctness where relevant
- failure clarity

Do not nitpick style unless it affects correctness, maintainability, or future milestone safety.
EOF
)"

gh pr comment "$pr" --body "$request_body"

cat > "$request_file" <<EOF
{
  "pr": $pr,
  "request_id": "$request_id",
  "request_time": "$request_time",
  "poll_seconds": $poll_seconds,
  "max_codex_loops": $max_codex_loops,
  "max_ambiguous_reviews": $max_ambiguous
}
EOF

cat <<EOF
Waiting for a new Codex response after:
  $request_time

This script has no timeout by default.
Polling every ${poll_seconds}s.

State dir:
  $state_dir
EOF

while true; do
  issue_comments="$(
    gh api "repos/$owner/$repo/issues/$pr/comments" --paginate \
      --jq '.[] | {kind: "issue_comment", id, author: .user.login, created_at, body, html_url}' \
    | jq -s '.'
  )"

  reviews="$(
    gh api "repos/$owner/$repo/pulls/$pr/reviews" --paginate \
      --jq '.[] | {kind: "pull_request_review", id, author: .user.login, created_at: .submitted_at, state, body, html_url}' \
    | jq -s '.'
  )"

  review_comments="$(
    gh api "repos/$owner/$repo/pulls/$pr/comments" --paginate \
      --jq '.[] | {kind: "pull_request_review_comment", id, author: .user.login, created_at, path, line, body, html_url}' \
    | jq -s '.'
  )"

  all="$(
    jq -n \
      --arg request_time "$request_time" \
      --arg re "$codex_author_regex" \
      --arg request_id "$request_id" \
      --argjson issue_comments "$issue_comments" \
      --argjson reviews "$reviews" \
      --argjson review_comments "$review_comments" '
        ($issue_comments + $reviews + $review_comments)
        | map(select(.created_at != null))
        | map(select(.created_at > $request_time))
        | map(select((.author // "") | test($re; "i")))
        | map(select((.body // "") | contains($request_id) | not))
        | sort_by(.created_at)
      '
  )"

  count="$(echo "$all" | jq 'length')"

  if [[ "$count" -eq 0 ]]; then
    echo "No new Codex response yet for request $request_id. Sleeping ${poll_seconds}s..."
    sleep "$poll_seconds"
    continue
  fi

  echo "$all" > "$raw_file"

  {
    echo "# Codex feedback for PR #$pr"
    echo
    echo "Request id: \`$request_id\`"
    echo "Request time: \`$request_time\`"
    echo
    echo "Detected Codex items: $count"
    echo
    echo "$all" | jq -r '
      .[] |
      "## " + .kind + " by " + .author + " at " + .created_at + "\n" +
      (if .state then "- State: `" + .state + "`\n" else "" end) +
      (if .path then "- File: `" + .path + "`" + (if .line then ":" + (.line|tostring) else "" end) + "\n" else "" end) +
      (if .html_url then "- URL: " + .html_url + "\n" else "" end) +
      "\n" +
      (.body // "_No body_") +
      "\n"
    '
  } > "$feedback_file"

  body_lc="$(echo "$all" | jq -r '[.[].body // "", .[].state // ""] | join("\n")' | tr '[:upper:]' '[:lower:]')"

  blocking=false
  ambiguous=false

  if printf '%s' "$body_lc" | grep -Eq 'changes_requested|p0|p1|blocking|must fix|do not merge|regression|security|failing test|missing test|not safe|incorrect'; then
    blocking=true
  fi

  if [[ "$blocking" != "true" ]]; then
    if printf '%s' "$body_lc" | grep -Eq 'no blocking|no p0|no p1|looks good|approved|no issues found|no findings'; then
      ambiguous=false
    else
      ambiguous=true
    fi
  fi

  if [[ "$blocking" == "true" ]]; then
    echo "{\"timestamp\":\"$(date -u +%FT%TZ)\",\"request_id\":\"$request_id\",\"result\":\"blocking\"}" >> "$attempts_file"

    gh pr edit "$pr" \
      --remove-label "agent:ready-for-human" \
      --add-label "agent:codex-loop" \
      --add-label "agent:needs-fix" || true

    new_blocking_count="$(jq -s '[.[] | select(.result == "blocking")] | length' "$attempts_file")"
    if (( new_blocking_count >= max_codex_loops )); then
      gh pr edit "$pr" --add-label "agent:review-loop-limit" || true
      ./scripts/agent/escalate-to-supervisor.sh "$pr" "Codex returned blocking feedback ${new_blocking_count} times."
      exit 40
    fi

    cat > "$summary_file" <<EOF
# Codex review result: blocking

PR: #$pr
Request id: $request_id

Feedback file:
$feedback_file

Required next step:
1. Read the feedback file.
2. Fix only blocking Codex findings and directly related test gaps.
3. Do not expand scope.
4. Push to the same PR.
5. Run this script again:

\`\`\`bash
./scripts/agent/codex-loop.sh $pr
\`\`\`

Do not merge.
EOF

    cat "$summary_file"
    exit 20
  fi

  if [[ "$ambiguous" == "true" ]]; then
    echo "{\"timestamp\":\"$(date -u +%FT%TZ)\",\"request_id\":\"$request_id\",\"result\":\"ambiguous\"}" >> "$attempts_file"

    new_ambiguous_count="$(jq -s '[.[] | select(.result == "ambiguous")] | length' "$attempts_file")"

    gh pr edit "$pr" --add-label "agent:needs-fix" || true

    if (( new_ambiguous_count > max_ambiguous )); then
      ./scripts/agent/escalate-to-supervisor.sh "$pr" "Codex feedback was ambiguous more than ${max_ambiguous} time(s)."
      exit 40
    fi

    cat > "$summary_file" <<EOF
# Codex review result: ambiguous

PR: #$pr
Request id: $request_id

Feedback file:
$feedback_file

Codex responded, but the script could not confidently classify the result as clean or blocking.

Required next step:
1. Read the feedback file.
2. If there are actionable/blocking findings, fix them, push, and rerun:

\`\`\`bash
./scripts/agent/codex-loop.sh $pr
\`\`\`

3. If there are no blocking findings and checks are green, mark ready for human:

\`\`\`bash
./scripts/agent/mark-ready-for-human.sh $pr
\`\`\`

4. Do not merge.
EOF

    cat "$summary_file"
    exit 21
  fi

  echo "{\"timestamp\":\"$(date -u +%FT%TZ)\",\"request_id\":\"$request_id\",\"result\":\"clean\"}" >> "$attempts_file"

  ./scripts/agent/mark-ready-for-human.sh "$pr"

  cat > "$summary_file" <<EOF
# Codex review result: clean

PR: #$pr
Request id: $request_id

Feedback file:
$feedback_file

Status:
- Codex response appeared non-blocking.
- PR marked \`agent:ready-for-human\`.
- Human merge still required.

Do not merge.
EOF

  cat "$summary_file"
  exit 0
done
