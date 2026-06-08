#!/usr/bin/env bash
set -euo pipefail

# Legacy compatibility wrapper. The queue-watching/delegation role belongs to the implementor.
# Use scripts/agent/implementor-next.sh in new docs and prompts.
exec "$(dirname "$0")/implementor-next.sh" "$@"
