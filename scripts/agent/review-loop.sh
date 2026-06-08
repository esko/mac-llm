#!/usr/bin/env bash
set -euo pipefail

pr="${1:-}"
if [[ -z "$pr" ]]; then
  echo "usage: review-loop.sh <pr-number>" >&2
  exit 2
fi

command -v gh >/dev/null || { echo "gh is required" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }
command -v git >/dev/null || { echo "git is required" >&2; exit 1; }

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

# Load optional repo-local env without clobbering variables explicitly set by the shell.
_env_AGENT_REVIEWER="${AGENT_REVIEWER-}"
_env_REVIEWER_AUTHOR_REGEX="${REVIEWER_AUTHOR_REGEX-}"
_env_REVIEWER_REQUEST_TEMPLATE="${REVIEWER_REQUEST_TEMPLATE-}"
_env_REVIEWER_LABEL="${REVIEWER_LABEL-}"
_env_REVIEWER_TRIGGER_LABEL="${REVIEWER_TRIGGER_LABEL-}"
_env_REVIEWER_DISPLAY_NAME="${REVIEWER_DISPLAY_NAME-}"
if [[ -f .agents/agent.env ]]; then
  # shellcheck disable=SC1091
  source .agents/agent.env
fi
[[ -n "$_env_AGENT_REVIEWER" ]] && AGENT_REVIEWER="$_env_AGENT_REVIEWER"
[[ -n "$_env_REVIEWER_AUTHOR_REGEX" ]] && REVIEWER_AUTHOR_REGEX="$_env_REVIEWER_AUTHOR_REGEX"
[[ -n "$_env_REVIEWER_REQUEST_TEMPLATE" ]] && REVIEWER_REQUEST_TEMPLATE="$_env_REVIEWER_REQUEST_TEMPLATE"
[[ -n "$_env_REVIEWER_LABEL" ]] && REVIEWER_LABEL="$_env_REVIEWER_LABEL"
[[ -n "$_env_REVIEWER_TRIGGER_LABEL" ]] && REVIEWER_TRIGGER_LABEL="$_env_REVIEWER_TRIGGER_LABEL"
[[ -n "$_env_REVIEWER_DISPLAY_NAME" ]] && REVIEWER_DISPLAY_NAME="$_env_REVIEWER_DISPLAY_NAME"

gh auth status >/dev/null

owner_repo="$(gh repo view --json nameWithOwner --jq '.nameWithOwner')"
owner="${owner_repo%%/*}"
repo="${owner_repo#*/}"

reviewer="${AGENT_REVIEWER:-codex}"
reviewer_config=".agents/reviewers/${reviewer}.env"

if [[ -f "$reviewer_config" ]]; then
  # Reviewer provider config fills defaults. Explicit shell/.agents env overrides win.
  _pre_REVIEWER_AUTHOR_REGEX="${REVIEWER_AUTHOR_REGEX-}"
  _pre_REVIEWER_REQUEST_TEMPLATE="${REVIEWER_REQUEST_TEMPLATE-}"
  _pre_REVIEWER_LABEL="${REVIEWER_LABEL-}"
  _pre_REVIEWER_TRIGGER_LABEL="${REVIEWER_TRIGGER_LABEL-}"
  _pre_REVIEWER_DISPLAY_NAME="${REVIEWER_DISPLAY_NAME-}"
  # shellcheck disable=SC1090
  source "$reviewer_config"
  [[ -n "$_pre_REVIEWER_AUTHOR_REGEX" ]] && REVIEWER_AUTHOR_REGEX="$_pre_REVIEWER_AUTHOR_REGEX"
  [[ -n "$_pre_REVIEWER_REQUEST_TEMPLATE" ]] && REVIEWER_REQUEST_TEMPLATE="$_pre_REVIEWER_REQUEST_TEMPLATE"
  [[ -n "$_pre_REVIEWER_LABEL" ]] && REVIEWER_LABEL="$_pre_REVIEWER_LABEL"
  [[ -n "$_pre_REVIEWER_TRIGGER_LABEL" ]] && REVIEWER_TRIGGER_LABEL="$_pre_REVIEWER_TRIGGER_LABEL"
  [[ -n "$_pre_REVIEWER_DISPLAY_NAME" ]] && REVIEWER_DISPLAY_NAME="$_pre_REVIEWER_DISPLAY_NAME"
