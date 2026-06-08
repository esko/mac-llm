"""Console entry point for mac-llm."""

from __future__ import annotations

import argparse
import sys

from mac_llm import __version__
from mac_llm.runtime.manager import render_start_command
from mac_llm.runtime.target import UnknownTargetError, get_target


def _cmd_runtime_render(target_id: str) -> int:
    try:
        target = get_target(target_id)
    except UnknownTargetError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    rendered = render_start_command(target)
    sys.stdout.write(rendered.format_output())
    return 0


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

    runtime_parser = subparsers.add_parser("runtime", help="Runtime management")
    runtime_subparsers = runtime_parser.add_subparsers(dest="runtime_command")

    render_parser = runtime_subparsers.add_parser(
        "render",
        help="Render start command and metadata without starting a process",
    )
    render_parser.add_argument("target_id", help="Runtime target id")

    args = parser.parse_args(argv)

    if args.command == "runtime" and args.runtime_command == "render":
        raise SystemExit(_cmd_runtime_render(args.target_id))

    parser.print_help()


if __name__ == "__main__":
    main()
