"""Fail-closed redaction for external briefs and brokered tool results."""

from __future__ import annotations

from pathlib import PurePosixPath

DEFAULT_DENIED_PATH_SEGMENTS: frozenset[str] = frozenset(
    {
        ".env",
        ".ssh",
        ".gnupg",
        ".netrc",
    }
)

SENSITIVE_FILENAME_MARKERS: frozenset[str] = frozenset(
    {
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "credentials",
        "credentials.json",
        "secrets.json",
        ".pem",
    }
)

FULL_REPO_DUMP_REFS: frozenset[str] = frozenset(
    {
        ".",
        "./",
        "**",
        "**/*",
        "__FULL_REPO__",
        "repo://full_dump",
    }
)


class RedactionError(ValueError):
    """Raised when sensitive content must not be included in a brief or result."""


def _path_segments(path_like: str) -> tuple[str, ...]:
    normalized = path_like.strip().replace("\\", "/")
    if normalized.startswith("artifact:"):
        return ()
    return PurePosixPath(normalized).parts


def _is_sensitive_path(ref: str) -> bool:
    lowered = ref.strip().lower()
    for part in _path_segments(lowered):
        if part in DEFAULT_DENIED_PATH_SEGMENTS:
            return True
        for marker in SENSITIVE_FILENAME_MARKERS:
            if marker in part:
                return True
    return False


def _is_full_repo_dump_ref(ref: str) -> bool:
    normalized = ref.strip()
    if normalized in FULL_REPO_DUMP_REFS:
        return True
    lowered = normalized.lower()
    if lowered in FULL_REPO_DUMP_REFS:
        return True
    if lowered in {"repo://full", "full_repo_dump", "entire_repo"}:
        return True
    return False


def assert_context_ref_allowed(ref: str) -> None:
    """Raise if a context reference must not appear in an external brief."""
    if not ref or not isinstance(ref, str):
        raise RedactionError("context ref must be a non-empty string")

    if _is_full_repo_dump_ref(ref):
        raise RedactionError(f"full repo dump context ref blocked: {ref}")

    if _is_sensitive_path(ref):
        raise RedactionError(f"sensitive context ref blocked: {ref}")


def validate_context_refs(refs: list[str] | None) -> tuple[str, ...]:
    """Validate context refs and return them in stable order."""
    if refs is None:
        return ()
    validated: list[str] = []
    for ref in refs:
        assert_context_ref_allowed(ref)
        validated.append(ref)
    return tuple(validated)
