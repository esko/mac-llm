#!/usr/bin/env bash
# Run the standard mac-llm benchmark suite and archive artifacts for A/B comparison.
#
# Usage:
#   export MAC_LLM_MODEL_LOCAL_FAST=...
#   export MAC_LLM_MODEL_LOCAL_DEEP_MOE=...
#   ./benchmarks/run-suite.sh qwen35
#
# Options:
#   --skip-kv    Skip bench kv (may fail without KV runtime integration)
#   --skip-swap  Skip bench swap lifecycle (M3); still runs swap-sequence
set -euo pipefail

label=""
skip_kv=0
skip_swap=0

usage() {
  cat <<'EOF'
Usage: ./benchmarks/run-suite.sh <label> [--skip-kv] [--skip-swap]

Run smoke, swap, and swap-sequence benchmarks, archiving artifacts under:
  benchmarks/comparison/<label>/

Set MAC_LLM_MODEL_LOCAL_FAST and MAC_LLM_MODEL_LOCAL_DEEP_MOE before running.

Examples:
  ./benchmarks/run-suite.sh qwen35
  ./benchmarks/run-suite.sh gemma4 --skip-kv
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --skip-kv)
      skip_kv=1
      shift
      ;;
    --skip-swap)
      skip_swap=1
      shift
      ;;
    -*)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [[ -n "$label" ]]; then
        echo "unexpected argument: $1" >&2
        usage >&2
        exit 2
      fi
      label="$1"
      shift
      ;;
  esac
done

if [[ -z "$label" ]]; then
  usage >&2
  exit 2
fi

if ! command -v mac-llm >/dev/null 2>&1; then
  echo "mac-llm not found on PATH; activate the project venv first." >&2
  exit 1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

archive_root="benchmarks/comparison/${label}"
mkdir -p "$archive_root"

archive_latest_run() {
  local dest_name="$1"
  local latest=""
  latest="$(ls -td benchmarks/runs/*/ 2>/dev/null | head -1 || true)"
  if [[ -z "$latest" ]]; then
    echo "no benchmark run found to archive for ${dest_name}" >&2
    return 1
  fi
  local dest="${archive_root}/${dest_name}"
  rm -rf "$dest"
  mkdir -p "$dest"
  cp -a "${latest%/}" "$dest/"
  echo "archived ${latest} -> ${dest}/"
}

write_manifest() {
  local manifest="${archive_root}/manifest.json"
  python3 - "$manifest" "$label" "$archive_root" <<'PY'
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

manifest_path = Path(sys.argv[1])
label = sys.argv[2]
archive_root = Path(sys.argv[3])

payload = {
    "label": label,
    "created_at": datetime.now(tz=UTC).isoformat(),
    "archive_root": str(archive_root),
    "model_local_fast": os.environ.get("MAC_LLM_MODEL_LOCAL_FAST"),
    "model_local_deep_moe": os.environ.get("MAC_LLM_MODEL_LOCAL_DEEP_MOE"),
}
manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
print(f"wrote {manifest_path}")
PY
}

echo "=== label: ${label} ==="
echo "archive root: ${archive_root}"

if [[ -z "${MAC_LLM_MODEL_LOCAL_FAST:-}" ]]; then
  echo "warning: MAC_LLM_MODEL_LOCAL_FAST is not set" >&2
fi
if [[ -z "${MAC_LLM_MODEL_LOCAL_DEEP_MOE:-}" ]]; then
  echo "warning: MAC_LLM_MODEL_LOCAL_DEEP_MOE is not set" >&2
fi

echo "=== smoke local_fast ==="
mac-llm runtime start local_fast
mac-llm runtime smoke local_fast --artifact-root "${archive_root}/smoke-fast"
mac-llm runtime stop local_fast
mac-llm runtime orphan-check local_fast

echo "=== smoke local_deep_moe ==="
mac-llm runtime start local_deep_moe
mac-llm runtime smoke local_deep_moe --artifact-root "${archive_root}/smoke-deep"
mac-llm runtime stop local_deep_moe
mac-llm runtime orphan-check local_deep_moe

if [[ "$skip_swap" -eq 0 ]]; then
  echo "=== bench swap (lifecycle) ==="
  mac-llm bench swap --from local_fast --to local_fast
  archive_latest_run "bench-swap"
else
  echo "=== bench swap skipped ==="
fi

echo "=== bench swap-sequence (primary proof) ==="
mac-llm bench swap-sequence local_fast local_deep_moe local_fast
archive_latest_run "bench-swap-sequence"

if [[ "$skip_kv" -eq 0 ]]; then
  echo "=== bench kv (optional) ==="
  if mac-llm bench kv --target local_deep_moe --prefix repo-review; then
    archive_latest_run "bench-kv"
  else
    echo "bench kv failed or unavailable; continuing" >&2
  fi
else
  echo "=== bench kv skipped ==="
fi

write_manifest

echo "Done. Artifacts under ${archive_root}/"
echo "Compare with: ./benchmarks/compare.sh qwen35 gemma4"
