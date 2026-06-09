#!/usr/bin/env python3
"""Compare archived mac-llm benchmark suites side by side."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_events(run_dir: Path) -> list[dict[str, Any]]:
    jsonl_path = run_dir / "run.jsonl"
    if not jsonl_path.is_file():
        return []
    return [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]


def _latest_run_dir(base: Path) -> Path | None:
    if not base.is_dir():
        return None

    nested = base / "benchmarks" / "runs"
    if nested.is_dir():
        candidates = [path for path in nested.iterdir() if path.is_dir()]
    else:
        candidates = [path for path in base.iterdir() if path.is_dir()]

    if not candidates:
        return None
    return max(candidates, key=lambda path: path.name)


def _find_suite_run(archive_root: Path, suite_name: str) -> Path | None:
    return _latest_run_dir(archive_root / suite_name)


def _fmt(value: Any, *, digits: int = 3) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return f"{float(value):.{digits}f}"
    return str(value)


def _orphan_ok(metadata: dict[str, Any]) -> str:
    orphan = metadata.get("orphan_check") or metadata.get("orphan_status")
    if not isinstance(orphan, dict):
        return "-"
    if "orphaned" in orphan:
        return "clean" if not orphan["orphaned"] else "orphan"
    if orphan.get("status") == "ok":
        return "clean"
    return str(orphan.get("status", orphan))


def _smoke_rows(archive_root: Path, target: str) -> list[dict[str, str]]:
    run_dir = _find_suite_run(archive_root, f"smoke-{target}")
    if run_dir is None:
        return []

    for event in _load_events(run_dir):
        if event.get("event") != "smoke.complete":
            continue
        benchmark = (event.get("metadata") or {}).get("benchmark") or {}
        return [
            {
                "suite": f"smoke {target}",
                "step": target,
                "load_s": _fmt(benchmark.get("load_time_s")),
                "ttft_s": _fmt(benchmark.get("ttft_s")),
                "tok_s": _fmt(benchmark.get("tokens_per_second")),
                "orphan": _orphan_ok(benchmark),
            }
        ]
    return []


def _swap_sequence_rows(archive_root: Path) -> list[dict[str, str]]:
    run_dir = _find_suite_run(archive_root, "bench-swap-sequence")
    if run_dir is None:
        return []

    rows: list[dict[str, str]] = []
    for event in _load_events(run_dir):
        if event.get("event") != "bench.swap_sequence.step.complete":
            continue
        metadata = event.get("metadata") or {}
        rows.append(
            {
                "suite": "swap-sequence",
                "step": str(metadata.get("target_id", metadata.get("step", "?"))),
                "load_s": _fmt(metadata.get("load_time_s")),
                "ttft_s": _fmt(metadata.get("ttft_s")),
                "tok_s": _fmt(metadata.get("tokens_per_second")),
                "orphan": _orphan_ok(metadata),
            }
        )
    return rows


def _collect_rows(archive_root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    rows.extend(_smoke_rows(archive_root, "fast"))
    rows.extend(_smoke_rows(archive_root, "deep"))
    rows.extend(_swap_sequence_rows(archive_root))
    return rows


def _print_table(left_label: str, right_label: str, left_rows: list[dict[str, str]], right_rows: list[dict[str, str]]) -> None:
    keys = [f"{row['suite']}:{row['step']}" for row in left_rows]
    for row in right_rows:
        key = f"{row['suite']}:{row['step']}"
        if key not in keys:
            keys.append(key)

    headers = ["suite", "step", f"{left_label} load", f"{right_label} load", f"{left_label} ttft", f"{right_label} ttft", f"{left_label} tok/s", f"{right_label} tok/s", f"{left_label} orphan", f"{right_label} orphan"]
    left_by_key = {f"{row['suite']}:{row['step']}": row for row in left_rows}
    right_by_key = {f"{row['suite']}:{row['step']}": row for row in right_rows}

    print("\t".join(headers))
    for key in keys:
        left = left_by_key.get(key, {})
        right = right_by_key.get(key, {})
        suite, step = key.split(":", 1)
        print(
            "\t".join(
                [
                    suite,
                    step,
                    left.get("load_s", "-"),
                    right.get("load_s", "-"),
                    left.get("ttft_s", "-"),
                    right.get("ttft_s", "-"),
                    left.get("tok_s", "-"),
                    right.get("tok_s", "-"),
                    left.get("orphan", "-"),
                    right.get("orphan", "-"),
                ]
            )
        )


def _load_manifest(archive_root: Path) -> dict[str, Any] | None:
    manifest_path = archive_root / "manifest.json"
    if not manifest_path.is_file():
        return None
    return json.loads(manifest_path.read_text())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", help="First archive label (e.g. qwen35)")
    parser.add_argument("right", help="Second archive label (e.g. qwen36)")
    parser.add_argument(
        "--root",
        default="benchmarks/comparison",
        help="Comparison archive root (default: benchmarks/comparison)",
    )
    args = parser.parse_args(argv)

    repo_root = Path.cwd()
    root = repo_root / args.root
    left_root = root / args.left
    right_root = root / args.right

    if not left_root.is_dir():
        print(f"missing archive: {left_root}", file=sys.stderr)
        return 1
    if not right_root.is_dir():
        print(f"missing archive: {right_root}", file=sys.stderr)
        return 1

    left_manifest = _load_manifest(left_root)
    right_manifest = _load_manifest(right_root)
    if left_manifest:
        print(f"# {args.left}: fast={left_manifest.get('model_local_fast')}")
        print(f"# {args.left}: deep={left_manifest.get('model_local_deep_moe')}")
    if right_manifest:
        print(f"# {args.right}: fast={right_manifest.get('model_local_fast')}")
        print(f"# {args.right}: deep={right_manifest.get('model_local_deep_moe')}")

    left_rows = _collect_rows(left_root)
    right_rows = _collect_rows(right_root)
    if not left_rows and not right_rows:
        print("no comparable metrics found in either archive", file=sys.stderr)
        return 1

    _print_table(args.left, args.right, left_rows, right_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
