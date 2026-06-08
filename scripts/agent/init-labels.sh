#!/usr/bin/env bash
set -euo pipefail

command -v gh >/dev/null || { echo "gh is required" >&2; exit 1; }

gh label create "agent:draft" --color "d4c5f9" --description "Planned but not launchable yet" || true
gh label create "agent:ready" --color "2ea44f" --description "Ready for a worker to claim" || true
gh label create "agent:claimed" --color "fbca04" --description "Claimed by an agent" || true
gh label create "agent:delegated" --color "fbca04" --description "Delegated to an issue-worker" || true
gh label create "agent:implementing" --color "fbca04" --description "Implementation in progress" || true
gh label create "agent:review-loop" --color "0366d6" --description "Reviewer loop active" || true
# Legacy compatibility label; prefer agent:review-loop.
gh label create "agent:codex-loop" --color "0366d6" --description "Legacy Codex review loop active" || true
gh label create "agent:needs-supervisor" --color "d73a4a" --description "Needs supervisor decision or takeover" || true
gh label create "agent:worker-stalled" --color "d73a4a" --description "Issue-worker reports stalled progress" || true
gh label create "agent:worker-incomplete" --color "d73a4a" --description "Issue-worker stopped before PR/review completion" || true
gh label create "agent:review-loop-limit" --color "d73a4a" --description "Review loop limit reached" || true
gh label create "agent:takeover-requested" --color "d73a4a" --description "Supervisor takeover requested" || true
gh label create "agent:supervisor-taking-over" --color "b60205" --description "Supervisor is taking over this PR" || true
gh label create "agent:ready-for-human" --color "6f42c1" --description "Ready for human review/merge" || true

gh label create "worker:any" --color "bfd4f2" --description "Open to any available implementor" || true
gh label create "worker:claude" --color "c5def5" --description "Claude-owned/suitable work" || true
gh label create "worker:cursor" --color "c5def5" --description "Cursor-owned/suitable work" || true
gh label create "worker:codex" --color "c5def5" --description "Codex planning/review work" || true

gh label create "review:requested" --color "0366d6" --description "Review requested" || true
gh label create "review:codex" --color "0366d6" --description "Codex reviewer selected" || true
gh label create "review:claude" --color "0366d6" --description "Claude reviewer selected" || true
gh label create "review:cursor" --color "0366d6" --description "Cursor reviewer selected" || true
# Legacy compatibility label; prefer review:requested + review:codex.
gh label create "codex:requested" --color "0366d6" --description "Legacy Codex review requested" || true

gh label create "size:xs" --color "ededed" --description "Extra-small task" || true
gh label create "size:s" --color "ededed" --description "Small task" || true
gh label create "size:m" --color "ededed" --description "Medium task" || true

gh label create "risk:low" --color "0e8a16" --description "Low-risk change" || true
gh label create "risk:medium" --color "fbca04" --description "Medium-risk change" || true
gh label create "risk:high" --color "d73a4a" --description "High-risk change" || true

echo "Agent labels initialized."
