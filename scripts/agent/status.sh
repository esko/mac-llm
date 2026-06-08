#!/usr/bin/env bash
set -euo pipefail

worker="${1:-}"

if [[ -n "$worker" ]]; then
  label_args=(--label "worker:${worker}")
else
  label_args=()
fi

echo "Open ready issues:"
gh issue list --state open --label agent:ready "${label_args[@]}" --limit 20 || true

echo
echo "Open delegated/claimed issues:"
gh issue list --state open --label agent:claimed "${label_args[@]}" --limit 20 || true

echo
echo "Open PRs:"
gh pr list --state open "${label_args[@]}" --limit 20 || true

echo
echo "Supervisor-needed PRs:"
gh pr list --state open --label agent:needs-supervisor "${label_args[@]}" --limit 20 || true
