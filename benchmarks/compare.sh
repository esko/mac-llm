#!/usr/bin/env bash
# Compare two archived benchmark suites produced by run-suite.sh.
#
# Usage:
#   ./benchmarks/compare.sh qwen35 qwen36
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

exec python3 "${repo_root}/benchmarks/compare.py" "$@"
