"""DeepSeek (OpenAI-compatible) streaming Summarizer.

The adapter owns the HTTP/SDK details; business modules only see the ``Summarizer``
port. ``stream`` yields ``delta.content`` fragments of one chat completion call so the
Analysis manager can persist and relay them over SSE. Any transport/upstream error is
raised to the caller, which maps it to ``analysis_failed`` and releases Quota.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable

import httpx

from app.config import Settings

logger = logging.getLogger("app.adapters.deepseek")


class DeepSeekSummarizer:
    def __init__(
        self,
        settings: Settings,
        *,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory or self._default_client

    def _default_client(self) -> httpx.AsyncClient:
        timeout = httpx.Timeout(
            connect=10.0,
            read=self._settings.analysis_timeout_seconds,
            write=30.0,
            pool=10.0,
        )
        return httpx.AsyncClient(base_url=self._settings.deepseek_base_url.rstrip("/"), timeout=timeout)

    def stream(self, *, prompt: str) -> AsyncIterator[str]:
        return self._stream(prompt)

    async def _stream(self, prompt: str) -> AsyncIterator[str]:
        api_key = self._settings.deepseek_api_key
        if not api_key:
            raise RuntimeError("APP_DEEPSEEK_API_KEY is not configured")

        payload = {
            "model": self._settings.deepseek_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        async with self._client_factory() as client:
            async with client.stream(
                "POST", "chat/completions", json=payload, headers=headers
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", "replace")[:500]
                    logger.warning(
                        "summarizer_upstream_error",
                        extra={
                            "event": "summarizer_upstream_error",
                            "status_code": response.status_code,
                        },
                    )
                    raise RuntimeError(f"DeepSeek returned {response.status_code}: {body}")

                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        return
                    try:
                        event = json.loads(data)
                    except ValueError:
                        continue
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    content = (choices[0].get("delta") or {}).get("content")
                    if content:
                        yield content
