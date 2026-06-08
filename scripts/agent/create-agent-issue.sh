#!/usr/bin/env bash
set -euo pipefail

title="${1:?usage: create-agent-issue.sh TITLE WORKER|any BODY_FILE [draft|ready]}"
worker="${2:?usage: create-agent-issue.sh TITLE WORKER|any BODY_FILE [draft|ready]}"
body_file="${3:?usage: create-agent-issue.sh TITLE WORKER|any BODY_FILE [draft|ready]}"
state="${4:-draft}"

if ! [[ "$worker" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "unsafe worker id: $worker" >&2
  exit 2
fi

case "$state" in
  draft|ready) ;;
  *) echo "state must be draft or ready" >&2; exit 2 ;;
esac

labels="worker:$worker"
if [[ "$state" == "ready" ]]; then
  labels="$labels,agent:ready"
else
  labels="$labels,agent:draft"
fi

gh issue create \
  --title "$title" \
  --body-file "$body_file" \
  --label "$labels"
