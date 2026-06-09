"""Tests for Gemma 4 chat formatting in mlx-sniper generate."""

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

from mlx_expert_sniper.generate import (
    _gemma4_chat_tokens,
    _gemma4_manual_chat_text,
    _gemma4_normalize_messages,
)


class _MockTokenizer:
    bos_token = "<bos>"
    chat_template = None

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        return [1000 + len(text)]


def test_gemma4_manual_chat_text_uses_official_generation_prime() -> None:
    tok = _MockTokenizer()
    messages = _gemma4_normalize_messages(
        [{"role": "user", "content": "Say hello in one sentence."}]
    )
    text = _gemma4_manual_chat_text(tok, messages)

    assert text.startswith("<bos>")
    assert "<|turn>user\nSay hello in one sentence." in text
    assert text.endswith("<|turn>model\n<|channel>thought\n ")


def test_gemma4_chat_tokens_encodes_full_prompt() -> None:
    tok = _MockTokenizer()
    messages = [{"role": "user", "content": "Hi"}]

    tokens = _gemma4_chat_tokens(tok, messages)

    assert tokens == [1000 + len(_gemma4_manual_chat_text(tok, messages))]


def test_gemma4_chat_tokens_folds_system_into_user() -> None:
    tok = _MockTokenizer()
    messages = [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "Hi"},
    ]
    text = _gemma4_manual_chat_text(tok, _gemma4_normalize_messages(messages))

    assert "Be brief.\n\nHi" in text
    assert "<|turn>user\nBe brief.\n\nHi" in text
