"""Compressor seam (Chunk 4 / The Token Company replaces the default).

Used on the COMPRESS_AND_EXECUTE path: reuse is unsafe but the prompt is bloated,
so we compress context before executing. Default is a passthrough that reports no
savings, so Chunk 1 is testable without the Token Company integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class CompressionResult:
    messages: list[dict[str, Any]]
    tokens_before: int
    tokens_after: int

    @property
    def saved_tokens(self) -> int:
        return max(0, self.tokens_before - self.tokens_after)


class Compressor(Protocol):
    def compress(self, messages: list[dict[str, Any]]) -> CompressionResult: ...


class PassthroughCompressor:
    """No-op default. Returns messages unchanged with zero savings."""

    def compress(self, messages: list[dict[str, Any]]) -> CompressionResult:
        from redundant.estimate import count_message_tokens

        tokens = count_message_tokens(messages)
        return CompressionResult(messages=messages, tokens_before=tokens, tokens_after=tokens)
