"""Tests for Gemma 4 manual chat tokenization in mlx-sniper generate."""

from __future__ import annotations

import sys
from pathlib import Path

CLI_AGENT_SRC = (
    Path(__file__).resolve().parents[1]
    / "research"
    / "expert-sniper"
    / "cli-agent"
    / "src"
)
sys.path.insert(0, str(CLI_AGENT_SRC))

from mlx_expert_sniper.generate import _gemma4_chat_tokens


class _MockTokenizer:
    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        if text == "user\n":
            return [1000]
        if text == "model\n":
            return [1001]
        return [2000 + len(text)]


def test_gemma4_chat_tokens_single_user_turn() -> None:
    tok = _MockTokenizer()
    messages = [{"role": "user", "content": "Say hello in one sentence."}]

    tokens = _gemma4_chat_tokens(tok, messages)

    assert tokens[:2] == [2, 105]
    assert tokens[-1] == 1001
    assert [106, 107, 105] in (
        tokens[i : i + 3] for i in range(len(tokens) - 2)
    )


def test_gemma4_chat_tokens_folds_system_into_user() -> None:
    tok = _MockTokenizer()
    messages = [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "Hi"},
    ]

    tokens = _gemma4_chat_tokens(tok, messages)

    assert tokens[0:2] == [2, 105]
    assert 1000 in tokens
    assert tokens[-1] == 1001
