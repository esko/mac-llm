"""Console entry point for mac-llm."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mac_llm import __version__
from mac_llm.bench.artifacts import BenchmarkArtifactWriter
from mac_llm.bench.kv import run_kv_benchmark_cli
from mac_llm.bench.swap import run_swap_benchmark
from mac_llm.runtime.manager import RuntimeLifecycleError, RuntimeManager, render_start_command
from mac_llm.roles.select import UnknownRoleError, select_target
from mac_llm.runtime.smoke import run_smoke
from mac_llm.runtime.target import UnknownTargetError, get_target


def _cmd_role_select(role: str, difficulty: str) -> int:
    try:
        result = select_target(role, difficulty=difficulty)
    except UnknownRoleError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except UnknownTargetError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    payload = {
        "role": role,
        "target_id": result.target_id,
        "deep_escalation": result.deep_escalation,
        "cache_strategy": result.cache_strategy,
    }
    sys.stdout.write(json.dumps(payload) + "\n")
    return 0


def _cmd_runtime_render(target_id: str) -> int:
    try:
        target = get_target(target_id)
    except UnknownTargetError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    rendered = render_start_command(target)
    sys.stdout.write(rendered.format_output())
    return 0


def _cmd_runtime_start(target_id: str) -> int:
    try:
        target = get_target(target_id)
    except UnknownTargetError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    manager = RuntimeManager(target=target)
    try:
        state = manager.start()
    except RuntimeLifecycleError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"started pid {state.pid} on port {state.port}")
    return 0


def _cmd_runtime_stop(target_id: str) -> int:
    try:
        target = get_target(target_id)
    except UnknownTargetError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    manager = RuntimeManager(target=target)
    try:
        manager.stop()
    except RuntimeLifecycleError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("stopped runtime")
    return 0


def _cmd_runtime_status(target_id: str) -> int:
    try:
        target = get_target(target_id)
    except UnknownTargetError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    manager = RuntimeManager(target=target)
    state = manager.status()
    if state is None:
        payload = {
            "target_id": target.target_id,
            "status": "stopped",
            "pid": None,
            "port": target.port,
            "start_time": None,
            "stop_timeout": target.stop_timeout,
            "last_error": None,
        }
    else:
        payload = {
            "target_id": state.target_id,
            "status": state.status,
            "pid": state.pid,
            "port": state.port,
            "start_time": state.start_time,
            "stop_timeout": state.stop_timeout,
            "last_error": state.last_error,
        }

    sys.stdout.write(json.dumps(payload) + "\n")
    return 0


def _cmd_runtime_health(target_id: str) -> int:
    try:
        target = get_target(target_id)
    except UnknownTargetError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    manager = RuntimeManager(target=target)
    result = manager.health_check()
    payload = {"ok": result.ok, "message": result.message}
    sys.stdout.write(json.dumps(payload) + "\n")
    return 0 if result.ok else 1


def _cmd_bench_swap(from_target_id: str, to_target_id: str) -> int:
    result = run_swap_benchmark(
        from_target_id=from_target_id,
        to_target_id=to_target_id,
    )
    rel_dir = result.run_dir.relative_to(Path.cwd())
    if result.ok:
        print(f"benchmark completed; artifacts in {rel_dir}")
        return 0

    print(result.message, file=sys.stderr)
    print(f"failure artifact written to {rel_dir}", file=sys.stderr)
    return 1


def _cmd_bench_kv(target_id: str, prefix_name: str) -> int:
    root = Path.cwd()
    writer = BenchmarkArtifactWriter(root)
    result = run_kv_benchmark_cli(
        target_id=target_id,
        prefix_name=prefix_name,
        root=root,
        writer=writer,
    )
    if result.status == "ok":
        assert result.record is not None
        print(f"kv benchmark complete: cache_helped={result.record.cache_helped}")
        print(f"artifact: {writer.run_dir}")
        return 0

    print(result.message or "kv benchmark failed", file=sys.stderr)
    print(f"artifact: {writer.run_dir}", file=sys.stderr)
    return 1


def _cmd_runtime_orphan_check(target_id: str) -> int:
    try:
        target = get_target(target_id)
    except UnknownTargetError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    manager = RuntimeManager(target=target)
    result = manager.orphan_check()
    payload = {
        "has_orphan": result.has_orphan,
        "port_occupied": result.port_occupied,
        "occupying_pid": result.occupying_pid,
        "stale_state_pid": result.stale_state_pid,
        "message": result.message,
    }
    sys.stdout.write(json.dumps(payload) + "\n")
    return 1 if result.has_orphan else 0


def _cmd_runtime_smoke(target_id: str, artifact_root: str | None) -> int:
    try:
        target = get_target(target_id)
    except UnknownTargetError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    root = Path(artifact_root) if artifact_root else Path.cwd()
    result = run_smoke(target, artifact_root=root)
    payload = result.record.to_dict()
    payload["artifact_dir"] = str(result.artifact_dir)
    sys.stdout.write(json.dumps(payload) + "\n")
    return 0 if result.record.status == "ok" else 1


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="mac-llm",
        description="Local-agent runtime for Apple Silicon Mac Mini",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    role_parser = subparsers.add_parser("role", help="Role-target selection")
    role_subparsers = role_parser.add_subparsers(dest="role_command")

    select_parser = role_subparsers.add_parser(
        "select",
        help="Print the resolved runtime target for a role",
    )
    select_parser.add_argument("role", help="Agent role (e.g. review, coding)")
    select_parser.add_argument(
        "--difficulty",
        default="medium",
        choices=["low", "medium", "high", "very_high"],
        help="Task difficulty hint for deep-escalation policy",
    )

    runtime_parser = subparsers.add_parser("runtime", help="Runtime management")
    runtime_subparsers = runtime_parser.add_subparsers(dest="runtime_command")

    render_parser = runtime_subparsers.add_parser(
        "render",
        help="Render start command and metadata without starting a process",
    )
    render_parser.add_argument("target_id", help="Runtime target id")

    start_parser = runtime_subparsers.add_parser(
        "start",
        help="Start a configured runtime target when available",
    )
    start_parser.add_argument("target_id", help="Runtime target id")

    stop_parser = runtime_subparsers.add_parser(
        "stop",
        help="Stop the managed runtime for a target",
    )
    stop_parser.add_argument("target_id", help="Runtime target id")

    status_parser = runtime_subparsers.add_parser(
        "status",
        help="Show persisted runtime state for a target",
    )
    status_parser.add_argument("target_id", help="Runtime target id")

    health_parser = runtime_subparsers.add_parser(
        "health",
        help="Probe the configured health URL for a target",
    )
    health_parser.add_argument("target_id", help="Runtime target id")

    orphan_parser = runtime_subparsers.add_parser(
        "orphan-check",
        help="Detect leftover processes or stale state for a target",
    )
    orphan_parser.add_argument("target_id", help="Runtime target id")

    smoke_parser = runtime_subparsers.add_parser(
        "smoke",
        help="Run an OpenAI-compatible smoke request and write a benchmark artifact",
    )
    smoke_parser.add_argument("target_id", help="Runtime target id")
    smoke_parser.add_argument(
        "--artifact-root",
        help="Directory root for benchmarks/runs artifacts (default: current directory)",
    )

    bench_parser = subparsers.add_parser("bench", help="Benchmark commands")
    bench_subparsers = bench_parser.add_subparsers(dest="bench_command")

    kv_parser = bench_subparsers.add_parser(
        "kv",
        help="Compare cold vs warm/restored prompt-cache performance",
    )
    kv_parser.add_argument(
        "--target",
        required=True,
        help="Runtime target id (e.g. local_deep_moe)",
    )
    kv_parser.add_argument(
        "--prefix",
        required=True,
        help="Built-in prefix prompt name (e.g. repo-review)",
    )

    swap_parser = bench_subparsers.add_parser(
        "swap",
        help="Run a fast→fast swap benchmark with artifact output",
    )
    swap_parser.add_argument(
        "--from",
        dest="from_target",
        required=True,
        help="Source runtime target id",
    )
    swap_parser.add_argument(
        "--to",
        dest="to_target",
        required=True,
        help="Destination runtime target id",
    )

    args = parser.parse_args(argv)

    if args.command == "role":
        if args.role_command == "select":
            raise SystemExit(_cmd_role_select(args.role, args.difficulty))

    if args.command == "runtime":
        if args.runtime_command == "render":
            raise SystemExit(_cmd_runtime_render(args.target_id))
        if args.runtime_command == "start":
            raise SystemExit(_cmd_runtime_start(args.target_id))
        if args.runtime_command == "stop":
            raise SystemExit(_cmd_runtime_stop(args.target_id))
        if args.runtime_command == "status":
            raise SystemExit(_cmd_runtime_status(args.target_id))
        if args.runtime_command == "health":
            raise SystemExit(_cmd_runtime_health(args.target_id))
        if args.runtime_command == "orphan-check":
            raise SystemExit(_cmd_runtime_orphan_check(args.target_id))
        if args.runtime_command == "smoke":
            raise SystemExit(_cmd_runtime_smoke(args.target_id, args.artifact_root))

    if args.command == "bench":
        if args.bench_command == "kv":
            raise SystemExit(_cmd_bench_kv(args.target, args.prefix))
        if args.bench_command == "swap":
            raise SystemExit(_cmd_bench_swap(args.from_target, args.to_target))

    parser.print_help()


if __name__ == "__main__":
    main()
