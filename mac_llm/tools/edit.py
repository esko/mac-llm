"""Approval-gated write/edit/test tool implementations."""

from __future__ import annotations

import hashlib
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any


class EditToolError(RuntimeError):
    """Raised when a write/edit/test tool cannot complete."""


_SHELL_METACHAR_RE = re.compile(r"[;|&$`<>]")


def hash_text(text: str) -> str:
    """Return sha256 digest for a text block."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def replace_block_hash_checked(
    file_path: Path,
    args: dict[str, Any],
) -> str:
    """Replace an exact block when old_hash matches the current block digest."""
    old_text = args["old_text"]
    new_text = args["new_text"]
    provided_hash = args["old_hash"]

    if hash_text(old_text) != provided_hash:
        raise EditToolError("hash mismatch: old_hash does not match old_text")

    content = file_path.read_text(encoding="utf-8")
    if old_text not in content:
        raise EditToolError("block not found: old_text is not present in file")

    updated = content.replace(old_text, new_text, 1)
    file_path.write_text(updated, encoding="utf-8")
    return f"replaced block in {file_path.name}\n"


def _parse_unified_hunks(patch: str) -> list[tuple[list[str], list[str]]]:
    """Parse unified diff hunks into (old_lines, new_lines) pairs."""
    hunks: list[tuple[list[str], list[str]]] = []
    old_lines: list[str] = []
    new_lines: list[str] = []
    in_hunk = False

    for line in patch.splitlines():
        if line.startswith("@@"):
            if in_hunk:
                hunks.append((old_lines, new_lines))
            old_lines = []
            new_lines = []
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith(" "):
            old_lines.append(line[1:])
            new_lines.append(line[1:])
        elif line.startswith("-"):
            old_lines.append(line[1:])
        elif line.startswith("+"):
            new_lines.append(line[1:])

    if in_hunk:
        hunks.append((old_lines, new_lines))
    return hunks


def propose_patch(file_path: Path, args: dict[str, Any]) -> str:
    """Apply a unified diff patch to a repo file."""
    patch = args["patch"]
    hunks = _parse_unified_hunks(patch)
    if not hunks:
        raise EditToolError("invalid patch: no hunks found")

    working = file_path.read_text(encoding="utf-8")

    # Apply hunks sequentially against the current file content.
    for old_block, new_block in hunks:
        old_text = "".join(f"{line}\n" for line in old_block)
        new_text = "".join(f"{line}\n" for line in new_block)
        if old_text not in working:
            raise EditToolError("patch does not apply: hunk context not found")
        working = working.replace(old_text, new_text, 1)

    file_path.write_text(working, encoding="utf-8")
    return f"applied patch to {file_path.name}\n"


def _validate_test_command(command: str) -> list[str]:
    if _SHELL_METACHAR_RE.search(command):
        raise EditToolError("disallowed command: shell metacharacters are not allowed")

    argv = shlex.split(command)
    if not argv:
        raise EditToolError("disallowed command: empty command")

    if argv[0] == "pytest":
        return argv
    if len(argv) >= 3 and argv[0] == "python" and argv[1] == "-m" and argv[2] == "pytest":
        return argv

    raise EditToolError("disallowed command: only pytest invocations are allowed")


def run_test_command(repo_root: Path, args: dict[str, Any]) -> str:
    """Run a constrained pytest invocation without shell."""
    argv = _validate_test_command(args["command"])
    result = subprocess.run(
        argv,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    output = result.stdout
    if result.stderr:
        output = f"{output}{result.stderr}"
    if result.returncode != 0:
        raise EditToolError(output.strip() or "test command failed")
    return output


_APPROVAL_GATED_HANDLERS = {
    "replace_block_hash_checked": replace_block_hash_checked,
    "propose_patch": propose_patch,
}


def execute_approval_gated_tool(
    tool: str,
    repo_root: Path,
    args: dict[str, Any],
    *,
    resolved_paths: dict[str, Path],
) -> str:
    """Execute a registered approval-gated tool and return raw output."""
    handler = _APPROVAL_GATED_HANDLERS.get(tool)
    if handler is not None:
        return handler(resolved_paths["file"], args)

    if tool == "run_test_command":
        return run_test_command(repo_root, args)

    raise EditToolError(f"unsupported approval-gated tool: {tool}")