else
  if [[ -z "${REVIEWER_AUTHOR_REGEX:-}" || -z "${REVIEWER_REQUEST_TEMPLATE:-}" ]]; then
    cat >&2 <<EOF_ERR
Unknown reviewer provider: $reviewer

Create:
  .agents/reviewers/${reviewer}.env
  .agents/reviewers/${reviewer}-request.md

or set REVIEWER_AUTHOR_REGEX and REVIEWER_REQUEST_TEMPLATE in the environment.
EOF_ERR
    exit 2
  fi
fi

reviewer_display="${REVIEWER_DISPLAY_NAME:-$reviewer}"
reviewer_author_regex="${REVIEWER_AUTHOR_REGEX:?REVIEWER_AUTHOR_REGEX is required}"
reviewer_label="${REVIEWER_LABEL:-review:${reviewer}}"
reviewer_trigger_label="${REVIEWER_TRIGGER_LABEL:-review:requested}"
reviewer_template="${REVIEWER_REQUEST_TEMPLATE:?REVIEWER_REQUEST_TEMPLATE is required}"

poll_seconds="${REVIEW_POLL_SECONDS:-${CODEX_POLL_SECONDS:-45}}"
max_review_loops="${AGENT_MAX_REVIEW_LOOPS:-${AGENT_MAX_CODEX_LOOPS:-3}}"
max_ambiguous="${AGENT_MAX_AMBIGUOUS_REVIEWS:-1}"
blocking_regex="${REVIEW_BLOCKING_REGEX:-changes_requested|p0|p1|blocking|must fix|do not merge|regression|security|failing test|missing test|not safe|incorrect}"
clean_regex="${REVIEW_CLEAN_REGEX:-no blocking|no p0|no p1|looks good|approved|no issues found|no findings}"
request_id="review-loop-${reviewer}-$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM"
request_time="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

state_dir=".agents/state/review-pr-${pr}"
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
if (( next_blocking_attempt > max_review_loops )); then
  gh pr edit "$pr" --add-label "agent:review-loop-limit" || true
  ./scripts/agent/escalate-to-supervisor.sh "$pr" "${reviewer_display} review loop exceeded ${max_review_loops} blocking attempts."
  exit 40
fi

printf 'Requesting %s review for PR #%s\n' "$reviewer_display" "$pr"
printf 'Request id: %s\n' "$request_id"

# Mark state before requesting review. Keep legacy codex labels when reviewer is codex.
labels=(
  --remove-label "agent:ready-for-human"
  --add-label "agent:review-loop"
  --add-label "$reviewer_trigger_label"
  --add-label "$reviewer_label"
)
if [[ "$reviewer" == "codex" ]]; then
  labels+=(--add-label "codex:requested")
fi
gh pr edit "$pr" "${labels[@]}" || true

if [[ ! -f "$reviewer_template" ]]; then
  echo "Reviewer request template not found: $reviewer_template" >&2
  exit 2
fi

request_comment_file="$state_dir/request-${request_id}-comment.md"
sed \
  -e "s/{{REQUEST_ID}}/$request_id/g" \
  -e "s/{{REVIEWER}}/$reviewer_display/g" \
  -e "s/{{PR}}/$pr/g" \
  "$reviewer_template" > "$request_comment_file"

gh pr comment "$pr" --body-file "$request_comment_file"

jq -n \
  --argjson pr "$pr" \
  --arg reviewer "$reviewer" \
  --arg reviewer_display "$reviewer_display" \
  --arg request_id "$request_id" \
  --arg request_time "$request_time" \
  --argjson poll_seconds "$poll_seconds" \
  --argjson max_review_loops "$max_review_loops" \
  --argjson max_ambiguous_reviews "$max_ambiguous" \
  --arg reviewer_author_regex "$reviewer_author_regex" \
  '{pr:$pr, reviewer:$reviewer, reviewer_display:$reviewer_display, request_id:$request_id, request_time:$request_time, poll_seconds:$poll_seconds, max_review_loops:$max_review_loops, max_ambiguous_reviews:$max_ambiguous_reviews, reviewer_author_regex:$reviewer_author_regex}' \
  > "$request_file"

cat <<EOF_WAIT
Waiting for a new ${reviewer_display} response after:
  $request_time

This script has no timeout by default.
Polling every ${poll_seconds}s.

State dir:
  $state_dir
