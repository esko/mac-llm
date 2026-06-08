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

if [[ -z "$worker" ]]; then
  echo
  echo "Open generic ready issues (worker:any):"
  gh issue list --state open --label agent:ready --label worker:any --limit 20 || true
fi

echo
echo "Open delegated/claimed issues:"
gh issue list --state open --label agent:claimed "${label_args[@]}" --limit 20 || true

echo
echo "Open PRs:"
gh pr list --state open "${label_args[@]}" --limit 20 || true

echo
echo "Supervisor-needed PRs:"
gh pr list --state open --label agent:needs-supervisor "${label_args[@]}" --limit 20 || true


echo
echo "Worker-incomplete issues:"
gh issue list --state open --label agent:worker-incomplete "${label_args[@]}" --limit 20 || true

echo
echo "Worker-incomplete PRs:"
gh pr list --state open --label agent:worker-incomplete "${label_args[@]}" --limit 20 || true
