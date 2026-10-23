"""DeepSeek (OpenAI-compatible) streaming Summarizer. Implemented by ticket #8."""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.config import Settings


class DeepSeekSummarizer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def stream(self, *, prompt: str) -> AsyncIterator[str]:
        return self._stream(prompt)

    async def _stream(self, prompt: str) -> AsyncIterator[str]:
        raise NotImplementedError("DeepSeekSummarizer.stream is implemented in ticket #8")
        yield ""  # pragma: no cover - makes this an async generator
