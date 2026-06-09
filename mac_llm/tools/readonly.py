"""Pre-approved read-only tool implementations."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any


class ReadOnlyToolError(RuntimeError):
    """Raised when a read-only tool cannot complete."""


def _run_git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise ReadOnlyToolError(stderr)
    return result.stdout


def read_file_range(repo_root: Path, args: dict[str, Any], file_path: Path) -> str:
    lines = file_path.read_text(encoding="utf-8").splitlines()
    start = args["start_line"]
    end = args["end_line"]
    selected = lines[start - 1 : end]
    return "\n".join(selected) + ("\n" if selected else "")


def search_text(repo_root: Path, args: dict[str, Any], search_root: Path) -> str:
    pattern = re.compile(args["pattern"])
    matches: list[str] = []
    paths = (
        [search_root]
        if search_root.is_file()
        else sorted(p for p in search_root.rglob("*") if p.is_file())
    )
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(repo_root).as_posix()
        for line_no, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                matches.append(f"{rel}:{line_no}:{line}")
    return "\n".join(matches) + ("\n" if matches else "")


def git_status(repo_root: Path, args: dict[str, Any]) -> str:
    return _run_git(repo_root, "status", "--short", "--branch")


def git_diff(repo_root: Path, args: dict[str, Any]) -> str:
    return _run_git(repo_root, "diff")


def list_files(repo_root: Path, args: dict[str, Any], list_root: Path) -> str:
    recursive = bool(args.get("recursive", False))
    if list_root.is_file():
        return list_root.relative_to(repo_root).as_posix() + "\n"
    if recursive:
        paths = sorted(
            p.relative_to(repo_root).as_posix()
            for p in list_root.rglob("*")
            if p.is_file()
        )
    else:
        paths = sorted(
            p.relative_to(repo_root).as_posix()
            for p in list_root.iterdir()
            if p.is_file()
        )
    return "\n".join(paths) + ("\n" if paths else "")


_READ_ONLY_HANDLERS = {
    "read_file_range": read_file_range,
    "search_text": search_text,
    "git_status": git_status,
    "git_diff": git_diff,
    "list_files": list_files,
}


def execute_read_only_tool(
    tool: str,
    repo_root: Path,
    args: dict[str, Any],
    *,
    resolved_paths: dict[str, Path],
) -> str:
    """Execute a registered read-only tool and return raw output."""
    handler = _READ_ONLY_HANDLERS.get(tool)
    if handler is None:
        raise ReadOnlyToolError(f"unsupported read-only tool: {tool}")

    if tool == "read_file_range":
        return handler(repo_root, args, resolved_paths["file"])
    if tool == "search_text":
        return handler(repo_root, args, resolved_paths.get("path", repo_root))
    if tool == "list_files":
        return handler(repo_root, args, resolved_paths["path"])
    return handler(repo_root, args)