EOF_WAIT

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
      --arg re "$reviewer_author_regex" \
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
    echo "No new ${reviewer_display} response yet for request $request_id. Sleeping ${poll_seconds}s..."
    sleep "$poll_seconds"
    continue
  fi

  echo "$all" > "$raw_file"

  {
    echo "# ${reviewer_display} feedback for PR #$pr"
    echo
    echo "Reviewer: \`$reviewer\`"
    echo "Request id: \`$request_id\`"
    echo "Request time: \`$request_time\`"
    echo
    echo "Detected reviewer items: $count"
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

  if printf '%s' "$body_lc" | grep -Eq "$blocking_regex"; then
    blocking=true
  fi

  if [[ "$blocking" != "true" ]]; then
    if printf '%s' "$body_lc" | grep -Eq "$clean_regex"; then
      ambiguous=false
    else
      ambiguous=true
    fi
  fi

  if [[ "$blocking" == "true" ]]; then
    echo "{\"timestamp\":\"$(date -u +%FT%TZ)\",\"request_id\":\"$request_id\",\"reviewer\":\"$reviewer\",\"result\":\"blocking\"}" >> "$attempts_file"

    gh pr edit "$pr" \
      --remove-label "agent:ready-for-human" \
      --add-label "agent:review-loop" \
      --add-label "agent:needs-fix" || true

    new_blocking_count="$(jq -s '[.[] | select(.result == "blocking")] | length' "$attempts_file")"
    if (( new_blocking_count >= max_review_loops )); then
      gh pr edit "$pr" --add-label "agent:review-loop-limit" || true
      ./scripts/agent/escalate-to-supervisor.sh "$pr" "${reviewer_display} returned blocking feedback ${new_blocking_count} times."
      exit 40
    fi

    cat > "$summary_file" <<EOF_SUMMARY
# Review result: blocking

PR: #$pr
Reviewer: $reviewer_display
Request id: $request_id

Feedback file:
$feedback_file

Required next step:
1. Read the feedback file.
2. Fix only blocking reviewer findings and directly related test gaps.
3. Do not expand scope.
4. Push to the same PR.
5. Run this script again:

\`\`\`bash
./scripts/agent/review-loop.sh $pr
\`\`\`

Do not merge.
EOF_SUMMARY

    cat "$summary_file"
    exit 20
  fi

  if [[ "$ambiguous" == "true" ]]; then
    echo "{\"timestamp\":\"$(date -u +%FT%TZ)\",\"request_id\":\"$request_id\",\"reviewer\":\"$reviewer\",\"result\":\"ambiguous\"}" >> "$attempts_file"

    new_ambiguous_count="$(jq -s '[.[] | select(.result == "ambiguous")] | length' "$attempts_file")"

    gh pr edit "$pr" --add-label "agent:needs-fix" || true

    if (( new_ambiguous_count > max_ambiguous )); then
      ./scripts/agent/escalate-to-supervisor.sh "$pr" "${reviewer_display} feedback was ambiguous more than ${max_ambiguous} time(s)."
      exit 40
    fi

    cat > "$summary_file" <<EOF_SUMMARY
# Review result: ambiguous

PR: #$pr
Reviewer: $reviewer_display
Request id: $request_id

Feedback file:
$feedback_file

The reviewer responded, but the script could not confidently classify the result as clean or blocking.

Required next step:
1. Read the feedback file.
2. If there are actionable/blocking findings, fix them, push, and rerun:

\`\`\`bash
./scripts/agent/review-loop.sh $pr
\`\`\`

3. If there are no blocking findings and checks are green, mark ready for human:

\`\`\`bash
./scripts/agent/mark-ready-for-human.sh $pr
\`\`\`

4. Do not merge.
EOF_SUMMARY

    cat "$summary_file"
    exit 21
  fi

  echo "{\"timestamp\":\"$(date -u +%FT%TZ)\",\"request_id\":\"$request_id\",\"reviewer\":\"$reviewer\",\"result\":\"clean\"}" >> "$attempts_file"

  ./scripts/agent/mark-ready-for-human.sh "$pr"

  cat > "$summary_file" <<EOF_SUMMARY
# Review result: clean

PR: #$pr
Reviewer: $reviewer_display
Request id: $request_id

Feedback file:
$feedback_file

Status:
- Reviewer response appeared non-blocking.
- PR marked \`agent:ready-for-human\`.
- Human merge still required.

Do not merge.
EOF_SUMMARY

  cat "$summary_file"
  exit 0
done
