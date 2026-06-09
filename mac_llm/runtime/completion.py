"""OpenAI-compatible completion client for managed runtime targets."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from mac_llm.runtime.target import RuntimeTarget

PostJsonFn = Callable[[str, dict[str, Any]], dict[str, Any]]

DEFAULT_COMPLETION_TIMEOUT_S = 120.0
DEFAULT_MAX_TOKENS = 512


def _completion_timeout_seconds() -> float:
    raw = os.environ.get("MAC_LLM_COMPLETION_TIMEOUT")
    if raw is None or raw == "":
        return DEFAULT_COMPLETION_TIMEOUT_S
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_COMPLETION_TIMEOUT_S


@dataclass(frozen=True)
class CompletionResult:
    """Result of a single completion request."""

    ok: bool
    text: str | None
    error: str | None
    ttft_ms: float | None = None
    tokens_per_second: float | None = None


def _extract_assistant_text(message: dict[str, Any]) -> str | None:
    """Return assistant text from content, or reasoning_content for thinking models."""
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content

    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning

    return None


def completion_url_for_target(target: RuntimeTarget) -> str:
    """Derive the chat-completions URL from a target health URL."""
    parsed = urlparse(target.health_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    return f"{base}/v1/chat/completions"


def run_completion(
    *,
    target: RuntimeTarget,
    prompt: str,
    model: str = "default",
    max_tokens: int = DEFAULT_MAX_TOKENS,
    post_json: PostJsonFn | None = None,
    timeout_seconds: float | None = None,
) -> CompletionResult:
    """Run a minimal OpenAI-compatible chat completion against a target."""
    if post_json is None:
        post_json = _default_post_json
    if timeout_seconds is None:
        timeout_seconds = _completion_timeout_seconds()

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "max_tokens": max_tokens,
        # Gemma 4 / thinking models: disable thinking so content is populated.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    started = time.perf_counter()
    try:
        response = post_json(
            completion_url_for_target(target),
            payload,
            timeout_seconds=timeout_seconds,
        )
    except urllib.error.URLError as exc:
        return CompletionResult(ok=False, text=None, error=str(exc.reason or exc))
    except TimeoutError:
        return CompletionResult(ok=False, text=None, error="completion request timed out")
    except OSError as exc:
        return CompletionResult(ok=False, text=None, error=str(exc))

    elapsed = time.perf_counter() - started
    if not isinstance(response, dict):
        return CompletionResult(ok=False, text=None, error="invalid completion response")

    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        error = response.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                return CompletionResult(ok=False, text=None, error=message)
        return CompletionResult(ok=False, text=None, error="completion returned no choices")

    first = choices[0]
    if not isinstance(first, dict):
        return CompletionResult(ok=False, text=None, error="invalid completion choice")

    message = first.get("message")
    if not isinstance(message, dict):
        return CompletionResult(ok=False, text=None, error="invalid completion message")

    text = _extract_assistant_text(message)
    if text is None:
        return CompletionResult(ok=False, text=None, error="completion returned empty content")

    usage = response.get("usage")
    tokens_per_second: float | None = None
    if isinstance(usage, dict):
        completion_tokens = usage.get("completion_tokens")
        if isinstance(completion_tokens, int) and completion_tokens > 0 and elapsed > 0:
            tokens_per_second = completion_tokens / elapsed

    return CompletionResult(
        ok=True,
        text=text,
        error=None,
        ttft_ms=elapsed * 1000,
        tokens_per_second=tokens_per_second,
    )


def _default_post_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float = DEFAULT_COMPLETION_TIMEOUT_S,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("completion response must be a JSON object")
    return parsed
